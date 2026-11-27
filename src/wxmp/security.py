# -*- coding: utf-8 -*-
"""Safety policy: confirmation gates, image path checks, token masking."""
from __future__ import annotations

import os
import re

from .errors import ConfirmationRequired, ParamError
from . import config

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = int(os.environ.get("WXMP_MAX_IMAGE_BYTES", 10 * 1024 * 1024))

_TOKEN_RE = re.compile(r"[?&]token=(\d+)")


def mask(value: str | None) -> str:
    """Never echo a usable session token.

    A 9-digit console token must not be recoverable from a log line, so only
    the first digit and the last two digits survive: ``312355317`` -> ``3*****17``.
    """
    if not value:
        return ""
    s = str(value)
    if len(s) <= 3:
        return "*" * len(s)
    if len(s) <= 5:
        return s[:1] + "*" * (len(s) - 2) + s[-1:]
    return s[:1] + "*" * (len(s) - 3) + s[-2:]


def mask_url(url: str | None) -> str:
    """Mask every token= parameter in a console URL before it is reported."""
    if not url:
        return ""
    return re.sub(r"(token=)(\d+)", lambda m: m.group(1) + mask(m.group(2)), str(url))


def token_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _TOKEN_RE.search(str(url))
    if m:
        return m.group(1)
    m = re.search(r"(?:^|&)token=(\d+)", str(url))
    return m.group(1) if m else None


def require_confirm(confirm: bool, action: str, hint: str) -> None:
    """Gate an irreversible console action behind an explicit confirm=true."""
    if confirm is not True:
        raise ConfirmationRequired(
            f"{action} requires confirm=true",
            {"action": action, "hint": hint,
             "note": "nothing was changed; the draft is untouched"},
        )


def check_content(text: str) -> str:
    """Refuse a runaway body before anything is typed into the editor."""
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > config.CONTENT_MAX_CHARS:
        raise ParamError(
            "content is longer than the server accepts",
            {"max": config.CONTENT_MAX_CHARS, "got": len(text),
             "hint": "split it into several materials, or raise the guard in "
                     "config.CONTENT_MAX_CHARS"})
    return text


def check_description(text: str) -> str:
    """Clip the description to the editor's character counter."""
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > config.TIETU_DESC_LIMIT:
        text = text[: config.TIETU_DESC_LIMIT]
    return text


def check_title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ParamError("title must not be empty")
    if len(text) > config.TIETU_TITLE_LIMIT:
        raise ParamError("title is longer than the editor limit",
                         {"max": config.TIETU_TITLE_LIMIT, "got": len(text)})
    return text


def resolve_images(paths) -> list[str]:
    """Validate local image files before the browser touches them."""
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ParamError("images must be a non-empty array of local file paths")
    if len(paths) > config.TIETU_MAX_IMAGES:
        raise ParamError("too many images",
                         {"max": config.TIETU_MAX_IMAGES, "got": len(paths)})
    out: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise ParamError("image path must be a non-empty string",
                             {"got": repr(raw)})
        path = os.path.abspath(os.path.expanduser(raw.strip()))
        if not os.path.isfile(path):
            raise ParamError("image file does not exist", {"path": path})
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ParamError("unsupported image type",
                             {"path": path, "allowed": sorted(IMAGE_SUFFIXES)})
        size = os.path.getsize(path)
        if size == 0:
            raise ParamError("image file is empty", {"path": path})
        if size > MAX_IMAGE_BYTES:
            raise ParamError("image file is too large",
                             {"path": path, "max_bytes": MAX_IMAGE_BYTES,
                              "got_bytes": size})
        out.append(path)
    return out