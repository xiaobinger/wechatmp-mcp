# -*- coding: utf-8 -*-
"""贴图 (image message) composer flow.

Everything in this module mirrors a hand-run session on the live console:

* ``/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77``
  ``&createType=8&token=…`` is the 贴图 editor. ``createType=8`` is mandatory —
  without it the URL opens the 图文 (article) composer instead.
* The editor holds two ``.ProseMirror[contenteditable="true"]`` nodes:
  index 0 is the title, index 1 is the description.
* The description counter reads ``<n>/1000``; the live editor measured
  799/1000 for a 987-character body, so the counter is not a 1:1 character
  count and is only used as a sanity check.
* Once an image is attached the placeholder disappears and the hint
  ``默认首图为封面`` appears — that is the success signal for the upload step.
* **Only one input works.** The editor holds two ``input[type=file]`` nodes:
  ``input[name="file"]`` (owned by the 图片库 picker) and the one inside
  ``div.weui-desktop-upload`` (the webuploader behind 本地上传). Handing the
  file to ``input[name="file"]`` does nothing — the counter stays empty and no
  request is made. The ``div.weui-desktop-upload`` input uploads for real
  (``filetransfer`` → ``modifyfile`` → ``operate_appmsg``, all 200) and the
  cover hint appears. Pasting an image into the page also uploads it, but only
  into 素材库 — it never attaches to the 贴图.
* The upload menu only exists after the add tile is clicked, so the flow is:
  click the tile, wait for ``a.pop-opr__button``, then set the files.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

from . import config, console, security
from .errors import PageError

LOG = logging.getLogger("wxmp.tietu")

EDITOR = ".ProseMirror[contenteditable='true']"
UPLOAD_HINT = "选择或拖拽图片"
UPLOAD_MENU = "a.pop-opr__button"
# The webuploader input behind 本地上传 — the only input the editor listens to.
UPLOADER_INPUT = 'div.weui-desktop-upload input[type="file"]'
LIBRARY_BUTTON = "从图片库选择"
LIBRARY_THUMB = ".weui-desktop-img-picker__img-thumb"
LIBRARY_CONFIRM = "button.weui-desktop-btn_primary"
COVER_HINT = "默认首图为封面"
SAVE_DRAFT = "保存为草稿"
PUBLISH = "发表"
PUBLISH_DIALOG = "div.weui-desktop-dialog:visible"

# 定时发表 controls inside the publish dialog.
SCHEDULE_SWITCH = "div.weui-desktop-switch__box"
SCHEDULE_INPUT = "input[placeholder='请选择时间']"
SCHEDULE_LABEL = "label.weui-desktop-form__label"
SCHEDULE_MIN_MINUTES = 1
SCHEDULE_MAX_MINUTES = 7 * 24 * 60

# Page text seen while a 发表 is in flight. 「该草稿正在发表，请勿重复操作」 is what
# the console shows after the submission is accepted; the item then lands in
# 发表记录 a couple of minutes later.
SUBMITTING_MARKERS = ("该草稿正在发表", "请勿重复操作", "正在发表", "发表中")
DONE_MARKERS = ("发表成功", "已发表成功", "发表完成", "已群发")

# 发表 on this account is gated by an admin scan: after the dialog is submitted a
# verification page appears and **the human must scan it with WeChat** before the
# message goes out. That was reported by the account owner on the live run of
# msgid 1000000021; the automation only ever saw 「该草稿正在发表」 afterwards, which
# is why an earlier revision wrongly concluded that no scan was involved.
SCAN_MARKERS = ("扫码", "扫一扫", "二维码", "管理员", "身份验证", "安全验证",
                "确认发表", "微信扫一扫")

SELECTED_RE = re.compile(r"已选择\s*(\d+)")
DESC_COUNT_RE = re.compile(r"(\d+)\s*/\s*1000\b")


# --------------------------------------------------------------------------
# small page helpers
# --------------------------------------------------------------------------
def _text(page) -> str:
    return console.body_text(page)


def has_cover(page) -> bool:
    return COVER_HINT in _text(page)


def desc_counter(page) -> int | None:
    m = DESC_COUNT_RE.search(_text(page))
    return int(m.group(1)) if m else None


def wait_for_cover(page, seconds: float = 30.0) -> bool:
    """Poll for the 默认首图为封面 hint, which only shows once an image is in."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if has_cover(page):
            return True
        page.wait_for_timeout(500)
    return False


