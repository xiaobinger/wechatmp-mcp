# -*- coding: utf-8 -*-
"""发表记录 tool: the read-only proof that something was really published."""
from __future__ import annotations

from .. import browser, console, records
from ..registry import bilingual, param, tool


@tool(
    "mp_list_published",
    bilingual(
        "List 发表记录 (already published items) — NOT the 草稿箱. Read-only. "
        "Reads /cgi-bin/appmsgpublish?sub=list and returns the counters (total / "
        "publish / masssend), plus per-item msgid, title, public content_url, "
        "sent_at, the sent_status counters and msg_status. This is the only honest "
        "way to confirm a publish: the composer only shows 「该草稿正在发表」 while "
        "the item appears here about two minutes after the admin scan. Limits: count "
        "is 1-50 (default 20) and one response is one page; msgid is the integer "
        "the other publish tools never return — it is what proves a publish, not "
        "the draft's appmsgid.",
        "列出发表记录（已经发出去的内容）——不是草稿箱。只读。读取 "
        "/cgi-bin/appmsgpublish?sub=list，返回计数（total / publish / masssend），"
        "以及每条的 msgid、标题、公开链接 content_url、发送时间 sent_at、"
        "发送状态计数和 msg_status。这是确认「真的发出去了」唯一可靠的方式："
        "编辑器里只会显示「该草稿正在发表」，而内容要等管理员扫码后约 2 分钟"
        "才会出现在这里。限制：count 取值 1–50（默认 20），一次响应就是一页；"
        "msgid 是整数，别和草稿的 appmsgid 搞混——证明发表的是 msgid。",
    ),
    {
        "count": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20,
                  "description": param(
                      "how many records to request from the console, 1-50; this is "
                      "a page size, not a cursor",
                      "向控制台请求多少条记录，取值 1–50；这是页大小，不是游标")},
    },
)
def mp_list_published(count: int = 20) -> dict:
    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        data = records.list_published(page, token, count=int(count))
        data["ok"] = True
        return data