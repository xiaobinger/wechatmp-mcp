# -*- coding: utf-8 -*-
"""草稿箱 operations: list, open, publish, delete.

Verified structure on the live console:

* The 草稿箱 is ``/cgi-bin/appmsg?type=77&action=list_card&token=…``. With
  ``action=list`` the same page renders 发表记录 instead, which is why that
  variant is not used.
* Every draft is a card: ``div.weui-desktop-card[data-appid="<id>"]`` — the
  draft id lives in ``data-appid``, **not** in an ``appmsgid=`` link. The title
  is ``.weui-desktop-publish__cover__title`` and the footer
  ``.weui-desktop-card__ft`` carries ``更新于 …``.
* The card's own title link is a **temporary preview** (``/s?__biz=…&tempkey=…``),
  not the editor. A saved draft is addressable directly at
  ``t=media/appmsg_edit&action=edit&type=77&appmsgid=<id>`` (that is the URL the
  console itself redirects to right after 保存为草稿), so ``open_draft`` tries
  that first and only falls back to the hover-only 编辑 card action.
* ``item_show_type=8`` selects the 贴图 tab of 草稿箱 and **is honoured** while
  that tab has drafts. When it is empty the console normalises the value to 0
  (文章); the tools therefore report both the requested and the landed value
  instead of pretending. Measured on the live account: with one 贴图 draft the
  URL keeps ``8`` and the card list holds exactly that draft.

The card actions live in a hover-only row of 20px icon buttons
(``.weui-desktop-card__action a.weui-desktop-icon-btn``) that carry **no text**;
the only way to tell them apart is the ``.weui-desktop-tooltip`` shown on hover.
Measured on the live card: index 0 = 删除 (trash can), index 2 = 编辑 — and the
tooltip node keeps the previous label for a moment, so a reading can come back
as ``删除|编辑``. Deletion then asks for confirmation in a **popover**, not a
modal dialog: ``确定删除？删除该内容不会删除已发表的内容`` with a primary 删除
and a default 取消 button. Both are handled below; every call that uses them is
gated behind ``confirm=true``.
"""
from __future__ import annotations

import logging
import re
import time

from . import config, console, security
from .errors import LoginRequired, PageError

LOG = logging.getLogger("wxmp.drafts")

EDITOR = ".ProseMirror[contenteditable='true']"
CARD = "div.weui-desktop-card[data-appid]"
CARD_TITLE = ".weui-desktop-publish__cover__title"
CARD_FOOT = ".weui-desktop-card__ft"
EDIT_LABEL = "编辑"
DELETE_LABEL = "删除"

# Where the console puts a confirmation prompt. The 删除 prompt is a popover
# anchored to the card icon; other actions use the modal dialog.
CONFIRM_HOSTS = ("div.weui-desktop-dialog:visible",
                 "div.weui-desktop-popover:visible")

_JS_ROWS = r"""
() => [...document.querySelectorAll('div.weui-desktop-card[data-appid]')].map(c => ({
  appid: c.dataset.appid,
  title: ((c.querySelector('.weui-desktop-publish__cover__title') || {}).innerText || '').trim().slice(0, 160),
  foot: ((c.querySelector('.weui-desktop-card__ft') || {}).innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120)
}))
"""


def _landed_type(page) -> int | None:
    m = re.search(r"item_show_type=(\d+)", page.url or "")
    return int(m.group(1)) if m else None


def open_list(page, token: str, kind: str = "tietu", count: int = 10) -> dict:
    """Open 草稿箱 and report which item_show_type the console actually kept."""
    requested = config.ITEM_TYPE.get(kind, 0)
    page.goto(config.url_draft_list(token, kind=kind, count=count),
              wait_until="domcontentloaded", timeout=config.timeout_ms())
    page.wait_for_timeout(2500)
    if console.login_markers_present(page):
        raise LoginRequired("the console dropped the session; log in again",
                            {"url": security.mask_url(page.url)})
    landed = _landed_type(page)
    info = {
        "url": security.mask_url(page.url),
        "item_show_type_requested": requested,
        "item_show_type_landed": landed,
    }
    if landed is not None and landed != requested:
        info["warning"] = (
            f"the console rewrote item_show_type {requested} -> {landed}, so this "
            f"view is not the {kind} list; 贴图 drafts are not addressable by URL "
            f"in this console version")
    return info


def list_rows(page) -> list[dict]:
    try:
        rows = page.evaluate(_JS_ROWS)
    except Exception as exc:  # noqa: BLE001
        raise PageError("could not read the draft list",
                        {"detail": str(exc).strip(),
                         "url": security.mask_url(page.url)}) from exc
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        foot = r.get("foot") or ""
        out.append({
            "appmsgid": int(r["appid"]) if str(r.get("appid", "")).isdigit() else r.get("appid"),
            "title": r.get("title") or "",
            "updated": foot,
            "state": _state_from_text(foot),
        })
    return out


