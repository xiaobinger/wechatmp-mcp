# -*- coding: utf-8 -*-
"""发表记录 (published items) — the only place a publish can be *proven*.

The console answers ``/cgi-bin/appmsgpublish?sub=list&…`` with

    {"is_admin": true,
     "base_resp": {...},
     "publish_page": "<json string>"}

where ``publish_page`` is itself an escaped JSON string holding
``total_count`` / ``publish_count`` / ``masssend_count`` / ``featured_count`` /
``item_show_type_counts`` and ``publish_list``. Every list entry is only a
wrapper — ``{"publish_type": 101, "publish_info": "<escaped json>"}`` — and
``publish_info`` is where ``type``, ``msgid``, ``sent_info.time``,
``sent_status`` (total / succ / fail / progress), ``sent_result.msg_status`` and
``appmsg_info[0]`` (``appmsgid`` / ``title`` / ``content_url``) actually live.

Measured on the live account: ``total_count 21, publish_count 1,
masssend_count 20`` with the newest entry being msgid ``1000000021``,
``sent_status.succ == total == 3``, ``msg_status 2``,
``content_url https://mp.weixin.qq.com/s/XlYWJHofOQzAXZco1rnH6A``.

On the live account a 贴图 publish reached this list **about two minutes after**
the admin scan, with ``sent_status.succ == total`` and ``msg_status == 2``, while
the draft id disappeared from 草稿箱. That is why publishing is not declared
verified from the composer page: this endpoint is the evidence.

The read is plain ``fetch`` inside the console origin, so it rides on the same
session cookie; the token is only used to build the URL and is masked in every
reply.
"""
from __future__ import annotations

import json
import logging
import time

from . import config, security
from .errors import PageError

LOG = logging.getLogger("wxmp.records")

_FETCH_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  const text = await r.text();
  return {status: r.status, body: text};
}"""


def _parse(raw):
    """Tolerate both a nested object and an escaped JSON string."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def fetch_list(page, token: str, count: int = 20) -> dict:
    """Ask the console for the 发表记录 page and return the raw envelope."""
    url = config.url_published(token, count)
    try:
        out = page.evaluate(_FETCH_JS, url)
    except Exception as exc:  # noqa: BLE001 - the tab may be navigating
        raise PageError(
            "could not read 发表记录",
            {"detail": f"{type(exc).__name__}: {exc}".strip()[:200],
             "url": security.mask_url(page.url)},
        ) from exc
    status = (out or {}).get("status")
    body = (out or {}).get("body") or ""
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise PageError(
            "发表记录 did not answer with JSON",
            {"http_status": status, "snippet": body[:300],
             "hint": "the session probably expired mid-call",
             "url": security.mask_url(page.url)},
        ) from exc
    base = payload.get("base_resp") or {}
    if base.get("ret") not in (None, 0):
        raise PageError(
            "发表记录 returned an error",
            {"ret": base.get("ret"), "msg": base.get("err_msg"),
             "http_status": status},
        )
    return payload


def parse_rows(payload: dict) -> dict:
    """Normalise ``publish_page`` into counters plus a flat row list.

    A list entry is only a wrapper: ``{"publish_type": 101, "publish_info":
    "<escaped json>"}``. ``publish_info`` is where ``msgid``, ``sent_info``,
    ``sent_status``, ``sent_result`` and ``appmsg_info`` actually live, so it is
    unescaped first. Both shapes are accepted, because a different console build
    may nest them directly.
    """
    page = _parse(payload.get("publish_page")) or {}
    raw = _parse(page.get("publish_list")) or []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        info = _parse(item.get("publish_info")) if "publish_info" in item else None
        if not isinstance(info, dict):
            info = item
        infos = _parse(info.get("appmsg_info")) or []
        first = infos[0] if infos and isinstance(infos[0], dict) else {}
        sent_info = _parse(info.get("sent_info")) or {}
        status = _parse(info.get("sent_status")) or {}
        result = _parse(info.get("sent_result")) or {}
        ts = sent_info.get("time")
        rows.append({
            "msgid": info.get("msgid"),
            "appmsgid": first.get("appmsgid"),
            "title": (first.get("title") or "").strip(),
            "content_url": first.get("content_url") or None,
            "publish_type": item.get("publish_type"),
            "sent_at": _iso(ts),
            "sent_ts": ts,
            "succ": status.get("succ"),
            "total": status.get("total"),
            "fail": status.get("fail"),
            "progress": status.get("progress"),
            "msg_status": result.get("msg_status"),
        })
    counters = {
        "total_count": page.get("total_count"),
        "publish_count": page.get("publish_count"),
        "masssend_count": page.get("masssend_count"),
    }
    return {"counters": counters, "rows": rows}


