# -*- coding: utf-8 -*-
"""图文 (article) composer flow.

Measured on the live console (account-level layout, 2026-11):

* The 图文 editor is the **same** endpoint as the 贴图 editor —
  ``/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77`` — just
  **without** the ``createType=8`` parameter. Adding it opens the 贴图 composer.
* Two ``.ProseMirror[contenteditable="true"]`` nodes carry the text: index 0 is
  the title (``data-placeholder="请在这里输入标题"``, counter ``0/64``) and index 1
  is the body (placeholder ``从这里开始写正文``, footer ``正文字数0``). The third
  ``[contenteditable]`` in the DOM is a hidden ``original_primary_tips_input`` and
  does not match the class, so the selector is unambiguous.
* 作者 is ``input#author`` (placeholder ``请输入作者``) and 摘要 is
  ``textarea#js_description`` (``name=digest``).
* **Cover.** The empty slot is ``span.btn-text.js_share_type_none_image``
  (``拖拽或选择封面``). Clicking it opens a menu of exactly four entries —
  从正文选择 / 从图片库选择 / 微信扫码上传 / 一键生成封面 — and there is **no**
  local-upload entry. A local cover therefore goes through 从图片库选择
  (``a.pop-opr__button.js_imagedialog``). Its dialog (``选择图片``) is a *named
  list*, not a thumbnail grid: entries are ``div.weui-desktop-img-picker__item``
  with the file name in ``strong.weui-desktop-img-picker__img-title``, the list is
  backed by 素材库, and 上传文件 (``div.js_upload_btn_container input[type=file]``)
  is how a local file gets in. Clicking the name selects the entry — the primary
  下一步 carries ``weui-desktop-btn_disabled`` until then — 下一步 opens 编辑封面
  (2.35:1 消息列表 / 1:1 转发卡片), and 确认 commits. The committed cover is a new
  ``div.js_cover_preview_new`` node whose picture is a CSS ``background-image``;
  the empty slot stays in the DOM, so page text cannot tell whether a cover is
  set (an earlier revision got that wrong and reported a good cover as missing).
  The same nodes appear twice in the DOM (a hidden template copy), so every
  locator has to be filtered with ``:visible`` — a bare ``.first`` resolves to
  the invisible node and the click times out.
* **Inline images.** The toolbar entry is the span 图片 inside
  ``.tpl_item.jsInsertIcon.img`` (28x18). Its dropdown is
  ``ul.tpl_dropdown_menu.js_img_dropdown_menu`` — a ``<ul>``, not a ``<div>``, so a
  tag-qualified selector silently never matches — and it lists 本地上传 /
  从图片库选择 / 微信扫码上传 / AI 配图 …; 本地上传 is
  ``.js_img_dropdown_menu input[type="file"]``, the only file input on the page.
  Handing it a file inserts the picture into the body (measured: ``.ProseMirror
  img`` went 0 -> 2, i.e. the editor adds its own wrapper/placeholder node too,
  so the count is a floor, not an exact tally). The input exists in the DOM even
  while the menu is closed, so the ready signal is the input becoming *visible*.
* 保存为草稿 is ``#js_submit`` (``span.btn.btn_input.btn_primary``) and 发表 is
  ``button.mass_send`` — the same publish control the 贴图 composer uses, which
  is why :func:`wxmp.tietu.publish` drives the article publish too.

What is **not** proven: the article publish dialog (its wording and whether it
adds a 群发/通知 step) was never submitted, and the cover crop step after the
library picks an image is only driven by "click the next visible primary
button". Every result therefore carries ``verified`` flags instead of promises.
"""
from __future__ import annotations

import logging
import os
import re
import time

from . import config, security, tietu
from .errors import PageError

LOG = logging.getLogger("wxmp.article")

EDITOR = ".ProseMirror[contenteditable='true']"
TITLE_PLACEHOLDER = "请在这里输入标题"
BODY_PLACEHOLDER = "从这里开始写正文"
AUTHOR_INPUT = "input#author"
DIGEST_INPUT = "textarea#js_description"