def click_text(page, *labels: str, exact: bool = False) -> str | None:
    """Click the first visible element carrying one of the given labels."""
    for label in labels:
        loc = page.get_by_text(label, exact=exact)
        for i in range(min(loc.count(), 8)):
            item = loc.nth(i)
            try:
                if item.is_visible():
                    item.click(timeout=8000)
                    return label
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                LOG.debug("click %r/%s failed: %s", label, i, exc)
    return None


def click_button(page, *labels: str) -> str | None:
    """Click a visible <button> by its label."""
    for label in labels:
        loc = page.get_by_role("button", name=label, exact=True)
        for i in range(min(loc.count(), 6)):
            item = loc.nth(i)
            try:
                if item.is_visible():
                    item.click(timeout=8000)
                    return label
            except Exception:  # noqa: BLE001
                continue
    return click_text(page, *labels)


# --------------------------------------------------------------------------
# editor
# --------------------------------------------------------------------------
def open_new(page, token: str) -> str:
    """Open a brand-new 贴图 composer and wait for it to be editable."""
    page.goto(config.url_tietu_new(token), wait_until="domcontentloaded",
              timeout=config.timeout_ms())
    try:
        page.wait_for_selector(EDITOR, timeout=config.timeout_ms())
    except Exception as exc:  # noqa: BLE001
        raise PageError(
            "the 贴图 editor did not appear",
            {"url": security.mask_url(page.url),
             "login_markers": console.login_markers_present(page),
             "detail": str(exc).strip()},
        ) from exc
    page.wait_for_timeout(800)
    return page.url


def open_upload_menu(page) -> bool:
    """Click the add tile so the 本地上传 / 图片库 menu is created in the DOM."""
    if not click_text(page, UPLOAD_HINT):
        return False
    try:
        page.wait_for_selector(UPLOAD_MENU, timeout=15000)
        return True
    except Exception:  # noqa: BLE001
        return False


def attach_images(page, paths: list[str]) -> dict:
    """Attach local image files to the composer.

    Verified on the live editor: only ``div.weui-desktop-upload input[file]``
    uploads. ``input[name="file"]`` belongs to the 图片库 picker and is inert
    here — handing it a file leaves the composer empty and sends no request.
    The library picker stays as a documented fallback (pick a thumbnail, press
    确定), but it attaches whatever is already in 素材库, not these files.
    """
    detail: dict = {"requested": len(paths)}
    detail["menu_opened"] = open_upload_menu(page)
    inp = page.locator(UPLOADER_INPUT).first
    if not inp.count():
        raise PageError(
            "the 本地上传 file input is missing",
            {"hint": "the editor layout changed; open the composer and check",
             "menu_opened": detail["menu_opened"],
             "url": security.mask_url(page.url)},
        )
    try:
        inp.set_input_files(paths)
    except Exception as exc:  # noqa: BLE001
        raise PageError(
            "could not hand the files to the uploader",
            {"detail": f"{type(exc).__name__}: {exc}",
             "url": security.mask_url(page.url)},
        ) from exc
    detail["method"] = "local-upload"
    detail["cover_hint"] = wait_for_cover(page)
    if detail["cover_hint"]:
        return detail
    LOG.warning("the uploader input did not attach the images; "
                "trying the library picker")
    detail.update(pick_from_library(page, len(paths)))
    detail["method"] = "library"
    if not detail.get("cover_hint"):
        detail["warning"] = ("the uploader accepted the files but the cover "
                            "hint never appeared")
    return detail