def _state_from_text(text: str) -> str:
    for marker, label in (("已发表", "published"), ("发表中", "publishing"),
                          ("审核", "reviewing"), ("未发表", "draft"),
                          ("已删除", "deleted"), ("更新于", "draft")):
        if marker in text:
            return label
    return "unknown"


def _card(page, appmsgid):
    return page.locator(f'div.weui-desktop-card[data-appid="{int(appmsgid)}"]').first


def _visible_tooltip(page, card) -> str:
    """Read the tooltip the console shows while an icon is hovered."""
    try:
        return card.evaluate(r"""c => [...c.querySelectorAll('.weui-desktop-tooltip')]
            .filter(t => { const r = t.getBoundingClientRect();
                           return r.width > 0 && r.height > 0
                                  && getComputedStyle(t).visibility !== 'hidden'; })
            .map(t => (t.innerText || '').trim()).filter(Boolean).join('|')""") or ""
    except Exception:  # noqa: BLE001
        return ""


def _card_icons(card):
    """The hover-only icon buttons in a card's action area (20px each)."""
    return card.locator(".weui-desktop-card__action a.weui-desktop-icon-btn")


def _click_card_icon(page, card, label: str, fallback_index: int) -> dict:
    """Click the card icon whose hover tooltip carries ``label``.

    The action area has no text — it is a row of icon buttons, the first of
    which draws a trash can. The tooltip is the only way to tell them apart, so
    each icon is hovered and read before clicking; ``fallback_index`` is used
    when no tooltip matches.
    """
    icons = _card_icons(card)
    count = icons.count()
    tried: list[dict] = []
    exact: int | None = None
    loose: int | None = None
    for i in range(count):
        el = icons.nth(i)
        try:
            el.hover(timeout=5000)
            page.wait_for_timeout(450)
            tip = _visible_tooltip(page, card)
            tried.append({"index": i, "tooltip": tip})
            # The tooltip node keeps the previous text while the next icon is
            # hovered, so a reading can carry several labels ("删除|编辑").
            # An exact single-label hit is therefore preferred over a substring.
            if tip.strip() == label and exact is None:
                exact = i
            elif label in tip and loose is None:
                loose = i
        except Exception as exc:  # noqa: BLE001
            tried.append({"index": i, "error": str(exc)[:120]})
            continue
    pick = exact if exact is not None else loose
    if pick is not None:
        icons.nth(pick).click(timeout=8000)
        return {"index": pick, "tooltip": next((t.get("tooltip") for t in tried
                                                if t.get("index") == pick), None),
                "tried": tried, "exact": pick == exact}
    if count > fallback_index:
        icons.nth(fallback_index).click(timeout=8000)
        return {"index": fallback_index, "tooltip": None, "tried": tried,
                "fallback": True}
    raise PageError(
        f"no {label} control in the draft card action area",
        {"icons": count, "tried": tried, "url": security.mask_url(page.url),
         "hint": "the card markup may differ on this account; do it by hand"},
    )


def _prepare_card(page, appmsgid: int):
    card = _card(page, appmsgid)
    if not card.count():
        raise PageError(
            "the draft is not on the first 草稿箱 page",
            {"appmsgid": int(appmsgid),
             "visible_draft_ids": [r["appmsgid"] for r in list_rows(page)],
             "hint": "raise count, or open 草稿箱 manually"},
        )
    card.scroll_into_view_if_needed(timeout=8000)
    card.hover()
    page.wait_for_timeout(800)
    return card


def _confirm_dialog(page, labels: tuple[str, ...] = ("删除", "确定", "确认"),
                    timeout_ms: int = 8000) -> dict | None:
    """Click the affirmative button of the console confirm prompt.

    The 删除 confirmation is **not** a ``.weui-desktop-dialog`` modal: the
    console renders it as a ``div.weui-desktop-popover`` anchored to the card
    icon (z-index 500, measured 280x161) whose text reads
    ``确定删除？删除该内容不会删除已发表的内容``, with a primary ``删除`` and a
    default ``取消`` button. Looking only for a dialog is why the first live
    delete clicked the icon and then found nothing to confirm. Dialogs are still
    checked first-class because other console actions use them.
    """
    deadline = time.time() + max(0.5, timeout_ms / 1000)
    tried: list[dict] = []
    while True:
        for host_sel in CONFIRM_HOSTS:
            try:
                host = page.locator(host_sel).first
                if not host.count() or not host.is_visible():
                    continue
            except Exception as exc:  # noqa: BLE001 - page may be navigating
                tried.append({"host": host_sel, "error": str(exc)[:100]})
                continue
            try:
                prompt = (host.inner_text() or "").replace("\n", " ").strip()[:120]
            except Exception:  # noqa: BLE001
                prompt = ""
            for label in labels:
                btn = host.get_by_role("button", name=label, exact=True)
                for i in range(min(btn.count(), 4)):
                    item = btn.nth(i)
                    try:
                        if item.is_visible():
                            item.click(timeout=8000)
                            return {"clicked": label, "host": host_sel,
                                    "prompt": prompt}
                    except Exception as exc:  # noqa: BLE001
                        tried.append({"host": host_sel, "label": label,
                                      "error": str(exc)[:100]})
        if time.time() >= deadline:
            return {"clicked": None, "host": None, "tried": tried} if tried else None
        page.wait_for_timeout(400)


