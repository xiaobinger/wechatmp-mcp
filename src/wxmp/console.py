# -*- coding: utf-8 -*-
"""Console session helpers: login detection, QR capture, token extraction.

Verified against the live backend (mp.weixin.qq.com):

* Logged out: the landing page at ``/`` shows 使用账号登录 / 扫码登录 and the
  URL carries no ``token`` parameter.
* Logged in: the landing page redirects to
  ``/cgi-bin/home?t=home/index&lang=zh_CN&token=<digits>``.

Only the numeric ``token`` query parameter is read, and it is masked before it
leaves the process.
"""
from __future__ import annotations

import logging
import time

from . import config, security
from .errors import LoginRequired, PageError

LOG = logging.getLogger("wxmp.console")

# Text that only appears on the logged-out landing page.
LOGIN_MARKERS = ("使用账号登录", "扫码登录", "微信扫一扫")

# Candidate nodes holding the login QR image, most specific first.
QR_SELECTORS = (
    "img.login__type__container__scan__qrcode",
    ".login__type__container__scan__qrcode img",
    "img[src*='qrcode']",
    "img.qrcode",
    ".qrcode img",
)

# Best-effort account label selectors; never fatal when absent.
NICK_SELECTORS = (
    "#nick_name",
    ".weui-desktop-account__nickname",
    ".weui-desktop-account__name",
    ".account_name",
)


def open_home(page) -> None:
    """Land on the console root so the redirect reveals the session state."""
    page.goto(config.url_login(), wait_until="domcontentloaded",
              timeout=config.timeout_ms())
    page.wait_for_timeout(1200)


def body_text(page) -> str:
    try:
        return page.inner_text("body") or ""
    except Exception:  # noqa: BLE001 - about:blank and closed pages
        return ""


def login_markers_present(page) -> list[str]:
    text = body_text(page)
    return [m for m in LOGIN_MARKERS if m in text]


def read_status(page) -> dict:
    """Describe the session without leaking the token."""
    url = page.url or ""
    token = security.token_from_url(url)
    logged_in = bool(token) and "/cgi-bin/" in url
    info: dict = {
        "logged_in": logged_in,
        "token": security.mask(token),
        "url": security.mask_url(url),
    }
    if logged_in:
        nick = nickname(page)
        if nick:
            info["account"] = nick
    else:
        markers = login_markers_present(page)
        info["login_markers"] = markers
        info["hint"] = ("not logged in: call mp_account_login, then scan the QR code "
                        "that mp_account_login writes to the out/ directory")
    return info


def nickname(page) -> str | None:
    """Account nickname — best effort, the console markup varies by account."""
    for sel in NICK_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                text = (loc.inner_text() or "").strip()
                if text:
                    return text
        except Exception:  # noqa: BLE001
            continue
    return None


def qr_screenshot(page, path: str) -> dict:
    """Save the login QR to ``path``; falls back to a full-page screenshot."""
    for sel in QR_SELECTORS:
        try:
            loc = page.locator(sel).first
            if not loc.count() or not loc.is_visible():
                continue
            box = loc.bounding_box()
            if not box or box["width"] < 80 or box["height"] < 80:
                continue
            loc.screenshot(path=path)
            return {"path": path, "selector": sel,
                    "width": round(box["width"]), "height": round(box["height"]),
                    "full_page": False}
        except Exception as exc:  # noqa: BLE001
            LOG.debug("QR selector %s failed: %s", sel, exc)
    page.screenshot(path=path, full_page=True)
    return {"path": path, "selector": None, "full_page": True,
            "hint": "the QR node was not matched; the whole page was captured"}


def wait_for_login(page, timeout_s: int = 180, poll_ms: int = 1000) -> dict:
    """Poll until the console redirects with a token, i.e. the scan succeeded."""
    deadline = time.time() + max(10, int(timeout_s))
    last = None
    while time.time() < deadline:
        url = page.url or ""
        token = security.token_from_url(url)
        if token and "/cgi-bin/" in url:
            # Give the home page a moment to render its account block.
            page.wait_for_timeout(1000)
            return {"logged_in": True, "token": security.mask(token),
                    "url": security.mask_url(url),
                    "account": nickname(page) or None}
        markers = login_markers_present(page)
        if markers != last:
            LOG.info("still waiting for the scan; markers=%s", markers)
            last = markers
        try:
            page.wait_for_timeout(poll_ms)
        except Exception as exc:  # noqa: BLE001 - window closed by the human
            raise LoginRequired(
                "the browser window closed before the login completed",
                {"detail": str(exc)},
            ) from exc
    raise LoginRequired(
        "login was not completed in time",
        {"waited_seconds": int(timeout_s),
         "hint": "call mp_account_login again, or scan faster",
         "url": security.mask_url(page.url or "")},
    )


def require_token(page) -> str:
    """Token for building console URLs, or a clear LoginRequired."""
    token = security.token_from_url(page.url or "")
    if token:
        return token
    raise LoginRequired(
        "not logged in; run mp_account_login and scan the QR code",
        {"url": security.mask_url(page.url or ""),
         "login_markers": login_markers_present(page)},
    )


def ensure_logged_in(page, timeout_s: float = 12.0) -> str:
    """Navigate to the root and return a token, or raise LoginRequired.

    The token only appears after the console redirects, and that redirect is not
    instant: with a valid persisted session the shell can still sit on the login
    page for a few seconds on a cold profile load. Reading ``page.url`` once
    therefore reported "not logged in" intermittently, so the token is awaited.
    A login shell that persists is what decides the negative answer.
    """
    open_home(page)
    start = time.time()
    deadline = start + max(1.0, float(timeout_s))
    marker_hits = 0
    while True:
        url = page.url or ""
        token = security.token_from_url(url)
        if token and "/cgi-bin/" in url:
            return token
        markers = login_markers_present(page)
        marker_hits = marker_hits + 1 if markers else 0
        if marker_hits >= 2 and time.time() - start >= 3.0:
            raise LoginRequired(
                "not logged in; run mp_account_login and scan the QR code",
                {"url": security.mask_url(url), "login_markers": markers},
            )
        if time.time() >= deadline:
            raise LoginRequired(
                "the console revealed no session in time; it may still be loading",
                {"waited_seconds": int(timeout_s), "url": security.mask_url(url),
                 "login_markers": markers,
                 "hint": "retry first; if it keeps failing the session expired, "
                         "so run mp_account_login"},
            )
        try:
            page.wait_for_timeout(400)
        except Exception as exc:  # noqa: BLE001 - the human closed the window
            raise LoginRequired("the browser closed while checking the session",
                                {"detail": str(exc)}) from exc


def screenshot(page, path: str) -> str:
    try:
        page.screenshot(path=path, full_page=True)
        return path
    except Exception as exc:  # noqa: BLE001
        raise PageError("could not take a screenshot", {"detail": str(exc)}) from exc