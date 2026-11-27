# -*- coding: utf-8 -*-
"""Transport-agnostic application: raw JSON bytes in, JSON text out."""
from __future__ import annotations

import json
from typing import Any

from .errors import INTERNAL_ERROR, INVALID_REQUEST, PARSE_ERROR
from .protocol import MCPProtocol


def _pack(obj: Any) -> str:
    """Single-line UTF-8 JSON: stdio is newline-delimited, never pretty-printed."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Application:
    def __init__(self, register_tools: bool = True):
        if register_tools:
            from . import tools  # noqa: F401 - import triggers tool registration
        self.protocol = MCPProtocol()

    @staticmethod
    def _error(rid: Any, code: int, message: str) -> str:
        return _pack({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": code, "message": message}})

    def process(self, raw: bytes | str) -> str | None:
        """Return a JSON string, or None when there is nothing to reply to.

        Notifications produce no reply. A batch with only notifications also
        produces no reply, as required by JSON-RPC 2.0.
        """
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return self._error(None, PARSE_ERROR, "invalid utf-8")
        else:
            text = raw
        try:
            msg = json.loads(text)
        except (ValueError, TypeError):
            return self._error(None, PARSE_ERROR, "parse error")
        try:
            reply = self.protocol.handle(msg)
        except Exception as exc:  # noqa: BLE001 - keep the stdio stream alive
            return self._error(None, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if reply is None:
            return None
        return _pack(reply)