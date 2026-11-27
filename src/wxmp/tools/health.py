# -*- coding: utf-8 -*-
"""Capability probe for clients and troubleshooting."""
from __future__ import annotations

import importlib.util
import platform
import sys

from .. import SERVER_NAME, __version__
from .. import config
from ..browser import session
from ..protocol import SUPPORTED_PROTOCOLS
from ..registry import TOOL_DEFS, bilingual, tool


def _spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@tool(
    "server_health",
    bilingual(
        "Report server version, supported MCP protocol versions, the registered "
        "tools and the browser configuration (profile directory, channel, headless "
        "mode, console limits). Use it to diagnose a client that cannot reach the "
        "console.",
        "报告服务版本、支持的 MCP 协议版本、已注册的工具，以及浏览器配置"
        "（profile 目录、浏览器通道、无头模式、控制台限制）。"
        "客户端连不上后台时用它排查。",
    ),
    {},
)
def server_health() -> dict:
    settings = config.settings()
    profile = config.profile_dir()
    try:
        entries = sum(1 for _ in profile.iterdir())
    except OSError:
        entries = -1
    session_ = session()
    return {
        "ok": True,
        "server": SERVER_NAME,
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "protocol_versions": list(SUPPORTED_PROTOCOLS),
        "transports": ["stdio", "http (Streamable HTTP)"],
        "tools": sorted(TOOL_DEFS),
        "tool_count": len(TOOL_DEFS),
        "dependencies": {
            "playwright": _spec("playwright"),
        },
        "settings": settings,
        "profile": {
            "dir": str(profile),
            "entries": entries,
            "warm": session_.warm,
        },
        "notes": [
            "login is manual: mp_account_login screenshots the QR code and polls "
            "the redirect",
            "cookies and tokens are never exported; token=… is masked in every reply",
            "mp_publish_material builds 贴图 (kind=tietu) and 图文 (kind=article) "
            "from a title, a cover, a body and action=draft|publish",
            "mp_create_tietu keeps a draft by default; action=publish or "
            "action=schedule needs confirm=true and an admin scan",
            "an article cover goes through the console's image library: the "
            "console offers 从正文选择 / 从图片库选择 / 微信扫码上传 / 一键生成封面 "
            "and no local upload",
            "a publish is only reported verified when a new msgid appears in "
            "发表记录 (mp_list_published)",
        ],
    }