# 封面
COVER_EMPTY = "span.btn-text.js_share_type_none_image"
COVER_EMPTY_TEXT = "拖拽或选择封面"
COVER_MENU = "a.pop-opr__button"
COVER_LIBRARY = "a.pop-opr__button.js_imagedialog:visible"
LIBRARY_UPLOAD_INPUT = "div.js_upload_btn_container input[type=file]"
# The picker is a *named list*, not a thumbnail grid: every entry is
# div.weui-desktop-img-picker__item and the file name lives in
# strong.weui-desktop-img-picker__img-title. Clicking the name is what selects
# the entry — the primary 下一步 keeps the class weui-desktop-btn_disabled until
# an entry is selected, which is the ready signal used below.
LIBRARY_ITEM = ".weui-desktop-img-picker__item"
LIBRARY_ITEM_TITLE = ".weui-desktop-img-picker__img-title"
LIBRARY_CONFIRM = "button.weui-desktop-btn_primary"
LIBRARY_DISABLED = "weui-desktop-btn_disabled"
CROP_MARKERS = ("编辑封面", "2.35:1", "1:1")
# Dialogs that belong to the cover detour and must not outlive it. The console
# also keeps 未实名 / 未设置头像 notices in the DOM (hidden), so they are never
# matched here.
COVER_DIALOG_MARKERS = ("选择图片", "编辑封面", "上传文件")
DIALOG = "div.weui-desktop-dialog:visible"
# 确认 is the 编辑封面 step's own word (measured: 上一步 / 确认); 确定 belongs to the
# picker's hidden footer and 下一步 to its visible one, so 确认 comes first.
CONFIRM_LABELS = ("确认", "确定", "下一步", "完成", "使用")
CLOSE_BTN = "button.weui-desktop-dialog__close-btn"

# 正文插图
INSERT_TRIGGER = ".tpl_item.jsInsertIcon.img"
INSERT_INPUT = '.js_img_dropdown_menu input[type="file"]'

SAVE_DRAFT = "保存为草稿"
PUBLISH = "发表"

# A block is an image when the whole line is either markdown-ish
# ``![](/path/to.png)`` or the explicit ``[[img:/path/to.png]]`` token. Anything
# else is one paragraph. Paths are validated by security.resolve_images before
# the browser is touched.
IMG_MD_RE = re.compile(r"^!\[[^\]]*\]\(\s*(?P<path>.+?)\s*\)$")
IMG_TOKEN_RE = re.compile(r"^\[\[\s*img\s*:?\s*(?P<path>.+?)\s*\]\]$")

_JS_BODY_IMGS = r"""
() => {
  const fields = [...document.querySelectorAll(".ProseMirror[contenteditable='true']")];
  const body = fields[1];
  return body ? body.querySelectorAll('img').length : -1;
}
"""

_JS_PICK = r"""
() => {
  const items = [...document.querySelectorAll('.weui-desktop-img-picker__item')];
  const sel = items.filter(el => el.classList.contains('selected'));
  const next = [...document.querySelectorAll('button')]
      .filter(b => (b.innerText || '').trim() === '下一步')
      .filter(b => b.getBoundingClientRect().width > 0);
  return {
    items: items.length,
    selected: sel.length,
    titles: sel.map(el => ((el.querySelector('strong') || {}).innerText || '')
                          .trim().slice(0, 60)),
    next_disabled: next.length
      ? /btn_disabled/.test(next[0].className || '') : null,
  };
}
"""

_JS_COVER = r"""
() => {
  const read = el => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {bg: (cs.backgroundImage || '').slice(0, 200),
            imgs: el.querySelectorAll('img').length,
            w: Math.round(r.width), h: Math.round(r.height)};
  };
  const out = {wide: null, square: null, ok: false, present: false};
  const wide = document.querySelector('.js_cover_preview_new');
  const square = document.querySelector('.js_cover_preview_square');
  if (wide) out.wide = read(wide);
  if (square) out.square = read(square);
  out.present = !!(wide || square);
  // url("") is what a preview shows before its picture has loaded, so only a
  // non-empty http(s) url (or a real <img>) counts as a loaded cover.
  const filled = p => !!p && p.w > 0
    && ((p.bg && /url\("?https?:/.test(p.bg)) || p.imgs > 0);
  out.ok = filled(out.wide) || filled(out.square);
  return out;
}
"""


