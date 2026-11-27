# -*- coding: utf-8 -*-
"""草稿箱 tools: list, publish, delete. All state changes need confirm=true."""
from __future__ import annotations

import time

from .. import browser, config, console, constraints, drafts, security
from ..registry import bilingual, param, tool


def _shot_path(name: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(config.out_dir() / f"{name}_{stamp}.png")


@tool(
    "mp_list_drafts",
    bilingual(
        "List the drafts in 草稿箱. Returns draft ids (from each card's "
        "data-appid), titles, the 更新于 footer and a state hint. "
        "item_show_type=8 selects the 贴图 tab and is honoured while that tab "
        "holds drafts; when it is empty the console normalises the value to 0 "
        "(文章), so both the requested and the landed value are reported. The ids "
        "feed mp_publish_draft and mp_delete_draft. Limits: count is 1-20 "
        "(default 10) and only the first page is read, so a busy 草稿箱 needs "
        "further calls with a smaller count; ids are integers and must be passed "
        "as such, never as a title.",
        "列出草稿箱里的草稿。返回草稿 id（取自每张卡片的 data-appid）、标题、"
        "「更新于」页脚和一个状态提示。item_show_type=8 选贴图标签页，只要该标签页"
        "有草稿就生效；该标签页为空时控制台会把值规范成 0（文章），所以请求值和实际"
        "落地的值都会报出来。这些 id 供 mp_publish_draft 和 mp_delete_draft 使用。"
        "限制：count 取值 1–20（默认 10），且只读第一页，草稿多时要再调一次并"
        "换小一点的 count；id 是整数，必须按整数传，不能传标题。",
    ),
    {
        "kind": {"type": "string", "enum": ["tietu", "article"], "default": "tietu",
                 "description": param(
                     "tietu asks for item_show_type=8, article for 0; the console "
                     "may normalise both to 0, and the reply reports both values",
                     "tietu 请求 item_show_type=8，article 请求 0；"
                     "控制台可能把两者都规范成 0，回包里两个值都会报")},
        "count": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10,
                  "description": param(
                      "how many cards to request from the console, 1-20; the "
                      "console renders one page, so this is not a cursor",
                      "向控制台请求多少张卡片，取值 1–20；控制台只渲染一页，"
                      "所以它不是翻页游标")},
    },
)
def mp_list_drafts(kind: str = "tietu", count: int = 10) -> dict:
    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        info = drafts.open_list(page, token, kind=kind, count=count)
        rows = drafts.list_rows(page)
        result = {
            "ok": True,
            "kind_requested": kind,
            "count": len(rows),
            "drafts": rows,
            **info,
            "note": ("only the first page is read; 更新于 is parsed from the card "
                     "footer, so treat the state as a hint"),
        }
        return result


