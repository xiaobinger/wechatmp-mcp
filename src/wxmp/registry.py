# -*- coding: utf-8 -*-
"""Lightweight tool registry with JSON-Schema-ish argument validation.

Dependency-free on purpose: no pydantic, no MCP SDK.
"""
from __future__ import annotations

import json
import re
import traceback
from typing import Any, Callable

from .errors import ParamError, ToolError

TOOL_DEFS: dict[str, dict] = {}

_OUTPUT_SCHEMA = {"type": "object", "additionalProperties": True}

# MCP exposes exactly one `description` per tool, and registries / marketplaces
# ingest that same string, so both languages have to live in one field. English
# comes first because that is what most clients and indexers read; the Chinese
# block follows under a marker so a reader (or a test) can always tell them apart.
ZH_MARKER = "【中文】"
LANG_SEPARATOR = "\n\n"


def _squash(text: str) -> str:
    return " ".join(str(text).split())


def bilingual(en: str, zh: str) -> str:
    """One description holding an English block and a Chinese block."""
    return f"{_squash(en)}{LANG_SEPARATOR}{ZH_MARKER}{_squash(zh)}"


def param(en: str, zh: str) -> str:
    """A short bilingual line for one argument, compact enough for a schema."""
    return f"{_squash(en)} / {_squash(zh)}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def tool(name: str, description: str, properties: dict,
         required: tuple[str, ...] = (), extra_schema: dict | None = None):
    """Register a callable as an MCP tool."""
    def deco(fn: Callable):
        schema: dict = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = list(required)
        if extra_schema:
            schema.update(extra_schema)
        TOOL_DEFS[name] = {
            "name": name,
            "description": description,
            "inputSchema": schema,
            "outputSchema": _OUTPUT_SCHEMA,
            "handler": fn,
        }
        return fn
    return deco


def list_tools() -> list[dict]:
    return [
        {k: v for k, v in d.items() if k != "handler"}
        for d in TOOL_DEFS.values()
    ]


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _check(prop: dict, key: str, value: Any) -> None:
    types = prop.get("type")
    if types:
        allowed = [types] if isinstance(types, str) else list(types)
        if value is None and "null" in allowed:
            return
        if not any(_type_ok(t, value) for t in allowed):
            raise ParamError(
                "invalid argument type",
                {"argument": key, "expected": allowed,
                 "got": type(value).__name__},
            )
    if "enum" in prop and value not in prop["enum"]:
        raise ParamError("value not allowed",
                         {"argument": key, "allowed": prop["enum"]})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in prop and value < prop["minimum"]:
            raise ParamError("value below minimum",
                             {"argument": key, "minimum": prop["minimum"]})
        if "maximum" in prop and value > prop["maximum"]:
            raise ParamError("value above maximum",
                             {"argument": key, "maximum": prop["maximum"]})
    if isinstance(value, str):
        if "minLength" in prop and len(value) < prop["minLength"]:
            raise ParamError("string too short", {"argument": key})
        if "maxLength" in prop and len(value) > prop["maxLength"]:
            raise ParamError("string too long",
                             {"argument": key, "max": prop["maxLength"],
                              "got": len(value)})
        if "pattern" in prop and not re.search(prop["pattern"], value):
            raise ParamError("string does not match pattern",
                             {"argument": key, "pattern": prop["pattern"]})
    if isinstance(value, list):
        if "minItems" in prop and len(value) < prop["minItems"]:
            raise ParamError("array too short",
                             {"argument": key, "min": prop["minItems"],
                              "got": len(value)})
        if "maxItems" in prop and len(value) > prop["maxItems"]:
            raise ParamError("array too long",
                             {"argument": key, "max": prop["maxItems"],
                              "got": len(value)})


def validate_args(name: str, args: Any) -> dict:
    d = TOOL_DEFS.get(name)
    if d is None:
        raise ParamError("unknown tool",
                         {"tool": name, "available": sorted(TOOL_DEFS)})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ParamError("arguments must be an object")
    schema = d["inputSchema"]
    props = schema["properties"]
    args = dict(args)
    for k in schema.get("required", []):
        if k not in args or args[k] is None:
            raise ParamError("missing required argument", {"argument": k})
    for k, v in args.items():
        if k not in props:
            raise ParamError("unknown argument",
                             {"argument": k, "allowed": sorted(props)})
        _check(props[k], k, v)
    for k, p in props.items():
        if k not in args and "default" in p:
            args[k] = p["default"]
    return args


def call_tool(name: str, args: Any) -> dict:
    """Execute a tool and always return an MCP tools/call result."""
    try:
        checked = validate_args(name, args)
        result = TOOL_DEFS[name]["handler"](**checked)
        if result is None:
            result = {"ok": True}
        if not isinstance(result, dict):
            result = {"ok": True, "data": result}
        is_error = bool(result.get("ok") is False)
    except ToolError as exc:
        result = {"ok": False, "error": exc.message,
                  "error_code": exc.code, "error_data": exc.data}
        is_error = True
    except Exception as exc:  # noqa: BLE001 - never let a tool crash the server
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": -32603,
            "error_data": {"traceback": traceback.format_exc(limit=8)},
        }
        is_error = True
    return {
        "content": [{"type": "text", "text": dumps(result)}],
        "structuredContent": result,
        "isError": is_error,
    }