# --------------------------------------------------------------------------
# pure helpers (offline-testable)
# --------------------------------------------------------------------------
def split_blocks(text: str) -> list[dict]:
    """Turn the body text into an ordered list of text paragraphs and images."""
    blocks: list[dict] = []
    normalised = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw in normalised.split("\n"):
        line = raw.strip()
        if not line:
            continue
        match = IMG_MD_RE.match(line) or IMG_TOKEN_RE.match(line)
        if match:
            blocks.append({"type": "image", "path": match.group("path").strip()})
        else:
            blocks.append({"type": "text", "text": line})
    return blocks


def block_paths(blocks: list[dict]) -> list[str]:
    return [b["path"] for b in blocks if b.get("type") == "image"]


def check_author(text: str) -> str:
    text = (text or "").strip()
    if len(text) > config.ARTICLE_AUTHOR_LIMIT:
        text = text[: config.ARTICLE_AUTHOR_LIMIT]
    return text


def check_digest(text: str) -> tuple[str, bool]:
    """Clip 摘要 to the field length; returns (value, clipped)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    limit = config.ARTICLE_DIGEST_LIMIT
    return (text[:limit], len(text) > limit)


# --------------------------------------------------------------------------
# page helpers
# --------------------------------------------------------------------------
def _fields(page):
    loc = page.locator(EDITOR)
    count = loc.count()
    if count < 2:
        raise PageError(
            "the 图文 composer did not render its title and body fields",
            {"fields": count, "url": security.mask_url(page.url),
             "hint": "the console layout may have changed; open the editor by hand"},
        )
    return loc.nth(0), loc.nth(1)


def body_image_count(page) -> int:
    try:
        return int(page.evaluate(_JS_BODY_IMGS))
    except Exception:  # noqa: BLE001 - the tab may be re-rendering
        return -1


def cover_state(page) -> dict:
    """Whether the 封面 slot actually holds an image.

    The empty slot stays in the DOM — ``拖拽或选择封面`` is the label of the mask
    that sits over it — so the page text keeps saying "empty" even after a cover
    is committed. What the console does instead is render
    ``div.js_cover_preview_new`` (2.35:1) and ``.js_cover_preview_square`` (1:1)
    with the picture as a CSS ``background-image`` (no ``<img>`` child), and the
    node only exists once 确认 in the 编辑封面 step was accepted. That node is the
    signal used here, measured on the live editor.
    """
    try:
        return page.evaluate(_JS_COVER) or {"ok": False}
    except Exception:  # noqa: BLE001
        return {"ok": False}


def cover_is_empty(page) -> bool:
    return not bool(cover_state(page).get("ok"))


def selection_state(page) -> dict:
    """How many picker entries are ticked and whether 下一步 is enabled."""
    try:
        return page.evaluate(_JS_PICK) or {}
    except Exception:  # noqa: BLE001 - the dialog may be mid-render
        return {}


def ensure_picked(page, name: str, host=None, tries: int = 4) -> dict:
    """Keep the wanted picker entry selected — clicking an item *toggles* it.

    Measured: right after 上传文件 the new entry already carries
    ``weui-desktop-img-picker__item selected`` (and its ``image_dialog__checkbox``
    is ticked) while 下一步 is enabled. Clicking the file name again *deselects*
    it, so 下一步 goes ``weui-desktop-btn_disabled``, the click is refused, the
    picker never advances and the leftover modal then swallows the later
    保存为草稿 click. Hence: read the state, click only when needed, re-read.
    """
    host = host or page
    state = selection_state(page)
    out: dict = {"before": state, "clicks": 0,
                 "ok": bool(name and name in (state.get("titles") or []))}
    if out["ok"]:
        return out
    for _ in range(max(1, tries)):
        loc = (host.locator(LIBRARY_ITEM, has_text=name) if name
               else host.locator(LIBRARY_ITEM))
        if not loc.count():
            loc = host.locator(LIBRARY_ITEM)
        if not loc.count():
            out["note"] = "the 选择图片 list holds no entry"
            return out
        item = loc.first
        try:
            item.click(timeout=8000, force=True)
        except Exception as exc:  # noqa: BLE001 - a re-render can eat the click
            out.setdefault("click_errors", []).append(str(exc).strip()[:120])
        out["clicks"] += 1
        page.wait_for_timeout(700)
        state = selection_state(page)
        titles = state.get("titles") or []
        if (name and name in titles) or (not name and state.get("selected")):
            out["ok"] = True
            out["after"] = state
            return out
    out["after"] = selection_state(page)
    out["note"] = ("the entry could not be kept selected, so 下一步 stays disabled"
                   if out["after"].get("next_disabled")
                   else "the entry's selection state did not settle")
    return out


def open_new(page, token: str) -> str:
    """Open a brand-new 图文 composer and wait until the body is editable."""
    page.goto(config.url_article_new(token), wait_until="domcontentloaded",
              timeout=config.timeout_ms())
    try:
        page.wait_for_selector(EDITOR, timeout=config.timeout_ms())
    except Exception as exc:  # noqa: BLE001
        raise PageError(
            "the 图文 editor did not appear",
            {"url": security.mask_url(page.url), "detail": str(exc).strip()[:200]},
        ) from exc
    deadline = time.time() + 20
    seen = ""
    while time.time() < deadline:
        try:
            _title, body = _fields(page)
            seen = " ".join((body.inner_text() or "").split())[:60]
        except PageError:
            seen = ""
        if BODY_PLACEHOLDER in seen or seen:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(800)
    return page.url


def set_title(page, title: str) -> None:
    # The title is the same ProseMirror the 贴图 composer uses, so the shared
    # field writer applies (insert_text never garbles CJK and needs no clipboard).
    tietu.set_field(page, 0, title)


def clear_body(page) -> None:
    _title, body = _fields(page)
    body.click(timeout=8000)
    page.wait_for_timeout(150)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.wait_for_timeout(200)


def focus_body_end(page) -> None:
    """Put the caret at the end of the body before typing a paragraph.

    Inserting an image goes through the toolbar, which takes the focus out of the
    editor, and a plain click lands the caret wherever the pointer hit. Clicking
    and then pressing Ctrl+End makes the insertion point deterministic, so a
    paragraph that follows an image really is appended after it.
    """
    _title, body = _fields(page)
    body.click(timeout=8000)
    page.wait_for_timeout(120)
    page.keyboard.press("Control+End")
    page.wait_for_timeout(120)


def _wait_body_images(page, before: int, seconds: float) -> int:
    deadline = time.time() + max(1.0, seconds)
    last = before
    while time.time() < deadline:
        last = body_image_count(page)
        if last > before:
            return last
        page.wait_for_timeout(500)
    return last


def insert_local_image(page, path: str, wait_s: float = 45.0) -> dict:
    """Insert one local image into the body through 图片 → 本地上传."""
    before = body_image_count(page)
    trigger = page.locator(INSERT_TRIGGER).first
    if not trigger.count():
        raise PageError(
            "the 图片 toolbar entry is missing",
            {"selector": INSERT_TRIGGER, "url": security.mask_url(page.url)},
        )
    trigger.click(timeout=8000)
    try:
        page.wait_for_selector(INSERT_INPUT, state="visible", timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise PageError(
            "the 本地上传 input in the insert menu did not appear",
            {"selector": INSERT_INPUT, "detail": str(exc).strip()[:160],
             "url": security.mask_url(page.url)},
        ) from exc
    inp = page.locator(INSERT_INPUT).first
    inp.set_input_files(path)
    after = _wait_body_images(page, before, wait_s)
    return {"path": os.path.basename(path), "images_before": before,
            "images_after": after, "ok": after > before}


def _disabled(item) -> bool:
    """Is this control greyed out? Clicking it would just burn the timeout."""
    try:
        return LIBRARY_DISABLED in (item.get_attribute("class") or "")
    except Exception:  # noqa: BLE001
        return False


def _click_primary(host, labels: tuple[str, ...] = CONFIRM_LABELS) -> str | None:
    """Click the first enabled primary/affirmative button inside ``host``."""
    for label in labels:
        btns = host.get_by_role("button", name=label, exact=True)
        for i in range(min(btns.count(), 4)):
            item = btns.nth(i)
            if _disabled(item):
                continue
            try:
                if item.is_visible():
                    item.click(timeout=8000)
                    return label
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                LOG.debug("confirm %r/%s failed: %s", label, i, exc)
    primary = host.locator(LIBRARY_CONFIRM)
    for i in range(min(primary.count(), 4)):
        item = primary.nth(i)
        if _disabled(item):
            continue
        try:
            if item.is_visible():
                label = (item.inner_text() or "").strip() or "primary"
                item.click(timeout=8000)
                return label
        except Exception as exc:  # noqa: BLE001
            LOG.debug("primary button %s failed: %s", i, exc)
    return None


def _primary_disabled(host) -> bool | None:
    """Is the dialog's primary button still disabled (i.e. nothing selected)?"""
    try:
        btn = host.locator(LIBRARY_CONFIRM).first
        if not btn.count():
            return None
        return LIBRARY_DISABLED in (btn.get_attribute("class") or "")
    except Exception:  # noqa: BLE001
        return None