def open_draft(page, token: str, appmsgid: int, kind: str = "tietu"):
    """Open a draft in its composer. Returns the page holding the editor.

    The console rewrites a freshly saved 贴图 draft to
    ``t=media/appmsg_edit&action=edit&type=77&appmsgid=<id>``, so that URL is
    the direct way in. The 草稿箱 编辑 action is only the fallback, because it
    depends on hover-only markup.
    """
    page.goto(config.url_draft_edit(token, int(appmsgid), 77),
              wait_until="domcontentloaded", timeout=config.timeout_ms())
    try:
        page.wait_for_selector(EDITOR, timeout=config.timeout_ms())
        page.wait_for_timeout(800)
        return page
    except Exception:  # noqa: BLE001 - fall back to the list action
        LOG.warning("the direct editor URL did not render a composer; "
                    "going through 草稿箱")
    open_list(page, token, kind=kind)
    card = _prepare_card(page, appmsgid)
    target = page
    popup = None
    try:
        with page.expect_popup(timeout=10000) as info:
            _click_card_icon(page, card, EDIT_LABEL, fallback_index=1)
        popup = info.value
        target = popup
    except PageError:
        raise
    except Exception:  # noqa: BLE001 - some accounts open it in the same tab
        popup = None
    if popup is not None:
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
    try:
        target.wait_for_selector(EDITOR, timeout=config.timeout_ms())
    except Exception as exc:  # noqa: BLE001
        raise PageError(
            "the draft opened but no editable composer appeared",
            {"url": security.mask_url(target.url),
             "detail": str(exc).strip()},
        ) from exc
    target.wait_for_timeout(800)
    return target


def publish_draft(page, token: str, appmsgid: int, kind: str = "tietu", *,
                  action: str = "publish", schedule_minutes: int = 10,
                  wait_publish_s: float = 180.0,
                  shot_path: str | None = None) -> dict:
    """Open the draft and publish (or schedule) it. The caller confirmed already.

    ``verified`` is never taken from the composer page: 发表 needs an admin scan
    and lands in 发表记录 asynchronously, so the only honest proof is a new
    ``msgid`` there. The ids are sampled **before** the submit and the list is
    polled afterwards for ``wait_publish_s`` seconds (0 skips the wait).
    """
    from . import records, tietu
    target = open_draft(page, token, appmsgid, kind=kind)
    editor_url = target.url
    before_ids: set = set()
    before_error = None
    if wait_publish_s and action == "publish":
        try:
            before_ids = records.msgids(records.list_published(page, token)["published"])
        except Exception as exc:  # noqa: BLE001 - verification is best effort
            LOG.warning("could not sample 发表记录 before publishing: %s", exc)
            before_error = f"{type(exc).__name__}: {exc}".strip()[:200]
    result = tietu.publish(target, action=action,
                           schedule_minutes=schedule_minutes,
                           shot_path=shot_path)
    result["appmsgid"] = int(appmsgid)
    result["editor_url"] = security.mask_url(editor_url)
    result["kind"] = kind
    if before_error:
        result["before_sample_error"] = before_error
    if action == "publish" and wait_publish_s:
        if before_ids:
            record = records.wait_for_new(page, token, before_ids,
                                          timeout_s=wait_publish_s)
            result["publish_record"] = record
            result["verified"] = bool(record.get("verified"))
        else:
            result["verified"] = False
            result["publish_record"] = {
                "verified": False,
                "note": ("the 发表记录 list could not be sampled before the "
                         "submit, so a new entry cannot be told apart"),
            }
    else:
        result["verified"] = False
    result["note"] = (
        "发表 is two steps plus a human: the header 发表 control, the "
        "confirmation dialog (发表贴图无需开启群发通知 / 定时发表), then a 扫码 page "
        "that the admin must scan with WeChat. verified=true only when a new "
        "msgid appeared in 发表记录; the publish itself lands ~2 minutes after "
        "the scan and the editor tab closes by itself.")
    return result


def delete_draft(page, token: str, appmsgid: int, kind: str = "tietu") -> dict:
    """Delete a draft from 草稿箱. The caller must have confirmed already."""
    open_list(page, token, kind=kind)
    card = _prepare_card(page, appmsgid)
    clicked = _click_card_icon(page, card, DELETE_LABEL, fallback_index=0)
    page.wait_for_timeout(1200)
    confirmed = _confirm_dialog(page)
    page.wait_for_timeout(2500)
    rows = list_rows(page)
    remaining = [r["appmsgid"] for r in rows]
    return {
        "appmsgid": int(appmsgid),
        "icon": clicked,
        "confirm": confirmed,
        "still_listed": int(appmsgid) in remaining,
        "visible_draft_ids": remaining,
        "verified": int(appmsgid) not in remaining,
        "url": security.mask_url(page.url),
    }