def _iso(ts):
    if not isinstance(ts, (int, float)) or ts <= 0:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))


def list_published(page, token: str, count: int = 20) -> dict:
    payload = fetch_list(page, token, count)
    parsed = parse_rows(payload)
    return {
        "counters": parsed["counters"],
        "count": len(parsed["rows"]),
        "published": parsed["rows"],
        "source": "/cgi-bin/appmsgpublish?sub=list",
        "note": ("this is 发表记录, not 草稿箱; a fresh publish appears here a "
                 "couple of minutes after the admin scan"),
    }


def msgids(rows) -> set:
    return {str(r.get("msgid")) for r in rows if r.get("msgid") is not None}


def find_new(before: set, rows, title: str | None = None) -> list:
    """Rows whose msgid was not in ``before``; optionally only those by title.

    A row without a msgid is skipped: the list can carry placeholder wrappers
    whose ``publish_info`` did not parse, and those must never be mistaken for a
    fresh publish.
    """
    fresh = [r for r in rows
             if r.get("msgid") is not None and str(r.get("msgid")) not in before]
    if title:
        wanted = title.strip()
        exact = [r for r in fresh if (r.get("title") or "").strip() == wanted]
        if exact:
            return exact
    return fresh


def _revive(page, token: str):
    """A tab to read 发表记录 from, re-opening one if the editor closed itself.

    After a 发表 the console closes the composer tab, so the page the caller
    holds may already be gone. The browser context survives, so a fresh tab on
    the console home restores the same session cookie.
    """
    try:
        if not page.is_closed():
            return page
    except Exception:  # noqa: BLE001 - already detached
        pass
    try:
        ctx = page.context
        fresh = ctx.new_page()
        fresh.goto(config.url_home(token), wait_until="domcontentloaded",
                   timeout=config.timeout_ms())
        fresh.wait_for_timeout(800)
        return fresh
    except Exception as exc:  # noqa: BLE001 - report through the poll loop
        raise PageError("could not reopen a tab to read 发表记录",
                        {"detail": f"{type(exc).__name__}: {exc}".strip()[:200]}) from exc


def wait_for_new(page, token: str, before: set, *, title: str | None = None,
                 timeout_s: float = 240.0, poll_s: float = 15.0,
                 count: int = 20) -> dict:
    """Poll 发表记录 until a msgid appears that was absent from ``before``.

    The publish lands asynchronously (measured: ~2 minutes after the scan), so a
    single read right after the submit always looks like a failure.
    """
    started = time.time()
    deadline = started + max(1.0, float(timeout_s))
    attempts = 0
    last = None
    probe = page
    while True:
        attempts += 1
        try:
            probe = _revive(probe, token)
            payload = fetch_list(probe, token, count)
            parsed = parse_rows(payload)
            last = parsed
            fresh = find_new(before, parsed["rows"], title)
            if fresh:
                return {
                    "verified": True,
                    "attempts": attempts,
                    "waited_s": round(time.time() - started, 1),
                    "entry": fresh[0],
                    "new_msgids": [r.get("msgid") for r in fresh],
                    "counters": parsed["counters"],
                }
        except Exception as exc:  # noqa: BLE001 - keep polling, report at the end
            LOG.warning("发表记录 poll %s failed: %s", attempts, exc)
            last = {"error": f"{type(exc).__name__}: {exc}".strip()[:200]}
        if time.time() >= deadline:
            break
        try:
            probe.wait_for_timeout(int(max(1.0, poll_s) * 1000))
        except Exception:  # noqa: BLE001 - the human closed the window
            time.sleep(max(1.0, poll_s))
    return {
        "verified": False,
        "attempts": attempts,
        "waited_s": round(time.time() - started, 1),
        "entry": None,
        "counters": (last or {}).get("counters") if isinstance(last, dict) else None,
        "last_error": (last or {}).get("error") if isinstance(last, dict) else None,
        "note": ("no new 发表记录 entry showed up in time; the publish may still "
                 "be queued, or the admin scan was not completed"),
    }