def _wait_cover(page, seconds: float = 25.0) -> dict:
    deadline = time.time() + max(1.0, seconds)
    state: dict = {"ok": False}
    while time.time() < deadline:
        state = cover_state(page)
        if state.get("ok"):
            return state
        page.wait_for_timeout(600)
    return state


def _wait_crop_dialog(page, seconds: float = 20.0):
    """Wait for the 编辑封面 step (identified by its text), not just any dialog.

    The picker dialog stays on screen for a moment after 下一步, so "a dialog is
    visible" is the wrong test — clicking the primary of the *picker* again is a
    no-op and the crop was silently skipped that way once.
    """
    deadline = time.time() + max(1.0, seconds)
    while time.time() < deadline:
        try:
            dlgs = page.locator(DIALOG)
            for i in range(min(dlgs.count(), 3)):
                cand = dlgs.nth(i)
                if not cand.is_visible():
                    continue
                text = " ".join((cand.inner_text() or "").split())
                if any(marker in text for marker in CROP_MARKERS):
                    return cand, text
        except Exception:  # noqa: BLE001 - re-rendering between probes
            pass
        page.wait_for_timeout(500)
    return None, ""


def read_titles(page) -> dict:
    """Read the title back out of whichever composer is open."""
    try:
        _title, body = _fields(page)
    except PageError:
        return {"ok": False}
    try:
        title = " ".join((_title.inner_text() or "").split())
        body_text = " ".join((body.inner_text() or "").split())
    except Exception:  # noqa: BLE001 - the tab may be re-rendering
        return {"ok": False}
    return {"ok": True, "title": title[:120], "title_chars": len(title),
            "body_chars": len(body_text), "body_images": body_image_count(page)}