def pick_from_library(page, count: int) -> dict:
    """Fallback: attach the newest ``count`` images already in 素材库."""
    link = page.locator(UPLOAD_MENU, has_text=LIBRARY_BUTTON).first
    if not link.count() and not open_upload_menu(page):
        raise PageError("could not open the upload menu",
                        {"url": security.mask_url(page.url)})
    page.locator(UPLOAD_MENU, has_text=LIBRARY_BUTTON).first.click(timeout=10000)
    try:
        page.wait_for_selector(LIBRARY_THUMB, timeout=15000)
    except Exception as exc:  # noqa: BLE001
        raise PageError("the image library is empty or did not open",
                        {"detail": str(exc).strip(),
                         "hint": "upload an image through the console once"}) from exc

    thumbs = page.locator(LIBRARY_THUMB)
    available = thumbs.count()
    picked = min(count, available)
    for i in range(picked):
        thumbs.nth(i).click()
        page.wait_for_timeout(200)
    page.wait_for_timeout(400)
    selected = SELECTED_RE.search(_text(page))
    confirm = page.locator(LIBRARY_CONFIRM, has_text="确定").first
    if not confirm.count():
        confirm = page.get_by_role("button", name="确定", exact=True).first
    try:
        confirm.click(timeout=8000)
    except Exception as exc:  # noqa: BLE001
        raise PageError("could not confirm the library selection",
                        {"detail": str(exc).strip()}) from exc
    page.wait_for_timeout(2000)
    return {
        "library_available": available,
        "library_picked": picked,
        "library_selected_label": selected.group(0) if selected else None,
        "library_note": ("images already in 素材库 were attached, newest first; "
                         "they may not be the files that were requested"),
        "cover_hint": wait_for_cover(page, 15),
    }


