# -*- coding: utf-8 -*-
"""贴图 tool: build an image message, then keep it, publish it or schedule it."""
from __future__ import annotations

import time

from .. import browser, config, console, constraints, records, security, tietu
from ..errors import ParamError
from ..registry import bilingual, param, tool

# The live editor's 默认首图为封面 hint is the only reliable "image attached"
# signal; the 素材库 picker's n/20 counter is not present in the composer.

ACTIONS = ("draft", "publish", "schedule")

_ACTION_HELP_EN = (
    "draft keeps it in 草稿箱; publish submits it now; schedule turns on "
    "定时发表 and submits for now+schedule_minutes. publish and schedule need "
    "confirm=true and a human: 发表 shows a 扫码 page that the admin must scan "
    "with WeChat.")
_ACTION_HELP_ZH = (
    "draft 留在草稿箱；publish 立即提交；schedule 打开定时发表，提交到 "
    "schedule_minutes 分钟之后。publish 和 schedule 需要 confirm=true，而且需要人："
    "发表时会出现扫码页，必须由管理员用微信扫。")


def _shot_path(name: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(config.out_dir() / f"{name}_{stamp}.png")


@tool(
    "mp_create_tietu",
    bilingual(
        "Create a 贴图 (image message) in the WeChat Official Account console: "
        "upload one or more local PNG/JPEG images, write the title and the "
        "description, save it as a DRAFT, and optionally publish or schedule it in "
        "the same call. action=draft (default) stops at the draft; action=publish "
        "submits it immediately; action=schedule submits it for "
        "now+schedule_minutes. Publishing is irreversible and publicly visible, so "
        "it needs confirm=true, and the console then shows a 扫码 page the human "
        "must scan with WeChat before the message goes out. verified=true only once "
        "a new entry appears in 发表记录. "
        + constraints.tietu_limits(),
        "在公众号后台创建一条贴图：上传 1–20 张本地 PNG/JPEG 图片、写入标题和描述、"
        "存成草稿，并可在同一次调用里直接发布或定时发布。action=draft（默认）停在"
        "草稿；action=publish 立即提交；action=schedule 提交到 schedule_minutes "
        "分钟之后。发布不可撤销且公开可见，需要 confirm=true；随后控制台会出现扫码页，"
        "必须由管理员用微信扫过，内容才会发出去。只有发表记录里出现新条目，"
        "verified 才会是 true。"
        + constraints.tietu_limits_zh(),
    ),
    {
        "images": {"type": "array", "minItems": 1,
                   "maxItems": constraints.IMAGE_COUNT,
                   "description": param(
                       f"required, 1-{constraints.IMAGE_COUNT} pictures: each "
                       f"must be {constraints.image_rule()}; the first one "
                       f"becomes the cover",
                       f"必填，1–{constraints.IMAGE_COUNT} 张：每张都要是"
                       + constraints.image_rule_zh()
                       + "；第一张作封面")},
        "title": {"type": "string", "minLength": 1,
                  "maxLength": constraints.TITLE_LIMIT,
                  "description": param(
                      f"required, 1-{constraints.TITLE_LIMIT} characters as the "
                      f"console counts them; empty or longer is rejected with "
                      f"-32602",
                      f"必填，1–{constraints.TITLE_LIMIT} 个字符（后台计数口径）；"
                      f"空或超长返回 -32602")},
        "description": {"type": "string", "default": "",
                        "description": param(
                            f"newlines become paragraphs. No maxLength: the code "
                            f"clips instead of refusing, so text longer than "
                            f"{constraints.DESC_LIMIT} characters is trimmed and "
                            f"the reply reports desc_clipped=true",
                            f"换行会分成段落。不设 maxLength：行为是截断而不是拒绝，"
                            f"超过 {constraints.DESC_LIMIT} 字会被裁掉，"
                            f"回包给 desc_clipped=true")},
        "action": {"type": "string", "enum": list(ACTIONS), "default": "draft",
                   "description": param(_ACTION_HELP_EN, _ACTION_HELP_ZH)},
        "schedule_minutes": {"type": "integer", "minimum": 1, "maximum": 10080,
                             "default": 10,
                             "description": param(
                                 "minutes from now for action=schedule; the time "
                                 "picker only offers today, so keep it small",
                                 "action=schedule 时表示从现在起多少分钟；"
                                 "控制台的时间选择器只提供「今天」，别设太大")},
        "confirm": {"type": "boolean", "default": False,
                    "description": param(
                        "must be true for action=publish or action=schedule",
                        "action=publish 或 action=schedule 时必须为 true")},
        "wait_publish_s": {"type": "integer", "minimum": 0, "maximum": 900,
                           "default": 180,
                           "description": param(
                               "how long to poll 发表记录 for the new msgid before "
                               "answering; 0 skips the poll and returns "
                               "verified=false",
                               "回答之前轮询发表记录等新 msgid 的秒数；"
                               "0 表示不轮询，直接返回 verified=false")},
        "screenshot": {"type": "boolean", "default": True,
                       "description": param(
                           "save a full-page PNG of the composer",
                           "把编辑器的整页 PNG 存下来")},
    },
    required=("images", "title"),
)
def mp_create_tietu(images, title, description: str = "", action: str = "draft",
                    schedule_minutes: int = 10, confirm: bool = False,
                    wait_publish_s: int = 180, screenshot: bool = True) -> dict:
    if action not in ACTIONS:
        raise ParamError("unknown action", {"action": action,
                                           "allowed": list(ACTIONS)})
    paths = security.resolve_images(images)
    title = security.check_title(title)
    desc = security.check_description(description or "")
    if action != "draft":
        security.require_confirm(
            confirm, f"action={action} on a 贴图",
            "publishing is public and cannot be undone; pass confirm=true only "
            "after the human approved this exact content",
        )

    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        result = tietu.create(page, token=token, images=paths, title=title,
                              description=desc, save=True)
        result["title"] = title
        result["desc_chars_input"] = len(desc)
        result["images_requested"] = len(paths)
        result["action"] = action
        if screenshot:
            result["screenshot"] = console.screenshot(page, _shot_path("tietu"))
        draft = result.get("draft") or {}
        result["appmsgid"] = draft.get("appmsgid")
        if action == "draft":
            result["verified"] = bool(result["appmsgid"])
            result["state"] = "draft" if result["appmsgid"] else "unknown"
            result["note"] = ("the draft id comes from the save response or the "
                              "editor URL; nothing was published")
        else:
            before: set = set()
            sample_error = None
            if wait_publish_s and action == "publish":
                try:
                    before = records.msgids(
                        records.list_published(page, token)["published"])
                except Exception as exc:  # noqa: BLE001 - verification is optional
                    sample_error = f"{type(exc).__name__}: {exc}".strip()[:200]
            result["publish"] = tietu.publish(
                page, action=action, schedule_minutes=int(schedule_minutes),
                shot_path=_shot_path("publish_scan"))
            if sample_error:
                result["before_sample_error"] = sample_error
            if action == "publish":
                if before:
                    record = records.wait_for_new(page, token, before,
                                                  timeout_s=wait_publish_s)
                    result["publish_record"] = record
                    result["verified"] = bool(record.get("verified"))
                else:
                    result["verified"] = False
                    result["publish_record"] = {
                        "verified": False,
                        "note": ("发表记录 could not be sampled before the "
                                 "submit, so a new entry cannot be told apart"),
                    }
                result["state"] = "published" if result["verified"] else "pending"
            else:
                result["state"] = "scheduled_unverified"
                result["verified"] = False
                result["warning"] = (
                    "定时发表 was driven through the UI but never confirmed: the "
                    "console showed no new 发表记录 entry for it, so treat the "
                    "schedule as unproven")
        if result.get("state") == "unknown":
            result["warning"] = (
                "the console did not report a draft id; open 草稿箱 and check "
                "whether the draft was saved before publishing anything")
        return result