def reopen_draft(page, token: str, appmsgid, timeout_s: float = 25.0) -> dict:
    """Reopen a saved draft and read its 标题 and 封面 back.

    In the composer the preview node is 0x0 with ``url("")`` until the console has
    committed the cropped picture, so the composer alone cannot prove a cover —
    measured twice on a good save. The saved draft renders it properly
    (235x100 with an ``mmbiz.qpic.cn`` background), which makes the reopened
    draft the only honest check; the title is read in the same pass because the
    navigation is already paid for.
    """
    out: dict = {"ok": False, "appmsgid": appmsgid}
    try:
        page.goto(config.url_draft_edit(token, appmsgid, 77),
                  wait_until="domcontentloaded", timeout=config.timeout_ms())
        page.wait_for_selector(EDITOR, timeout=config.timeout_ms())
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"could not reopen the draft: {exc}".strip()[:160]
        return out
    out["title"] = read_titles(page)
    out["cover"] = _wait_cover(page, timeout_s)
    out["ok"] = bool(out["cover"].get("ok"))
    return out


def cover_from_draft(page, token: str, appmsgid, timeout_s: float = 25.0) -> dict:
    """Cover-only view of :func:`reopen_draft` (kept for callers that want just it)."""
    return reopen_draft(page, token, appmsgid, timeout_s)["cover"]


