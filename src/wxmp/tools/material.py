# -*- coding: utf-8 -*-
"""One tool for both material types: 贴图 (image message) and 图文 (article).

``mp_create_tietu`` stays as the gallery-oriented 贴图 tool. This one takes the
same inputs a human would type into the console — a title, a cover image, the
body (inline images included) and the material type — and either keeps a draft
or publishes straight from the editor, without detouring through 草稿箱.
"""
from __future__ import annotations

import time

from .. import (article, browser, config, console, constraints, records,
                security, tietu)
from ..errors import ParamError
from ..registry import bilingual, param, tool

KINDS = ("tietu", "article")
ACTIONS = ("draft", "publish")


def _shot_path(name: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return str(config.out_dir() / f"{name}_{stamp}.png")


def _resolve_cover(raw: str) -> str | None:
    raw = (raw or "").strip()
    return security.resolve_images([raw])[0] if raw else None


@tool(
    "mp_publish_material",
    bilingual(
        "Create one piece of material in the WeChat Official Account console from "
        "a title, a cover image and a body, then keep it as a draft or publish it "
        "straight from the editor. kind=tietu builds a 贴图 (image message): cover "
        "plus any extra images become the gallery, content is the description. "
        "kind=article builds a 图文 article: cover is the 封面 chosen through the "
        "console's image library (the console has no local cover upload), content "
        "is the body, and a line that is just ![](/path/to.png) or "
        "[[img:/path/to.png]] inserts that local image at that point of the body; "
        "author and digest fill 作者 and 摘要. action=draft (default) stops at 草稿箱; "
        "action=publish submits from the same editor with the console's own 发表 "
        "control, needs confirm=true, and then shows the admin 扫码 page that a "
        "human must scan with WeChat. verified=true only when a NEW msgid appears "
        "in 发表记录 — for action=publish with wait_publish_s>0 only. "
        + constraints.material_limits(),
        "用标题、封面图和正文在公众号后台做一份素材，然后存草稿或直接从编辑器发表。"
        "kind=tietu 做贴图：封面加上额外图片就是图集，content 是描述。"
        "kind=article 做图文：封面走后台的图片库（后台没有本地封面入口），"
        "content 是正文，某一行只有 ![](/path/to.png) 或 [[img:/path/to.png]] 时，"
        "就在那里插入这张本地图片；author 和 digest 分别填作者和摘要。"
        "action=draft（默认）停在草稿箱；action=publish 用后台自己的发表按钮"
        "从同一个编辑器直接提交，需要 confirm=true，之后会出现扫码页，"
        "必须由人用微信扫。只有发表记录里出现「新」msgid 才 verified=true——"
        "仅限 action=publish 且 wait_publish_s>0 的情况。"
        + constraints.material_limits_zh(),
    ),
    {
        "kind": {"type": "string", "enum": list(KINDS),
                 "description": param(
                     "required, one of tietu|article: tietu builds a 贴图 image "
                     "message, article builds a 图文 article. The two open "
                     "different editors and read different fields, so it has no "
                     "default",
                     "必填，取值 tietu|article：tietu 做贴图，article 做图文。"
                     "两者编辑器不同、字段也不同，所以不给默认值")},
        "title": {"type": "string", "minLength": 1,
                  "maxLength": constraints.TITLE_LIMIT,
                  "description": param(
                      f"required, 1-{constraints.TITLE_LIMIT} characters as the "
                      f"console counts them (one CJK ideograph counts as one). "
                      f"An empty or over-long title is rejected with -32602 and "
                      f"is never trimmed",
                      f"必填，1–{constraints.TITLE_LIMIT} 个字符（按后台计数口径，"
                      f"一个汉字算一个）。空标题或超长直接返回 -32602，"
                      f"不会截断")},
        "content": {"type": "string", "maxLength": constraints.CONTENT_MAX_CHARS,
                    "default": "",
                    "description": param(
                        f"kind=tietu: the description, newlines become "
                        f"paragraphs, clipped to {constraints.DESC_LIMIT} "
                        f"characters (reply sets desc_clipped=true). kind=article: "
                        f"the body, one paragraph per line; a line holding only "
                        f"![](/abs/path.png) or [[img:/abs/path.png]] inserts "
                        f"that picture there and the line itself is not typed. "
                        f"Hard cap {constraints.CONTENT_MAX_CHARS} characters: "
                        f"longer is rejected with -32602 (a guard against a "
                        f"runaway prompt, not a console limit)",
                        f"kind=tietu：描述，换行分段，超过 "
                        f"{constraints.DESC_LIMIT} 字截断（回包 desc_clipped=true）。"
                        f"kind=article：正文，一行一段；某一行只有 "
                        f"![](/绝对路径.png) 或 [[img:/绝对路径.png]] 时在该处插图，"
                        f"这一行本身不会作为文字写入。服务端硬上限 "
                        f"{constraints.CONTENT_MAX_CHARS} 字符，超过直接返回 "
                        f"-32602（这是防失控的闸门，不是后台的限制）")},
        "cover": {"type": "string", "default": "",
                  "description": param(
                      f"required for kind=article, optional for kind=tietu (then "
                      f"it is the gallery's first picture). Must be "
                      f"{constraints.image_rule()}",
                      f"kind=article 必填，kind=tietu 可省（此时作图集第一张）。"
                      f"必须是{constraints.image_rule_zh()}")},
        "images": {"type": "array", "maxItems": constraints.IMAGE_COUNT,
                   "default": [],
                   "description": param(
                       f"extra pictures, each {constraints.image_rule()}. "
                       f"kind=tietu: the gallery is cover + images together and "
                       f"holds at most {constraints.IMAGE_COUNT}, so with a cover "
                       f"at most {constraints.IMAGE_COUNT - 1} entries here. "
                       f"kind=article: they are appended to the body after the "
                       f"text",
                       f"额外图片，每个都要是{constraints.image_rule_zh()}。"
                       f"kind=tietu：图集 = cover + images，总共最多 "
                       f"{constraints.IMAGE_COUNT} 张，所以给了 cover 时这里最多 "
                       f"{constraints.IMAGE_COUNT - 1} 个。"
                       f"kind=article：接在正文文字之后")},
        "author": {"type": "string", "default": "",
                   "description": param(
                       f"kind=article only (ignored for tietu): the 作者 field. "
                       f"Not a maxLength in the schema because the code clips "
                       f"instead of refusing: text longer than "
                       f"{constraints.AUTHOR_LIMIT} characters is trimmed and the "
                       f"reply reports clipped=true with requested_chars",
                       f"仅 kind=article（tietu 忽略）：作者字段。schema 里不设 "
                       f"maxLength，因为行为是截断而不是拒绝：超过 "
                       f"{constraints.AUTHOR_LIMIT} 字会被裁掉，回包给 "
                       f"clipped=true 和 requested_chars")},
        "digest": {"type": "string", "default": "",
                   "description": param(
                       f"kind=article only (ignored for tietu): the 摘要 field, "
                       f"trimmed to {constraints.DIGEST_LIMIT} characters with "
                       f"clipped=true in the reply (no maxLength, so a long value "
                       f"is trimmed rather than refused). Leave it empty and the "
                       f"console scrapes the first characters of the body itself",
                       f"仅 kind=article（tietu 忽略）：摘要字段，超过 "
                       f"{constraints.DIGEST_LIMIT} 字会被裁到该长度，回包给 "
                       f"clipped=true（不设 maxLength，所以长文本是截断不是拒绝）。"
                       f"留空则由后台自己抓正文开头")},
        "action": {"type": "string", "enum": list(ACTIONS), "default": "draft",
                   "description": param(
                       "draft (default) keeps it in 草稿箱 without publishing "
                       "anything; publish submits from the same editor with the "
                       "console's own 发表 control and needs confirm=true",
                       "draft（默认）只留在草稿箱，什么都不发表；publish 用后台"
                       "自己的发表按钮从同一个编辑器提交，需要 confirm=true")},
        "confirm": {"type": "boolean", "default": False,
                    "description": param(
                        "must be true for action=publish and is ignored for "
                        "action=draft; publishing is public and cannot be undone",
                        "action=publish 时必须为 true，action=draft 时会忽略；"
                        "发表是公开且不可撤销的")},
        "wait_publish_s": {"type": "integer", "minimum": 0, "maximum": 900,
                           "default": 180,
                           "description": param(
                               "action=publish only, 0-900: how long to poll "
                               "发表记录 for the new msgid; 0 skips the poll and "
                               "answers verified=false at once",
                               "仅 action=publish，取值 0–900：轮询发表记录等新 "
                               "msgid 的秒数；0 表示不轮询、直接返回 "
                               "verified=false")},
        "screenshot": {"type": "boolean", "default": True,
                       "description": param(
                           "save a full-page PNG of the composer to out/ and "
                           "return its path",
                           "把编辑器的整页 PNG 存到 out/ 并返回路径")},
    },
    required=("kind", "title"),
)
def mp_publish_material(kind: str, title: str, content: str = "", cover: str = "",
                        images=(), author: str = "", digest: str = "",
                        action: str = "draft", confirm: bool = False,
                        wait_publish_s: int = 180, screenshot: bool = True) -> dict:
    if kind not in KINDS:
        raise ParamError("unknown kind", {"kind": kind, "allowed": list(KINDS)})
    if action not in ACTIONS:
        raise ParamError("unknown action", {"action": action,
                                           "allowed": list(ACTIONS)})
    title = security.check_title(title)
    content = security.check_content(content)
    extra = list(images or [])
    cover_path = _resolve_cover(cover)

    if action == "publish":
        security.require_confirm(
            confirm, f"action=publish on a {kind}",
            "publishing is public and cannot be undone; pass confirm=true only "
            "after the human approved this exact material",
        )

    if kind == "tietu":
        resolved_extra = security.resolve_images(extra) if extra else []
        gallery = ([cover_path] if cover_path else []) + resolved_extra
        if not gallery:
            raise ParamError(
                "a 贴图 needs at least one image",
                {"hint": "pass cover=<path> or images=[<path>, ...]",
                 "max_images": config.TIETU_MAX_IMAGES})
        if len(gallery) > config.TIETU_MAX_IMAGES:
            raise ParamError(
                "a 贴图 takes at most 20 images",
                {"max": config.TIETU_MAX_IMAGES, "got": len(gallery)})
        description = security.check_description(content)
    else:
        if not cover_path:
            raise ParamError(
                "a 图文 needs a cover image",
                {"hint": "pass cover=<absolute path of a local png/jpeg>",
                 "note": "the console has no local cover upload; the server "
                         "uploads it into 素材库 and picks it there"})
        blocks = article.split_blocks(content)
        inline = article.block_paths(blocks)
        if inline:
            security.resolve_images(inline)
        gallery = security.resolve_images(extra) if extra else []

    with browser.session().exclusive() as page:
        token = console.ensure_logged_in(page)
        result: dict = {"ok": True, "kind": kind, "action": action, "title": title}
        if kind == "tietu":
            created = tietu.create(page, token=token, images=gallery, title=title,
                                   description=description, save=True)
            created["desc_chars_input"] = len(description)
            created["images_requested"] = len(gallery)
            cover_used = "images[0]"
        else:
            created = article.create(page, token=token, title=title, body=content,
                                     cover=cover_path,
                                     images=tuple(gallery),
                                     author=author or "", digest=digest or "",
                                     save=True)
            cover_used = "library"
        created["cover_source"] = cover_used
        result.update(created)
        if screenshot:
            result["screenshot"] = console.screenshot(page, _shot_path(kind))

        draft = result.get("draft") or {}
        result["appmsgid"] = draft.get("appmsgid")

        if action == "draft":
            result["verified"] = bool(result["appmsgid"])
            result["state"] = "draft" if result["appmsgid"] else "unknown"
            result["note"] = ("nothing was published: the console saved a draft "
                              "and the id comes from the save response or the "
                              "editor URL")
            if not result["appmsgid"]:
                result["warning"] = (
                    "the console did not report a draft id; open 草稿箱 and check "
                    "whether it was saved before publishing anything")
        else:
            before: set = set()
            sample_error = None
            if wait_publish_s:
                try:
                    before = records.msgids(
                        records.list_published(page, token)["published"])
                except Exception as exc:  # noqa: BLE001 - verification is optional
                    sample_error = f"{type(exc).__name__}: {exc}".strip()[:200]
            result["publish"] = tietu.publish(
                page, action="publish", shot_path=_shot_path("publish_scan"))
            if sample_error:
                result["before_sample_error"] = sample_error
            if wait_publish_s and before:
                record = records.wait_for_new(page, token, before,
                                              timeout_s=wait_publish_s)
                result["publish_record"] = record
                result["verified"] = bool(record.get("verified"))
            else:
                result["verified"] = False
                result["publish_record"] = {
                    "verified": False,
                    "note": ("发表记录 was not sampled before the submit, so a new "
                             "entry cannot be told apart"),
                }
            result["state"] = "published" if result["verified"] else "pending"
            result["warning"] = (
                "the submit needs the admin scan: a 扫码 page appears right after "
                "the 发表 dialog and the human must scan it with WeChat. The "
                "material only lands in 发表记录 about two minutes later, so "
                "verified=false here means unproven, not failed")
        if kind == "article":
            cover = result.get("cover") or {}
            # Only the reopened draft counts: in the composer the preview node is
            # still 0x0/url("") at submit time, so cover["ok"] there proves nothing.
            result["cover_ok"] = bool(cover.get("verified"))
            if not result["cover_ok"]:
                result.setdefault("warning", (
                    "the 封面 could not be confirmed on the saved draft; re-open "
                    "the draft and check the cover slot before publishing — the "
                    "console refuses to publish without one"))
        return result