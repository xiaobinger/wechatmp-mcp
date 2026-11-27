# -*- coding: utf-8 -*-
"""The limits a caller has to respect, written once and reused in every schema.

A tool description is the only contract an agent sees before it calls, so the
numbers there must be the numbers the code enforces. Every string here is built
from :mod:`wxmp.config` and :mod:`wxmp.security`, the tool modules embed it, and
``tests/selftest.py`` re-checks the rendered text against the same constants —
a stale description fails the suite instead of misleading a caller.

Descriptions are squashed to one line by ``registry.bilingual``, so the blocks
below use ``•`` separators rather than newlines.
"""
from __future__ import annotations

from . import config, security

IMAGE_TYPES = "/".join(s.lstrip(".") for s in sorted(security.IMAGE_SUFFIXES))
IMAGE_COUNT = config.TIETU_MAX_IMAGES
DESC_LIMIT = config.TIETU_DESC_LIMIT
TITLE_LIMIT = config.TIETU_TITLE_LIMIT
ARTICLE_TITLE_LIMIT = config.ARTICLE_TITLE_LIMIT
DIGEST_LIMIT = config.ARTICLE_DIGEST_LIMIT
AUTHOR_LIMIT = config.ARTICLE_AUTHOR_LIMIT
# The body/description string is capped by the server itself, not by the console:
# a guard against a runaway prompt, chosen well above any real article so a long
# body is never refused by accident.
CONTENT_MAX_CHARS = config.CONTENT_MAX_CHARS