def set_cover(page, path: str, wait_s: float = 45.0) -> dict:
    """Set the 封面 from a local file.

    Measured path: 封面 slot → 从图片库选择 → the picker's 上传文件 input takes
    the file → the entry appears under its file name → clicking that name
    selects it (the primary 下一步 loses ``weui-desktop-btn_disabled``) → 下一步 →
    the 编辑封面 step (2.35:1 消息列表 / 1:1 转发卡片) → 确认 → the cover preview
    node appears. The console offers no local cover upload, so this detours
    through 素材库 and reports every step that did or did not happen.
    """
    name = os.path.basename(path)
    out: dict = {"path": name, "ok": False, "steps": []}
    slot = page.locator(COVER_EMPTY).first
    if not slot.count():
        state = cover_state(page)
        out["error"] = "the empty 封面 slot was not found"
        out["cover_state"] = state
        out["cover_already_set"] = bool(state.get("ok"))
        out["ok"] = bool(state.get("ok"))
        return out
    slot.click(timeout=8000)
    out["steps"].append("open-menu")
    try:
        page.wait_for_selector(COVER_LIBRARY, timeout=20000)
    except Exception:  # noqa: BLE001 - the lazily rendered menu swallows a click
        try:
            slot.click(timeout=8000)
            page.wait_for_selector(COVER_LIBRARY, timeout=15000)
        except Exception:  # noqa: BLE001
            try:
                out["menu"] = [t.strip() for t in
                               page.locator(COVER_MENU).all_inner_texts()]
            except Exception:  # noqa: BLE001
                out["menu"] = []
            out["error"] = "the 封面 menu did not offer 从图片库选择"
            return out
    page.locator(COVER_LIBRARY).first.click(timeout=8000)
    out["steps"].append("open-library")
    dlg = page.locator(DIALOG).first
    try:
        dlg.wait_for(state="visible", timeout=20000)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"the 选择图片 dialog did not open: {exc}".strip()[:200]
        return out
    out["dialog"] = " ".join((dlg.inner_text() or "").split())[:160]
    inp = dlg.locator(LIBRARY_UPLOAD_INPUT).first
    if not inp.count():
        inp = page.locator(LIBRARY_UPLOAD_INPUT).first
    if not inp.count():
        out["error"] = "the 上传文件 input of the picker was not found"
        return out
    inp.set_input_files(path)
    out["steps"].append("upload")
    deadline = time.time() + max(5.0, wait_s)
    listed = False
    while time.time() < deadline:
        try:
            if name in (dlg.inner_text() or ""):
                listed = True
                break
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(700)
    out["listed_by_name"] = listed
    out["primary_disabled_before_pick"] = _primary_disabled(dlg)

    if not dlg.locator(LIBRARY_ITEM).count():
        out["error"] = "the 选择图片 list holds no entry"
        return out
    # The upload usually leaves the new entry already ticked; clicking it again
    # would untick it and freeze 下一步 (see ensure_picked).
    pick = ensure_picked(page, name, host=dlg)
    out["pick"] = pick
    if pick.get("ok"):
        out["steps"].append("select-item")
    else:
        out["warning_pick"] = pick.get("note")
    out["primary_disabled_after_pick"] = _primary_disabled(dlg)
    out["next"] = _click_primary(dlg)
    out["steps"].append("next")
    crop, crop_text = _wait_crop_dialog(page, 20)
    if crop is None and out["next"]:
        # The picker's own render can swallow the first 下一步; retry once, but
        # only while the picker is still the top dialog (never double-click a
        # crop step, that is how 确认 used to be skipped).
        page.wait_for_timeout(1200)
        still_picker = "上传文件" in "".join(
            " ".join((d.inner_text() or "").split())
            for d in page.locator(DIALOG).all())
        if still_picker:
            out["next_retry"] = _click_primary(dlg)
            crop, crop_text = _wait_crop_dialog(page, 20)
    if crop is not None:
        out["crop_prompt"] = crop_text[:160]
        out["crop_confirm"] = _wait_enabled_confirm(page, 25)
        out["steps"].append("crop-confirm")
        if not out["crop_confirm"]:
            out["warning_crop"] = ("the 编辑封面 step offered no enabled confirm "
                                   "within 25 s; the cover may not be committed")
    else:
        out["crop_prompt"] = None
        out["warning_crop"] = ("the 编辑封面 step never showed up after 下一步; "
                               "the cover may not be committed")

    state = _wait_cover(page, 20)
    out["cover_state"] = state
    out["ok"] = bool(state.get("ok"))
    if not out["ok"]:
        out["warning"] = ("the preview had not painted inside this call; the "
                          "saved draft is re-checked when the material is saved")
    return out


