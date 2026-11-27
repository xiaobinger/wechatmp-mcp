# -*- coding: utf-8 -*-
"""MCP JSON-RPC 2.0 protocol handling, independent of the transport."""
from __future__ import annotations

import json
from typing import Any

from . import SERVER_NAME, __version__, config
from .errors import (INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST,
                     METHOD_NOT_FOUND, PARSE_ERROR)
from .registry import call_tool, list_tools

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]

_INSTRUCTIONS_EN = (
    "WeChat Official Account (公众号) back-office automation for 贴图 / image "
    "messages and 图文 / articles. Call mp_status first: the browser profile "
    "keeps the login session, and mp_status reports whether a human needs to "
    "scan a QR code with mp_account_login. mp_publish_material is the single "
    "entry point for new material: pass kind=tietu or kind=article, a title, a "
    "cover image, the body (article bodies may embed a local image with a line "
    "that holds only ![](/path.png)) and action=draft to keep it or "
    "action=publish to submit it straight from the editor. mp_create_tietu "
    "stays for multi-image 贴图 galleries. Publishing is never finished by the "
    "server alone and always needs confirm=true: after the 发表 dialog the "
    "console shows a 扫码 page that the admin must scan with WeChat, the item "
    "then lands in 发表记录 about two minutes later, so the tools poll that list "
    "and only report verified=true for a NEW msgid. mp_publish_draft and "
    "mp_delete_draft are irreversible and also require confirm=true; "
    "mp_list_published reads 发表记录 (proof), mp_list_drafts reads 草稿箱. "
    "Argument limits are enforced, not advisory: a title is 1-64 characters "
    "(one CJK ideograph counts as one) and an empty or longer one is refused "
    f"with -32602; content (the body, or the 贴图 description) is refused above "
    f"{config.CONTENT_MAX_CHARS} characters rather than clipped; a 贴图 "
    f"description is clipped to {config.TIETU_DESC_LIMIT} characters and "
    f"reports "
    "desc_clipped=true; an article digest is clipped to 120 and its author to "
    "64; every picture must be an absolute path to an existing "
    "png/jpg/jpeg/gif/webp file of at most 10 MB, a 贴图 gallery holds at most "
    "20 pictures including its cover, and a 图文 needs a cover because the "
    "console has no local cover upload. Read each tool's description before "
    "calling: it lists its own field limits, defaults and reply flags. "
    "Login is manual by design: the server only screenshots the QR code and "
    "polls the redirect. It never reads cookies, tokens or credentials out of "
    "the browser profile."
)
_INSTRUCTIONS_ZH = (
    "公众号后台自动化，面向贴图 / 图片消息和图文 / 文章。先调 mp_status：登录态保存在"
    "浏览器 profile 里，mp_status 会说明是否还需要人调 mp_account_login 扫码。"
    "mp_publish_material 是新建素材的统一入口：传 kind=tietu 或 kind=article、"
    "标题、封面图、正文（图文正文里可以放一整行 ![](/path.png) 来插入本地图片），"
    "action=draft 存草稿，action=publish 直接从编辑器发表。多图贴图集仍可用 "
    "mp_create_tietu。发表从来不是服务端单独完成的，而且一定需要 confirm=true："
    "发表弹窗之后控制台会出现扫码页，必须由管理员用微信扫，约 2 分钟后内容才落到"
    "发表记录；所以这些工具会轮询那张表，只有出现新 msgid 才报 verified=true。"
    "mp_publish_draft 和 mp_delete_draft 不可撤销，同样需要 confirm=true；"
    "mp_list_published 读发表记录（证据），mp_list_drafts 读草稿箱。"
    "参数限制是硬性的，不是建议：标题 1–64 个字符（一个汉字算一个），空标题或超长"
    "直接返回 -32602；content（正文或贴图描述）超过 "
    f"{config.CONTENT_MAX_CHARS} 字符直接拒绝，不截断；"
    f"贴图描述超过 {config.TIETU_DESC_LIMIT} 字会被截断并回 desc_clipped=true；"
    "图文摘要超过 120 字截断、作者超过 64 字截断；每张图必须是存在的绝对路径、"
    "格式为 png/jpg/jpeg/gif/webp、单张不超过 10 MB；贴图图集最多 20 张（含封面）；"
    "图文必须给封面，因为后台没有本地封面入口。调用前先读对应工具的描述，"
    "每个工具自己的字段限制、默认值和回包标志都写在里面。"
    "登录按设计只能人工：服务端只截图二维码并轮询跳转，"
    "从不读取浏览器 profile 里的 cookie、token 或凭据。"
)

INSTRUCTIONS = f"{_INSTRUCTIONS_EN}\n\n【中文】{_INSTRUCTIONS_ZH}"


def _error(rid: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": err}


def _ok(rid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


class MCPProtocol:
    def __init__(self):
        self.protocol_version = LATEST_PROTOCOL
        self.client_info: dict | None = None
        self.client_capabilities: dict | None = None
        self.initialized = False

    # ---- request dispatch -------------------------------------------------
    def handle(self, msg: Any) -> dict | None:
        if isinstance(msg, list):
            if not msg:
                return _error(None, INVALID_REQUEST, "empty batch")
            replies = [r for m in msg if (r := self.handle(m)) is not None]
            return replies or None
        if not isinstance(msg, dict):
            return _error(None, INVALID_REQUEST, "request must be an object")
        if msg.get("jsonrpc") != "2.0":
            return _error(msg.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'")

        method = msg.get("method")
        rid = msg.get("id")
        is_notification = "id" not in msg
        if not isinstance(method, str):
            return None if is_notification else _error(rid, INVALID_REQUEST, "missing method")

        try:
            result = self._dispatch(method, msg.get("params") or {})
        except Exception as exc:  # noqa: BLE001
            if is_notification:
                return None
            return _error(rid, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

        if is_notification:
            return None
        if result is self._METHOD_NOT_FOUND:
            return _error(rid, METHOD_NOT_FOUND, f"method not found: {method}")
        return _ok(rid, result)

    _METHOD_NOT_FOUND = object()

    def _dispatch(self, method: str, params: dict):
        if method == "initialize":
            return self._initialize(params)
        if method.startswith("notifications/"):
            if method == "notifications/initialized":
                self.initialized = True
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": list_tools()}
        if method == "tools/call":
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            name = params.get("name")
            if not isinstance(name, str):
                raise ValueError("tool name must be a string")
            return call_tool(name, params.get("arguments"))
        if method == "resources/list":
            return {"resources": []}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "resources/read":
            return self._METHOD_NOT_FOUND
        if method == "prompts/list":
            return {"prompts": []}
        if method == "prompts/get":
            return self._METHOD_NOT_FOUND
        if method == "logging/setLevel":
            return {}
        if method == "completion/complete":
            return {"completion": {"values": [], "total": 0, "hasMore": False}}
        return self._METHOD_NOT_FOUND

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        if requested in SUPPORTED_PROTOCOLS:
            self.protocol_version = requested
        else:
            self.protocol_version = LATEST_PROTOCOL
        self.client_info = params.get("clientInfo")
        self.client_capabilities = params.get("capabilities")
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        }