def set_field(page, index: int, text: str) -> None:
    """Replace the content of editor ``index`` (0 title, 1 description)."""
    fields = page.locator(EDITOR)
    if fields.count() <= index:
        raise PageError("the composer field is missing",
                        {"index": index, "found": fields.count()})
    field = fields.nth(index)
    field.click(timeout=8000)
    page.wait_for_timeout(150)
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            # insert_text emits no key events, so CJK text is never garbled and
            # never needs the OS clipboard (which broke on CF_HTML).
            page.keyboard.insert_text(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")
    page.wait_for_timeout(300)


def set_title(page, title: str) -> None:
    set_field(page, 0, title)


def set_description(page, desc: str) -> None:
    set_field(page, 1, desc)


# --------------------------------------------------------------------------
# save / publish
# --------------------------------------------------------------------------
def _scan_appmsgid(value) -> int | None:
    """Depth-first search for an ``appmsgid`` in a JSON payload."""
    if isinstance(value, dict):
        for key in ("appmsgid", "app_msg_id", "appMsgId"):
            v = value.get(key)
            if isinstance(v, (int, str)) and str(v).isdigit():
                return int(v)
        for v in value.values():
            found = _scan_appmsgid(v)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _scan_appmsgid(v)
            if found:
                return found
    return None


def _url_appmsgid(url: str | None) -> int | None:
    if not url:
        return None
    m = re.search(r"appmsgid=(\d+)", url)
    return int(m.group(1)) if m else None


def click_save_draft(page) -> str | None:
    """Press 保存为草稿 through every shape the console uses for it.

    It is a ``<button>`` in some layouts and ``span#js_submit``
    (``span.btn.btn_input.btn_primary``, with the label in a child
    ``span.send_wording``) in others, so a role lookup alone can miss it.
    """
    hit = click_button(page, SAVE_DRAFT)
    if hit:
        return hit
    for sel in ("#js_submit", "span.btn_input.btn_primary"):
        loc = page.locator(sel)
        for i in range(min(loc.count(), 4)):
            item = loc.nth(i)
            try:
                if (item.is_visible()
                        and SAVE_DRAFT in (item.inner_text() or "")):
                    item.click(timeout=8000)
                    return sel
            except Exception as exc:  # noqa: BLE001 - try the next shape
                LOG.debug("save %s/%s failed: %s", sel, i, exc)
    return None


def _visible_dialog_heads(page) -> list[str]:
    """First line of every visible modal — the usual reason a click is swallowed."""
    heads: list[str] = []
    try:
        dlgs = page.locator("div.weui-desktop-dialog:visible")
        for i in range(min(dlgs.count(), 3)):
            text = " ".join((dlgs.nth(i).inner_text() or "").split())
            if text:
                heads.append(text[:80])
    except Exception:  # noqa: BLE001
        pass
    return heads


def save_draft(page) -> dict:
    """Press 保存为草稿 and recover the new draft id when the console reports it."""
    payload = None
    try:
        with page.expect_response(
                lambda r: "operate_appmsg" in r.url or "appmsg" in r.url,
                timeout=20000) as info:
            clicked = click_save_draft(page)
            if not clicked:
                raise PageError(
                    "the 保存为草稿 button was not found",
                    {"url": security.mask_url(page.url),
                     "open_dialogs": _visible_dialog_heads(page)},
                )
        resp = info.value
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001 - some endpoints answer with HTML
            try:
                payload = {"text": resp.text()[:400]}
            except Exception:  # noqa: BLE001
                payload = None
    except PageError:
        raise
    except Exception as exc:  # noqa: BLE001 - timeout on the response watch
        LOG.warning("could not observe the save response: %s", exc)
        # The click may still have been registered; the URL is the next hint.
        payload = None

    page.wait_for_timeout(2500)
    appmsgid = _scan_appmsgid(payload) or _url_appmsgid(page.url)
    toast = ""
    for sel in (".weui-desktop-toast__content", ".weui-desktop-toast"):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                toast = (loc.inner_text() or "").strip()
                break
        except Exception:  # noqa: BLE001
            continue
    return {
        "appmsgid": appmsgid,
        "toast": toast,
        "url": security.mask_url(page.url),
        "appmsgid_source": ("response" if _scan_appmsgid(payload) else
                            "url" if appmsgid else "unknown"),
    }


def _click_publish_control(page) -> str | None:
    """Press the 贴图 composer's publish control and report which selector hit.

    ``span.publish_enable_button`` is a 草稿箱 card action, not this page's
    control: in the composer the real button is ``button.mass_send``, labelled
    by its inner ``span.send_wording`` (发表). It sits inside a ``span.btn``
    shell that only paints the rounded box — clicking the shell does nothing.
    """
    for sel in ("button.mass_send", "button:has(span.send_wording)"):
        loc = page.locator(sel)
        for i in range(min(loc.count(), 4)):
            item = loc.nth(i)
            try:
                if item.is_visible():
                    item.click(timeout=8000)
                    return sel
            except Exception as exc:  # noqa: BLE001 - try the next candidate
                LOG.debug("publish control %s/%s failed: %s", sel, i, exc)
    return click_button(page, PUBLISH)


def _confirm_publish_dialog(page, timeout_s: float = 20.0, prepare=None):
    """Wait for the publish dialog, let ``prepare`` touch it, press its submit.

    Measured: the dialog only renders a few seconds **after** the click —
    it was absent at +2s and present at +6s — so a 1.5s look can never find it.
    It is a ``div.weui-desktop-dialog`` reading
    ``发表贴图无需开启群发通知`` / ``定时发表``, and its affirmative button is
    itself labelled 发表 (primary), next to 取消. The footer button is tried
    first: the dialog body also holds the 定时发表 switch and time picker, and
    while that picker is open its ``<li>`` intercepts clicks on the footer.
    """
    deadline = time.time() + max(1.0, timeout_s)
    prepared = None
    while time.time() < deadline:
        try:
            dlg = page.locator(PUBLISH_DIALOG).first
            if dlg.count() and dlg.is_visible():
                prompt = (dlg.inner_text() or "").replace("\n", " ").strip()[:200]
                if prepare is not None and prepared is None:
                    prepared = prepare(page, dlg)
                for candidate in (dlg.locator("div.weui-desktop-dialog__ft button.weui-desktop-btn_primary"),
                                  dlg.locator("button.weui-desktop-btn_primary"),
                                  dlg.get_by_role("button", name=PUBLISH, exact=True)):
                    for i in range(min(candidate.count(), 4)):
                        btn = candidate.nth(i)
                        try:
                            if btn.is_visible():
                                label = (btn.inner_text() or "").strip() or PUBLISH
                                btn.click(timeout=8000)
                                return prompt, label, prepared
                        except Exception as exc:  # noqa: BLE001
                            LOG.debug("publish dialog button failed: %s", exc)
        except Exception as exc:  # noqa: BLE001 - page may be re-navigating
            LOG.debug("publish dialog probe failed: %s", exc)
        page.wait_for_timeout(500)
    return "", None, prepared


def _set_schedule(page, dlg, minutes: int) -> dict:
    """Turn on 定时发表 and write now+``minutes`` into the time picker.

    Measured structure: the row is ``div.publish_container`` with
    ``label.weui-desktop-form__label`` 定时发表 and a switch whose clickable part
    is ``div.weui-desktop-switch__box`` (the ``input.weui-desktop-switch__input``
    is parked off-screen at x=-9610). Enabling it renders
    ``input[placeholder='请选择时间']`` holding ``HH:MM`` for 今天. Typing into it
    leaves the hour/minute panel open, and that panel's ``<li>`` swallows clicks
    on the footer, so it is dismissed by clicking the 定时发表 label.
    """
    target = (dt.datetime.now() + dt.timedelta(minutes=int(minutes))).strftime("%H:%M")
    dlg.locator(SCHEDULE_SWITCH).first.click(timeout=8000)
    page.wait_for_timeout(1200)
    inp = dlg.locator(SCHEDULE_INPUT).first
    if not inp.count():
        raise PageError(
            "the 定时发表 time picker did not appear",
            {"minutes": int(minutes), "url": security.mask_url(page.url),
             "hint": "the switch may already be on, or this account may not be "
                     "allowed to schedule"},
        )
    inp.click(timeout=6000)
    inp.press("Control+a")
    inp.type(target, delay=60)
    page.wait_for_timeout(600)
    dlg.locator(SCHEDULE_LABEL).first.click(timeout=6000)
    page.wait_for_timeout(800)
    value = ""
    try:
        value = inp.input_value()
    except Exception:  # noqa: BLE001 - the picker may have re-rendered
        pass
    return {"requested": target, "value": value, "matches": value == target}


def _phase_probe(page) -> dict:
    """Which 发表-phase markers the page shows right now."""
    try:
        text = _text(page)
    except Exception as exc:  # noqa: BLE001 - the tab may close after a submit
        return {"closed": True, "text_error": str(exc).strip()[:120],
                "submitting": False, "done": False, "scan": []}
    return {
        "closed": False,
        "submitting": any(m in text for m in SUBMITTING_MARKERS),
        "done": any(m in text for m in DONE_MARKERS),
        "scan": [m for m in SCAN_MARKERS if m in text],
    }


def hold_for_scan(page, shot_path: str | None = None,
                  timeout_s: float = 120.0) -> dict:
    """Screenshot the admin 扫码 page and wait for the human to finish it.

    This step is not automatable and must not be faked: the account owner scans
    the QR with WeChat, only then does the console accept the 发表 and finish it
    in the background. Nothing is clicked here — the function only captures the
    QR for the human and reports whether the page moved on.
    """
    out: dict = {
        "needed": True,
        "screenshot": None,
        "cleared": False,
        "waited_s": 0.0,
        "hint": ("scan the QR in the browser window with WeChat; the 发表 only "
                 "starts once the scan is confirmed"),
    }
    if shot_path:
        try:
            out["screenshot"] = console.screenshot(page, shot_path)
        except Exception as exc:  # noqa: BLE001
            out["screenshot_error"] = str(exc).strip()[:160]
    started = time.time()
    deadline = started + max(1.0, float(timeout_s))
    while time.time() < deadline:
        probe = _phase_probe(page)
        if probe["closed"] or not probe["scan"]:
            out["cleared"] = True
            out["submitting"] = probe["submitting"]
            out["done"] = probe["done"]
            break
        try:
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001 - the human closed the window
            out["cleared"] = True
            break
    out["waited_s"] = round(time.time() - started, 1)
    return out


def _wait_for_phase(page, seconds: float) -> dict:
    """Poll the page until any 发表-phase marker shows up, or time runs out."""
    deadline = time.time() + max(0.5, float(seconds))
    probe = {"closed": False, "submitting": False, "done": False, "scan": []}
    while time.time() < deadline:
        probe = _phase_probe(page)
        if (probe["closed"] or probe["submitting"] or probe["done"]
                or probe["scan"]):
            return probe
        try:
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001 - the tab may be closing after a submit
            probe["closed"] = True
            return probe
    return probe


def publish(page, *, action: str = "publish", schedule_minutes: int = 10,
            scan_wait_s: float = 120.0, scan_watch_s: float = 25.0,
            settle_s: float = 8.0, shot_path: str | None = None) -> dict:
    """Press 发表 and submit the confirmation dialog. Irreversible.

    ``action``:

    * ``publish`` (default) — submit now.
    * ``schedule`` — turn on 定时发表, write now+``schedule_minutes``, submit.

    **发表 is gated by an admin scan on this account.** Measured on the live run
    of msgid 1000000021: the 发表 dialog submits, a 扫码 page appears, the account
    owner scans it with WeChat, and only then does the console start the publish
    (「该草稿正在发表，请勿重复操作」), finish it in the background a couple of
    minutes later and close the editor tab itself. An earlier revision concluded
    "no scan needed" because the automation only saw the 正在发表 text; that was
    wrong and is corrected here.

    Consequence: this call can only report what the page showed. The real proof
    is a new entry in 发表记录, so ``verified`` stays ``False`` here and the
    caller must re-read that list.
    """
    if action not in ("publish", "schedule"):
        raise PageError(
            "unknown publish action",
            {"action": action, "allowed": ["publish", "schedule"],
             "hint": "use publish to submit now, schedule for 定时发表"})
    if action == "schedule":
        minutes = int(schedule_minutes)
        if not SCHEDULE_MIN_MINUTES <= minutes <= SCHEDULE_MAX_MINUTES:
            raise PageError(
                "schedule_minutes is out of range",
                {"schedule_minutes": minutes,
                 "min": SCHEDULE_MIN_MINUTES, "max": SCHEDULE_MAX_MINUTES,
                 "note": "the console's 定时发表 picker only offers 今天, so a "
                         "value beyond the next few hours is not reliable"})

    clicked = _click_publish_control(page)
    if not clicked:
        raise PageError("the 发表 button was not found",
                        {"url": security.mask_url(page.url),
                         "hint": "open the draft in the composer first"})

    prepare = None
    if action == "schedule":
        prepare = lambda pg, dlg: _set_schedule(pg, dlg, schedule_minutes)  # noqa: E731

    prompt, confirmed, prepared = _confirm_publish_dialog(page, prepare=prepare)

    # Submitting navigates: page.evaluate can throw "Execution context was
    # destroyed", so the probe tolerates it and the text stays optional. The 扫码
    # page can also render later than the 正在发表 toast, hence the second window.
    probe = _wait_for_phase(page, settle_s)
    if not (probe["closed"] or probe["submitting"] or probe["done"]
            or probe["scan"]):
        probe = _wait_for_phase(page, scan_watch_s)

    result = {
        "clicked": clicked,
        "action": action,
        "dialog_prompt": prompt or None,
        "confirm_clicked": confirmed,
        "submitted": bool(confirmed),
        "submitting_marker": bool(probe.get("submitting")),
        "done_marker": bool(probe.get("done")),
        "url": security.mask_url(page.url),
    }
    if prepared is not None:
        result["schedule"] = prepared
    if probe.get("closed"):
        result["page_closed"] = True
    if probe.get("scan"):
        result["scan_markers"] = probe["scan"]
        result["scan"] = hold_for_scan(page, shot_path, scan_wait_s)
        result["needs_scan"] = True
    result["verified"] = False
    if action == "schedule":
        result["note"] = ("定时发表 was driven through the console UI (switch, "
                          "time picker, footer 发表). The submission is NOT "
                          "verified: 发表记录 showed no new queue entry for it. "
                          "Confirm nothing else is required (the scan step) "
                          "before relying on the schedule.")
    else:
        result["note"] = ("发表 needs the admin scan: a 扫码 page appears after "
                          "the dialog submits and the human must scan it with "
                          "WeChat. Success is only proven by a new 发表记录 entry "
                          "— this flag is therefore false, and the publish lands "
                          "asynchronously about 2 minutes after the scan.")
    return result


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def create(page, *, token: str, images: list[str], title: str,
           description: str, save: bool = True) -> dict:
    started = time.time()
    out: dict = {"ok": True}
    out["editor_url"] = security.mask_url(open_new(page, token))
    out["upload"] = attach_images(page, images)
    if not out["upload"].get("cover_hint"):
        raise PageError(
            "no image reached the composer",
            {"upload": out["upload"],
             "url": security.mask_url(page.url),
             "hint": "run the flow with a human watching; the console may have "
                     "shown a modal (unverified account, new-device check)"},
        )
    set_title(page, title)
    out["title_chars"] = len(title)
    if description:
        set_description(page, description)
        out["desc_chars_input"] = len(description)
        out["desc_counter"] = desc_counter(page)
        limit = config.TIETU_DESC_LIMIT
        if out["desc_counter"] and out["desc_counter"] > limit:
            out["desc_warning"] = (f"the live counter reports "
                                   f"{out['desc_counter']}/{limit}")
    out["cover_hint"] = has_cover(page)
    if save:
        out["draft"] = save_draft(page)
    out["elapsed_ms"] = int((time.time() - started) * 1000)
    out["url"] = security.mask_url(page.url)
    return out