def _wait_enabled_confirm(page, seconds: float = 25.0) -> str | None:
    """Click the 编辑封面 confirm once it stops being greyed out.

    Measured: right after 下一步 the crop dialog exists but its 确认 still carries
    ``weui-desktop-btn_disabled`` while the picture is being cropped server-side;
    a click at that moment is refused and, if the dialog is then closed, the
    draft is saved without a cover (live run 100000245 lost its cover that way).
    """
    deadline = time.time() + max(1.0, seconds)
    while time.time() < deadline:
        for i in range(min(page.locator(DIALOG).count(), 4)):
            dlg = page.locator(DIALOG).nth(i)
            try:
                if not dlg.is_visible():
                    continue
                text = " ".join((dlg.inner_text() or "").split())
                if not any(m in text for m in CROP_MARKERS):
                    continue
            except Exception:  # noqa: BLE001 - re-rendering
                continue
            label = _click_primary(dlg)
            if label:
                return label
        page.wait_for_timeout(700)
    return None


def close_dialogs(page, markers: tuple[str, ...] = (), rounds: int = 4) -> list[str]:
    """Close leftover *cover* modals so the next click is not intercepted.

    A picker that did not advance stays on top of the composer; Playwright then
    reports the 保存为草稿 click as "not found" because the button never receives
    the pointer, which is exactly how a live run failed once. Only dialogs whose
    text carries one of ``markers`` are touched, so an unrelated console notice
    (未实名 / 未设置头像, which sit in the DOM) is left alone. Returns what was
    clicked, so the reply can say a modal had to be dismissed.
    """
    markers = markers or COVER_DIALOG_MARKERS
    closed: list[str] = []
    for _ in range(max(1, rounds)):
        try:
            dlgs = page.locator(DIALOG)
            top = None
            for i in range(min(dlgs.count(), 4)):
                cand = dlgs.nth(i)
                if not cand.is_visible():
                    continue
                text = " ".join((cand.inner_text() or "").split())
                if any(m in text for m in markers):
                    top = cand
                    break
            if top is None:
                return closed
            # 1) the dialog's own X, which every weui dialog carries
            did = False
            try:
                x = top.locator(CLOSE_BTN)
                for i in range(min(x.count(), 3)):
                    if x.nth(i).is_visible():
                        x.nth(i).click(timeout=5000)
                        closed.append("x")
                        did = True
                        break
            except Exception:  # noqa: BLE001 - fall through to the text buttons
                pass
            if did:
                page.wait_for_timeout(600)
                continue
            # 2) 取消 / 关闭, and 上一步 as the last resort (编辑封面 → picker)
            for label in ("取消", "关闭", "上一步"):
                btns = top.get_by_role("button", name=label, exact=True)
                hit = False
                for i in range(min(btns.count(), 4)):
                    item = btns.nth(i)
                    if item.is_visible():
                        item.click(timeout=5000)
                        closed.append(label)
                        hit = True
                        break
                if hit:
                    break
            page.wait_for_timeout(600)
        except Exception as exc:  # noqa: BLE001 - closing is best effort
            LOG.debug("close_dialogs: %s", exc)
            return closed
    return closed


