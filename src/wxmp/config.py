# -*- coding: utf-8 -*-
"""Environment-driven configuration.

Everything is optional: the defaults keep the profile and the screenshots in
the directory the server was started from, which is what an MCP client
expects. Nothing secret is ever written here — the login session lives only
inside the Playwright profile directory, and the URL token is kept in memory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_URL = "https://mp.weixin.qq.com"

# Console endpoints (verified against the live backend).
PATH_HOME = "/cgi-bin/home?t=home/index&lang=zh_CN&token={token}"
PATH_LOGIN = "/"
# 贴图 (image message) editor. type=77 is the "media" family, createType=8 is
# the 贴图 flavour — both are required, the editor silently opens the article
# composer without createType=8.
PATH_TIETU_NEW = ("/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit"
                  "&isNew=1&type=77&createType=8&token={token}&lang=zh_CN")
# 图文 (article) editor: the very same endpoint **without** createType=8. The
# article composer and the 贴图 composer share one URL template; the extra
# parameter is what selects the flavour.
PATH_ARTICLE_NEW = ("/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit"
                    "&isNew=1&type=77&token={token}&lang=zh_CN")
PATH_DRAFT_EDIT = ("/cgi-bin/appmsg?t=media/appmsg_edit&action=edit"
                   "&type={mtype}&appmsgid={appmsgid}&token={token}&lang=zh_CN")
# 草稿箱. ``action=list_card`` renders the draft cards; ``action=list`` renders
# 发表记录 instead. The console normalises item_show_type to 0 (文章) for every
# value tried, so a 贴图-only view is not addressable by URL in this version.
PATH_DRAFT_LIST = ("/cgi-bin/appmsg?begin=0&count={count}&type=77&action=list_card"
                   "&item_show_type={item_type}&token={token}&lang=zh_CN")
ITEM_TYPE = {"article": 0, "tietu": 8}

# 发表记录 (published, not drafts). ``action=list`` on ``/cgi-bin/appmsg?`` renders
# the same page, but this JSON endpoint is the read-only way in: it answers with
# ``publish_page.publish_list`` and needs nothing but the session cookie + token.
PATH_PUBLISHED_LIST = ("/cgi-bin/appmsgpublish?sub=list&begin=0&count={count}"
                       "&f=json&token={token}&lang=zh_CN&ajax=1")

# Platform limits measured on the live 贴图 editor.
TIETU_MAX_IMAGES = 20
TIETU_DESC_LIMIT = 1000
TIETU_TITLE_LIMIT = 64

# 图文 (article) limits. The title counter reads 0/64 like the 贴图 one; the
# 摘要 field is clipped to 120 so a long digest is trimmed instead of silently
# rejected by the console.
ARTICLE_TITLE_LIMIT = 64
ARTICLE_DIGEST_LIMIT = 120
ARTICLE_AUTHOR_LIMIT = 64

# The body/description string has no measured console limit worth copying; this is
# a guard against a runaway prompt, set far above any real article so a long body
# is refused loudly instead of being typed for minutes.
CONTENT_MAX_CHARS = 50000


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def project_root() -> Path:
    """Directory that owns ``out/`` and ``.state/``.

    Resolved from the package location, **not** from ``Path.cwd()``. An MCP
    client starts the server with an arbitrary working directory, and a
    cwd-relative profile silently created a second, empty profile: the console
    then answered "not logged in" while the real profile still held the session.
    """
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], here.parents[1]):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


def out_dir() -> Path:
    raw = os.environ.get("WXMP_OUT_DIR")
    path = Path(raw).expanduser() if raw else project_root() / "out"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir() -> Path:
    """Persistent Playwright profile: cookies survive between server restarts."""
    raw = os.environ.get("WXMP_PROFILE_DIR")
    path = (Path(raw).expanduser() if raw
            else project_root() / ".state" / "profile")
    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_channel() -> str:
    """Installed browser to drive. Empty string means Playwright's own build."""
    return os.environ.get("WXMP_BROWSER_CHANNEL", "msedge").strip()


def headless() -> bool:
    # Headed by default: the console is picky about automation and a human can
    # see what the server is doing.
    return _flag("WXMP_HEADLESS", False)


def cdp_url() -> str:
    """Attach to an already-running Chrome instead of launching one."""
    return os.environ.get("WXMP_CDP_URL", "").strip()


def timeout_ms() -> int:
    return _int("WXMP_TIMEOUT_MS", 30000)


def login_timeout_s() -> int:
    return _int("WXMP_LOGIN_TIMEOUT", 180)


def slow_mo_ms() -> int:
    return _int("WXMP_SLOW_MO", 0)


def viewport() -> dict:
    return {"width": _int("WXMP_VIEWPORT_W", 1280),
            "height": _int("WXMP_VIEWPORT_H", 900)}


def device_scale() -> float:
    """Device pixel ratio of the controlled window.

    The console renders the login QR at roughly 122 CSS px, which is small when
    the PNG is all a human has to scan. Set WXMP_DEVICE_SCALE=2 to double the
    resolution of every screenshot.
    """
    raw = os.environ.get("WXMP_DEVICE_SCALE", "")
    try:
        value = float(raw) if raw else 1.0
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0


def settings() -> dict:
    return {
        "base_url": BASE_URL,
        "profile_dir": str(profile_dir()),
        "out_dir": str(out_dir()),
        "browser_channel": browser_channel() or "(playwright chromium)",
        "headless": headless(),
        "cdp_url": bool(cdp_url()),
        "timeout_ms": timeout_ms(),
        "login_timeout_s": login_timeout_s(),
        "device_scale": device_scale(),
        "viewport": viewport(),
        "python": sys.version.split()[0],
        "limits": {
            "tietu_max_images": TIETU_MAX_IMAGES,
            "tietu_desc_limit": TIETU_DESC_LIMIT,
            "tietu_title_limit": TIETU_TITLE_LIMIT,
            "article_title_limit": ARTICLE_TITLE_LIMIT,
            "article_digest_limit": ARTICLE_DIGEST_LIMIT,
            "article_author_limit": ARTICLE_AUTHOR_LIMIT,
            "content_max_chars": CONTENT_MAX_CHARS,
        },
    }


def url_home(token: str) -> str:
    return BASE_URL + PATH_HOME.format(token=token)


def url_login() -> str:
    return BASE_URL + PATH_LOGIN


def url_tietu_new(token: str) -> str:
    return BASE_URL + PATH_TIETU_NEW.format(token=token)


def url_article_new(token: str) -> str:
    return BASE_URL + PATH_ARTICLE_NEW.format(token=token)


def url_draft_edit(token: str, appmsgid, mtype: int = 77) -> str:
    return BASE_URL + PATH_DRAFT_EDIT.format(token=token, appmsgid=appmsgid,
                                             mtype=mtype)


def url_draft_list(token: str, kind: str = "tietu", count: int = 10) -> str:
    return BASE_URL + PATH_DRAFT_LIST.format(token=token, count=count,
                                             item_type=ITEM_TYPE.get(kind, 8))


def url_published(token: str, count: int = 20) -> str:
    return BASE_URL + PATH_PUBLISHED_LIST.format(token=token, count=count)