# -*- coding: utf-8 -*-
"""Playwright browser session with a persistent profile.

Design notes
------------
* One process-wide session. The MCP tools are called one at a time, so the
  synchronous Playwright API is enough; ``exclusive()`` serialises access when
  the optional HTTP transport serves requests from several threads.
* The login session lives **only** inside the Playwright profile directory.
  No cookie, storage or token value is ever read out of it, and the ``token=``
  query parameter is masked everywhere it is reported.
* Playwright's sync API is thread-affine. If a call arrives from a different
  thread than the one that started the driver, the session is torn down and
  rebuilt on the new thread instead of raising.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import threading

from . import config
from .errors import BrowserUnavailable, PageError

LOG = logging.getLogger("wxmp.browser")


class Browser:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ident: int | None = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._closed = False

    # ---- lifecycle --------------------------------------------------------
    @staticmethod
    def _api():
        try:
            from playwright.sync_api import Error as PWError
            from playwright.sync_api import TimeoutError as PWTimeout
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on the env
            raise BrowserUnavailable(
                "playwright is not installed",
                {
                    "detail": str(exc),
                    "hint": "pip install playwright — a system Edge/Chrome is "
                            "enough (WXMP_BROWSER_CHANNEL=msedge), so "
                            "`playwright install` is optional",
                },
            ) from exc
        return sync_playwright, PWError, PWTimeout

    def _start(self) -> None:
        sync_playwright, _, _ = self._api()
        self._closed = False
        self._pw = sync_playwright().start()
        try:
            cdp = config.cdp_url()
            if cdp:
                self._browser = self._pw.chromium.connect_over_cdp(cdp)
                contexts = self._browser.contexts
                self._context = (contexts[0] if contexts
                                 else self._browser.new_context(
                                     viewport=config.viewport(),
                                     device_scale_factor=config.device_scale(),
                                     locale="zh-CN"))
            else:
                self._context = self._launch_persistent()
            self._context.set_default_timeout(config.timeout_ms())
        except BrowserUnavailable:
            self._stop()
            raise
        except Exception as exc:  # noqa: BLE001 - surface it as a tool error
            self._stop()
            raise BrowserUnavailable(
                "could not start a browser",
                {"detail": f"{type(exc).__name__}: {exc}",
                 "profile_dir": str(config.profile_dir()),
                 "channel": config.browser_channel() or "(bundled chromium)",
                 "hint": "close other windows using this profile, or set "
                         "WXMP_BROWSER_CHANNEL to an installed browser "
                         "(msedge / chrome), or attach with WXMP_CDP_URL"},
            ) from exc
        atexit.register(self.close)

    def _launch_persistent(self):
        kwargs = dict(
            user_data_dir=str(config.profile_dir()),
            headless=config.headless(),
            viewport=config.viewport(),
            device_scale_factor=config.device_scale(),
            locale="zh-CN",
            slow_mo=config.slow_mo_ms(),
            accept_downloads=False,
            # The console is friendlier when it does not see the automation flag.
            args=["--disable-blink-features=AutomationControlled"],
        )
        channel = config.browser_channel()
        if channel:
            try:
                return self._pw.chromium.launch_persistent_context(
                    channel=channel, **kwargs)
            except Exception as exc:  # noqa: BLE001 - fall back to bundled build
                LOG.warning("browser channel %r unavailable (%s); "
                            "falling back to the bundled chromium",
                            channel, type(exc).__name__)
        return self._pw.chromium.launch_persistent_context(**kwargs)

    def _stop(self) -> None:
        for attr in ("_context", "_browser"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None
        self._page = None

    def close(self) -> None:
        with self._lock:
            self._stop()
            self._ident = None
            self._closed = True

    def _ensure(self) -> None:
        ident = threading.get_ident()
        if self._ident is not None and self._ident != ident:
            LOG.info("browser session re-bound to thread %s", ident)
            self._stop()
            self._ident = None
        if self._ident is None:
            self._start()
            self._ident = ident

    @property
    def warm(self) -> bool:
        """True once a driver has been started (no browser launch implied)."""
        return self._ident is not None

    # ---- page access ------------------------------------------------------
    def page(self):
        self._ensure()
        if self._page is None or self._page.is_closed():
            pages = [p for p in self._context.pages if not p.is_closed()]
            self._page = pages[0] if pages else self._context.new_page()
        return self._page

    @contextlib.contextmanager
    def exclusive(self):
        with self._lock:
            yield self.page()

    def reset_page(self) -> None:
        """Drop the current tab so the next call starts from a clean page."""
        with self._lock:
            if self._page is not None:
                try:
                    self._page.close()
                except Exception:  # noqa: BLE001
                    pass
            self._page = None

    # ---- navigation -------------------------------------------------------
    def goto(self, page, url: str, wait_until: str = "domcontentloaded"):
        _, _, PWTimeout = self._api()
        try:
            return page.goto(url, wait_until=wait_until,
                             timeout=config.timeout_ms())
        except PWTimeout as exc:
            raise PageError("page did not load in time",
                            {"url": _mask(url), "detail": str(exc).strip()}) from exc
        except Exception as exc:  # noqa: BLE001
            raise PageError("navigation failed",
                            {"url": _mask(url), "detail": str(exc).strip()}) from exc


def _mask(url: str) -> str:
    from .security import mask_url
    return mask_url(url)


_SESSION: Browser | None = None
_SESSION_LOCK = threading.Lock()


def session() -> Browser:
    """Process-wide browser session, created on first use."""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None or _SESSION._closed:
            _SESSION = Browser()
        return _SESSION


def shutdown() -> None:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None:
            _SESSION.close()
            _SESSION = None