def set_author(page, author: str) -> dict:
    loc = page.locator(AUTHOR_INPUT).first
    if not loc.count():
        return {"ok": False, "error": "the 作者 input was not found"}
    loc.fill(author)
    page.wait_for_timeout(200)
    return {"ok": True, "chars": len(author)}


def set_digest(page, digest: str) -> dict:
    value, clipped = check_digest(digest)
    loc = page.locator(DIGEST_INPUT).first
    if not loc.count():
        return {"ok": False, "error": "the 摘要 textarea was not found"}
    loc.fill(value)
    page.wait_for_timeout(200)
    return {"ok": True, "chars": len(value), "clipped": clipped,
            "requested_chars": len(digest or "")}


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def create(page, *, token: str, title: str, body: str = "",
           cover: str | None = None, images: tuple[str, ...] | list[str] = (),
           author: str = "", digest: str = "", save: bool = True) -> dict:
    """Fill the 图文 composer, then keep it as a draft when ``save`` is set."""
    started = time.time()
    out: dict = {"ok": True}
    out["editor_url"] = security.mask_url(open_new(page, token))
    blocks = split_blocks(body)
    out["blocks"] = {
        name: sum(1 for b in blocks if b["type"] == name)
        for name in ("text", "image")
    }
    set_title(page, title)
    out["title_chars"] = len(title)

    clear_body(page)
    typed = {"text": 0, "image": 0, "failed_images": []}
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            focus_body_end(page)
            page.keyboard.insert_text(block["text"])
            typed["text"] += 1
        else:
            res = insert_local_image(page, block["path"])
            if res.get("ok"):
                typed["image"] += 1
            else:
                typed["failed_images"].append(res)
        if i < len(blocks) - 1:
            page.keyboard.press("Enter")
            page.wait_for_timeout(120)
    page.wait_for_timeout(400)
    out["body"] = typed

    extra = []
    for path in images:
        extra.append(insert_local_image(page, path))
    if extra:
        out["extra_images"] = extra
    out["body_images"] = body_image_count(page)

    author = check_author(author)
    if author:
        out["author"] = set_author(page, author)
    if digest:
        out["digest"] = set_digest(page, digest)
    if cover:
        out["cover"] = set_cover(page, cover)
    out["cover_empty"] = cover_is_empty(page)
    if save:
        out["closed_dialogs"] = close_dialogs(page)
        draft = tietu.save_draft(page)
        out["draft"] = draft
        appmsgid = draft.get("appmsgid")
        if cover:
            # The composer's preview may still be unpainted at submit time, so the
            # only hard evidence is the saved draft itself: reopen it and read the
            # cover back. composer_ok is reported next to it, never instead of it.
            out["cover"]["composer_ok"] = bool(out["cover"].get("ok"))
            if appmsgid:
                recheck = reopen_draft(page, token, appmsgid)
                out["cover"]["recheck"] = {
                    "ok": bool(recheck.get("ok")),
                    "title": (recheck.get("title") or {}).get("title"),
                    "wide": (recheck.get("cover") or {}).get("wide"),
                    "error": recheck.get("error"),
                }
                out["cover"]["verified"] = bool(recheck.get("ok"))
                if not recheck.get("ok"):
                    out["cover"]["warning"] = (
                        "the draft was saved but the reopened draft shows no 封面 "
                        "picture; the console will not publish it as it stands")
            else:
                out["cover"]["verified"] = False
                out["cover"]["warning"] = (
                    "no draft id was reported, so the 封面 could not be re-checked")
    out["elapsed_ms"] = int((time.time() - started) * 1000)
    out["url"] = security.mask_url(page.url)
    return out