@tool(
    "mp_publish_draft",
    bilingual(
        "Publish or schedule an existing draft. IRREVERSIBLE and publicly "
        "visible: requires confirm=true, and the human must have approved this "
        "exact draft id. Opens the draft in the composer, presses 发表, waits for "
        "the confirmation dialog (发表贴图无需开启群发通知 / 定时发表) and presses "
        "its 发表 button. action=publish submits now, action=schedule turns on "
        "定时发表 and submits for now+schedule_minutes. After submitting, the "
        "console shows a 扫码 page that the admin must scan with WeChat; the item "
        "then lands in 发表记录 about two minutes later. verified=true only when a "
        "NEW msgid appears in that list, so wait_publish_s controls how long the "
        "call polls for it. " + constraints.draft_limits(),
        "发布或定时发布一条已有草稿。不可撤销且公开可见：需要 confirm=true，"
        "并且必须由人确认过这个具体的 draft id。它会打开草稿编辑器、点发表、"
        "等确认弹窗（发表贴图无需开启群发通知 / 定时发表）再点弹窗里的发表按钮。"
        "action=publish 立即提交；action=schedule 打开定时发表，提交到 "
        "schedule_minutes 分钟之后。提交后控制台会出现扫码页，必须由管理员用微信扫，"
        "约 2 分钟后内容才落到发表记录。只有发表记录里出现「新」msgid 时 "
        "verified=true，wait_publish_s 控制轮询多久。" + constraints.draft_limits_zh(),
    ),
    {
        "appmsgid": {"type": "integer", "minimum": 1,
                     "description": param(
                         "required, integer draft id from mp_list_drafts / "
                         "mp_publish_material (for example 100000250), not the "
                         "title and not a string",
                         "必填，整数草稿 id，来自 mp_list_drafts / "
                         "mp_publish_material（例如 100000250），不是标题、"
                         "不要传字符串")},
        "confirm": {"type": "boolean", "default": False,
                    "description": param(
                        "must be true, otherwise the call is refused with -32602 "
                        "before the browser opens; publishing cannot be undone",
                        "必须为 true，否则在打开浏览器之前就返回 -32602；"
                        "发表不可撤销")},
        "kind": {"type": "string", "enum": ["tietu", "article"], "default": "tietu",
                 "description": param(
                     "which console tab the draft is opened in; pass the same kind "
                     "mp_list_drafts reported",
                     "草稿在哪个后台标签页打开；传 mp_list_drafts 报出来的那个 "
                     "kind")},
        "action": {"type": "string", "enum": ["publish", "schedule"],
                   "default": "publish",
                   "description": param(
                       "publish submits now; schedule uses 定时发表",
                       "publish 立即提交；schedule 走定时发表")},
        "schedule_minutes": {"type": "integer", "minimum": 1, "maximum": 10080,
                             "default": 10,
                             "description": param(
                                 "action=schedule only, 1-10080 minutes from now; "
                                 "the console picker only offers today, so a value "
                                 "past midnight cannot be honoured — keep it within "
                                 "the same day",
                                 "仅 action=schedule，取值 1–10080 分钟；"
                                 "控制台选择器只提供「今天」，超过今天 24 点的值"
                                 "无法兑现——请控制在当天内")},
        "wait_publish_s": {"type": "integer", "minimum": 0, "maximum": 900,
                           "default": 180,
                           "description": param(
                               "0-900 seconds to poll 发表记录 for the new msgid; "
                               "0 returns verified=false at once",
                               "轮询发表记录等新 msgid 的秒数，取值 0–900；"
                               "0 表示立刻返回 verified=false")},
        "screenshot": {"type": "boolean", "default": True,
                       "description": param("save a full-page PNG after the submit",
                                           "提交之后存一张整页 PNG")},
    },
    required=("appmsgid",),
)
def mp_publish_draft(appmsgid: int, confirm: bool = False, kind: str = "tietu",
                     action: str = "publish", schedule_minutes: int = 10,
                     wait_publish_s: int = 180, screenshot: bool = True) -> dict:
    security.require_confirm(
        confirm, "publishing a draft",
        "this makes the message public. Pass confirm=true only when the human "
        "explicitly asked to publish this appmsgid",
    )
    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        result = drafts.publish_draft(
            page, token, int(appmsgid), kind=kind, action=action,
            schedule_minutes=int(schedule_minutes),
            wait_publish_s=float(wait_publish_s),
            shot_path=_shot_path("publish_scan"))
        if screenshot:
            result["screenshot"] = console.screenshot(page, _shot_path("publish"))
        result["ok"] = True
        return result


@tool(
    "mp_delete_draft",
    bilingual(
        "Delete a draft from the 草稿箱. IRREVERSIBLE: requires confirm=true. The "
        "console asks 确定删除？ in a popover and notes that 删除该内容不会删除已发表"
        "的内容, so an already published message stays up — this server cannot "
        "recall one. Reports whether the id disappeared from the list afterwards. "
        + constraints.draft_limits(),
        "从草稿箱删除一条草稿。不可撤销：需要 confirm=true。控制台会用气泡问"
        "「确定删除？」，并提示「删除该内容不会删除已发表的内容」，所以已经发出去的"
        "内容不会因此下线——本服务也无法召回它。会回报该 id 之后是否从列表里消失。"
        + constraints.draft_limits_zh(),
    ),
    {
        "appmsgid": {"type": "integer", "minimum": 1,
                     "description": param(
                         "required, integer draft id from mp_list_drafts; the "
                         "title is not an id",
                         "必填，整数草稿 id，来自 mp_list_drafts；标题不是 id")},
        "confirm": {"type": "boolean", "default": False,
                    "description": param(
                        "must be true, otherwise the call is refused with -32602 "
                        "before the browser opens; deletion cannot be undone",
                        "必须为 true，否则在打开浏览器之前就返回 -32602；"
                        "删除不可撤销")},
        "kind": {"type": "string", "enum": ["tietu", "article"], "default": "tietu",
                 "description": param(
                     "which console tab the draft lives in; pass the same kind "
                     "mp_list_drafts reported",
                     "草稿在哪个后台标签页；传 mp_list_drafts 报出来的那个 kind")},
    },
    required=("appmsgid",),
)
def mp_delete_draft(appmsgid: int, confirm: bool = False,
                    kind: str = "tietu") -> dict:
    security.require_confirm(
        confirm, "deleting a draft",
        "the draft cannot be restored. Pass confirm=true only when the human "
        "explicitly asked to delete this appmsgid",
    )
    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        result = drafts.delete_draft(page, token, int(appmsgid), kind=kind)
        result["ok"] = True
        return result