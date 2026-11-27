# -*- coding: utf-8 -*-
"""Account tools: session status and QR-code login."""
from __future__ import annotations

import time

from .. import browser, config, console, security
from ..errors import LoginRequired
from ..registry import bilingual, param, tool


def _shot_path(name: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(config.out_dir() / f"{name}_{stamp}.png")


@tool(
    "mp_status",
    bilingual(
        "Check whether the WeChat Official Account console session is still valid. "
        "Opens the console root in the controlled browser and reports login state, "
        "the masked session token, the account nickname when it can be read, and "
        "the profile directory in use. Call this before any other mp_* tool.",
        "检查公众号后台的会话是否仍然有效。在受控浏览器里打开后台首页，回报登录状态、"
        "打码后的会话 token、能读到时的账号昵称，以及当前使用的 profile 目录。"
        "调用其它任何 mp_* 工具之前，先调它。",
    ),
    {
        "screenshot": {"type": "boolean", "default": False,
                       "description": param(
                           "also save a full-page PNG to the out/ directory",
                           "同时把一张整页 PNG 存到 out/ 目录")},
    },
)
def mp_status(screenshot: bool = False) -> dict:
    with browser.session().exclusive() as page:
        console.open_home(page)
        status = console.read_status(page)
        if screenshot:
            status["screenshot"] = console.screenshot(page, _shot_path("status"))
        status["profile_dir"] = str(config.profile_dir())
        status["headless"] = config.headless()
        status["channel"] = config.browser_channel() or "(bundled chromium)"
        status["ok"] = True
        if not status.get("logged_in"):
            status["next"] = "call mp_account_login, then scan the QR code with WeChat"
        return status


@tool(
    "mp_account_login",
    bilingual(
        "Start the QR-code login: opens the console, writes a screenshot of the QR "
        "code into the out/ directory and waits for a human to scan it with WeChat. "
        "Returns as soon as the console redirects with a session token. The login "
        "is manual by design — no credential is ever handled by the server. "
        "Limits: timeout_s is 15-600 seconds (default 180); when it runs out the "
        "call raises LoginRequired and the reply carries the QR path, so call it "
        "again rather than retrying blindly. If the profile already holds a "
        "session the call returns immediately with already_logged_in=true.",
        "启动扫码登录：打开后台、把二维码截图存到 out/ 目录，然后等人用微信扫。"
        "控制台一旦带着 session token 跳转就立即返回。登录按设计只能人工完成，"
        "服务端从不接触任何凭据。限制：timeout_s 取值 15–600 秒（默认 180）；"
        "超时会抛 LoginRequired，回包里带二维码路径，所以再调一次即可，"
        "不要盲目重试。如果 profile 里已有会话，会立刻返回 "
        "already_logged_in=true。",
    ),
    {
        "timeout_s": {"type": "integer", "minimum": 15, "maximum": 600,
                      "default": 180,
                      "description": param(
                          "how long to wait for the human scan, 15-600 seconds; "
                          "the call answers early when the redirect happens",
                          "等待人工扫码的秒数，取值 15–600；一旦跳转就提前返回")},
    },
)
def mp_account_login(timeout_s: int = 180) -> dict:
    with browser.session().exclusive() as page:
        console.open_home(page)
        status = console.read_status(page)
        if status.get("logged_in"):
            status["ok"] = True
            status["already_logged_in"] = True
            return status
        qr = console.qr_screenshot(page, _shot_path("login_qr"))
        try:
            result = console.wait_for_login(page, timeout_s=timeout_s)
        except LoginRequired as exc:
            data = dict(exc.data or {})
            data["qr"] = qr
            data["hint"] = ("the browser window is still open on the login page: "
                            "scan the QR shown there (or the PNG at qr), then call "
                            "mp_account_login again")
            raise LoginRequired(exc.message, data) from exc
        result["ok"] = True
        result["qr"] = qr
        result["qr_note"] = ("the PNG is a fallback; the live QR is in the browser "
                             "window that the server keeps open")
        result["profile_dir"] = str(config.profile_dir())
        result["note"] = ("the session is persisted in the Playwright profile; "
                          "later calls reuse it until the console expires it")
        return result