def max_image_mb() -> int:
    return max(1, security.MAX_IMAGE_BYTES // (1024 * 1024))


def image_rule() -> str:
    """What counts as an acceptable local picture, in English."""
    return (f"a local {IMAGE_TYPES} file given as an absolute path that exists, "
            f"at most {max_image_mb()} MB each (raise WXMP_MAX_IMAGE_BYTES to "
            f"allow bigger files)")


def image_rule_zh() -> str:
    return (f"本地 {IMAGE_TYPES} 文件，必须写绝对路径且文件存在，单张最多 "
            f"{max_image_mb()} MB（要更大就调 WXMP_MAX_IMAGE_BYTES）")


def material_limits() -> str:
    """Hard limits of mp_publish_material plus the reply fields to branch on."""
    return (
        f"Limits, enforced before the browser is touched: "
        f"• title is required, 1-{TITLE_LIMIT} characters as the console counts "
        f"them (one CJK ideograph is one character); an empty or longer title is "
        f"rejected with error code -32602 instead of being trimmed. "
        f"• content is refused above {CONTENT_MAX_CHARS} characters with -32602 (the "
        f"server's own guard, not a console limit); for tietu it is the "
        f"description and is clipped to "
        f"{DESC_LIMIT} characters — the reply reports desc_clipped=true; for "
        f"article it is the body, one paragraph per line, and an inline picture "
        f"needs a whole line of its own. "
        f"• author is clipped to {AUTHOR_LIMIT} characters, digest to "
        f"{DIGEST_LIMIT} — both report clipped/requested_chars. "
        f"• cover and images must each be {image_rule()}. "
        f"• for tietu the gallery is cover + images and holds at most "
        f"{IMAGE_COUNT} pictures; kind=article requires cover, and there images "
        f"are appended to the body after the text. "
        f"• action=publish also needs confirm=true and wait_publish_s in 0-900. "
        f"• kind=article with action=publish is implemented but never submitted "
        f"against the live console, so treat verified=false there as unproven. "
        f"Reply fields to branch on: appmsgid (null means no draft id was "
        f"reported), state=draft|published|pending|unknown, verified, cover_ok "
        f"(article only; true only when the reopened draft showed the cover), "
        f"and warning (non-empty means a human should look before publishing)."
    )


def material_limits_zh() -> str:
    return (
        f"硬性要求（在碰浏览器之前就校验）："
        f"• title 必填，1–{TITLE_LIMIT} 个字符，按后台计数口径（一个汉字算一个）；"
        f"空标题或超长直接返回错误码 -32602，不会悄悄截断。"
        f"• content：服务端硬上限 {CONTENT_MAX_CHARS} 个字符；"
        f"tietu 时是描述，超过 {DESC_LIMIT} 字会被截断，回包给 "
        f"desc_clipped=true；article 时是正文，一行一段，插图必须单独占一行。"
        f"• author 超过 {AUTHOR_LIMIT} 字截断，digest 超过 {DIGEST_LIMIT} 字截断，"
        f"回包分别给 clipped / requested_chars。"
        f"• cover 和 images 里的每一项都必须是{image_rule_zh()}。"
        f"• tietu 的图集 = cover + images，最多 {IMAGE_COUNT} 张；"
        f"kind=article 必须给 cover，images 会接在正文文字之后。"
        f"• action=publish 还需要 confirm=true，wait_publish_s 取值 0–900。"
        f"• kind=article 配 action=publish 代码写了但没在真机提交过，那里的 "
        f"verified=false 只代表未证实。"
        f"回包该看哪些字段：appmsgid（null 表示没拿到草稿 id）、"
        f"state=draft|published|pending|unknown、verified、cover_ok"
        f"（仅图文，只有重开草稿看到封面才为 true）、warning（非空表示发表前该让人看一眼）。"
    )


def tietu_limits() -> str:
    """Hard limits of mp_create_tietu."""
    return (
        f"Limits, enforced before the browser is touched: "
        f"• images is required, 1-{IMAGE_COUNT} files, each {image_rule()}; the "
        f"first one becomes the cover. "
        f"• title is required, 1-{TITLE_LIMIT} characters; empty or longer is "
        f"rejected with -32602. "
        f"• description is clipped to {DESC_LIMIT} characters and the reply "
        f"reports desc_clipped=true; the console's own counter is returned as "
        f"desc_counter and is not a 1:1 character count. "
        f"• action=publish or action=schedule needs confirm=true. "
        f"• schedule_minutes is 1-10080, but the time picker only offers today, "
        f"so a large value cannot be honoured — keep it within the same day. "
        f"Reply fields: appmsgid, state, verified (a NEW msgid in 发表记录), "
        f"warning."
    )


def tietu_limits_zh() -> str:
    return (
        f"硬性要求（在碰浏览器之前就校验）："
        f"• images 必填，1–{IMAGE_COUNT} 个文件，每个都要是{image_rule_zh()}；"
        f"第一张作封面。"
        f"• title 必填，1–{TITLE_LIMIT} 个字符；空或超长返回 -32602。"
        f"• description 超过 {DESC_LIMIT} 字截断，回包给 desc_clipped=true；"
        f"控制台自己的计数以 desc_counter 返回，它和字数不是 1:1。"
        f"• action=publish 或 action=schedule 需要 confirm=true。"
        f"• schedule_minutes 范围 1–10080，但时间选择器只提供今天，所以太大的值"
        f"无法兑现——请控制在同一天内。"
        f"回包字段：appmsgid、state、verified（发表记录里出现新 msgid）、warning。"
    )


def draft_limits() -> str:
    """Limits shared by the draft-box tools and the publish tool."""
    return (
        f"Limits: appmsgid must be the integer id from mp_list_drafts / "
        f"mp_publish_material, not the title; kind selects which console tab is "
        f"used; publishing and deleting need confirm=true and are refused with "
        f"-32602 before anything is opened."
    )


def draft_limits_zh() -> str:
    return (
        f"硬性要求：appmsgid 必须是 mp_list_drafts / mp_publish_material 返回的"
        f"整数 id，不是标题；kind 决定用哪个后台标签页；发表和删除都需要 "
        f"confirm=true，否则在打开任何页面之前就返回 -32602。"
    )