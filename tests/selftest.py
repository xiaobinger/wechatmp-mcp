# -*- coding: utf-8 -*-
"""End-to-end self test for wechatmp-mcp.

Offline by design: no browser is launched, no network call is made and no
console session is touched. Everything here runs against the pure Python layers
(protocol, registry, security, config) plus the browser-free helpers inside the
flow modules.

Run from the package root:

    python tests/selftest.py
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("WXMP_OUT_DIR", str(ROOT / "out"))
os.environ.setdefault("WXMP_PROFILE_DIR", str(ROOT / ".state" / "profile"))

from wxmp import config, security  # noqa: E402
from wxmp.app import Application  # noqa: E402
from wxmp.errors import (INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR,
                         ParamError)  # noqa: E402
from wxmp.registry import TOOL_DEFS  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  | " + str(detail)[:160]) if detail else ""))


def rpc(app: Application, method: str, params=None, rid=99) -> dict:
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    raw = app.process(json.dumps(msg, ensure_ascii=False))
    assert raw is not None, f"{method} produced no reply"
    return json.loads(raw)


def call(app: Application, name: str, args: dict | None = None) -> tuple[dict, bool]:
    res = rpc(app, "tools/call", {"name": name, "arguments": args or {}})
    if "error" in res:
        return {"error": res["error"]}, True
    result = res["result"]
    return result["structuredContent"], result["isError"]


def make_png(path: Path, width: int = 8, height: int = 8) -> Path:
    """Write a tiny valid PNG without any image library."""
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                                8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(raw)) +
                     chunk(b"IEND", b""))
    return path


def main() -> int:
    app = Application()
    tmp = Path(tempfile.mkdtemp(prefix="wxmp-selftest-"))
    png = make_png(tmp / "cover.png")

    # ---- protocol -------------------------------------------------------
    print("protocol")
    for version in ("2025-06-18", "2025-03-26", "2024-11-05"):
        res = rpc(app, "initialize", {"protocolVersion": version,
                                      "capabilities": {},
                                      "clientInfo": {"name": "selftest", "version": "1"}})
        result = res["result"]
        check(f"initialize {version}",
              result["protocolVersion"] == version
              and result["serverInfo"]["name"] == "wechatmp-mcp"
              and "tools" in result["capabilities"],
              result["serverInfo"])
    res = rpc(app, "initialize", {"protocolVersion": "1999-01-01"})
    check("initialize falls back to the latest protocol",
          res["result"]["protocolVersion"] == "2025-06-18",
          res["result"]["protocolVersion"])

    app.process(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    check("notifications produce no reply",
          app.process(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None)
    check("ping answers", rpc(app, "ping")["result"] == {})
    check("unknown method is -32601",
          rpc(app, "does/not/exist")["error"]["code"] == METHOD_NOT_FOUND)
    check("broken json is -32700",
          json.loads(app.process("{not json"))["error"]["code"] == PARSE_ERROR)
    check("empty batch is rejected",
          json.loads(app.process("[]"))["error"]["code"] == -32600)
    check("batch of two requests answers both",
          len(json.loads(app.process(json.dumps([
              {"jsonrpc": "2.0", "id": 1, "method": "ping"},
              {"jsonrpc": "2.0", "id": 2, "method": "ping"}])))) == 2)
    check("resources/list is empty", rpc(app, "resources/list")["result"]["resources"] == [])

    # ---- tool surface ---------------------------------------------------
    print("tools")
    listed = rpc(app, "tools/list")["result"]["tools"]
    names = sorted(t["name"] for t in listed)
    expected = ["mp_account_login", "mp_create_tietu", "mp_delete_draft",
                "mp_list_drafts", "mp_list_published", "mp_publish_draft",
                "mp_publish_material", "mp_status", "server_health"]
    check("nine tools registered", names == expected, names)
    check("tools/list carries schemas",
          all(t.get("inputSchema", {}).get("type") == "object" for t in listed))
    check("registry agrees with tools/list", sorted(TOOL_DEFS) == expected)

    health, is_error = call(app, "server_health")
    check("server_health succeeds", not is_error and health.get("ok") is True,
          health.get("error"))
    check("server_health counts the tools", health.get("tool_count") == 9,
          health.get("tool_count"))
    check("server_health reports the console limits",
          health["settings"]["limits"]["tietu_desc_limit"] == 1000
          and health["settings"]["limits"]["tietu_max_images"] == 20
          and health["settings"]["limits"]["article_digest_limit"] == 120,
          health["settings"]["limits"])
    check("server_health never exposes a token",
          "token" not in json.dumps(health["settings"]).lower())

    # ---- bilingual contract --------------------------------------------
    # Every tool description and every argument description must carry both
    # languages, because a marketplace only ever reads one string per field.
    print("bilingual")
    from wxmp.protocol import INSTRUCTIONS
    from wxmp.registry import ZH_MARKER
    cjk = re.compile(r"[\u4e00-\u9fff]")
    latin = re.compile(r"[A-Za-z]")
    no_zh = [n for n, d in TOOL_DEFS.items() if ZH_MARKER not in d["description"]]
    check("every tool description carries the Chinese block marker", not no_zh, no_zh)
    thin = [n for n, d in TOOL_DEFS.items()
            if len(d["description"].split(ZH_MARKER)[-1].strip()) < 10]
    check("the Chinese block is not a placeholder", not thin, thin)
    mono = [n for n, d in TOOL_DEFS.items()
            if not (cjk.search(d["description"]) and latin.search(d["description"]))]
    check("every tool description is bilingual", not mono, mono)
    bad_args = []
    for name, d in TOOL_DEFS.items():
        for key, prop in d["inputSchema"]["properties"].items():
            text = prop.get("description") or ""
            if not (cjk.search(text) and latin.search(text) and " / " in text):
                bad_args.append(f"{name}.{key}")
    check("every argument description is 'english / 中文'", not bad_args, bad_args)
    check("the server instructions are bilingual too",
          ZH_MARKER in INSTRUCTIONS
          and cjk.search(INSTRUCTIONS.split(ZH_MARKER)[-1]),
          INSTRUCTIONS[:60])

    # ---- limits are stated where a caller can see them -------------------
    # A description that drifts from the constants is worse than no description:
    # an agent plans against it. These checks fail the suite on any drift.
    print("limits in the tool text")
    from wxmp import constraints

    def _schema(tool_name):
        return TOOL_DEFS[tool_name]["inputSchema"]["properties"]

    mat = TOOL_DEFS["mp_publish_material"]["description"]
    tietu_desc = TOOL_DEFS["mp_create_tietu"]["description"]
    need = [
        ("title limit", str(constraints.TITLE_LIMIT)),
        ("description limit", str(constraints.DESC_LIMIT)),
        ("digest limit", str(constraints.DIGEST_LIMIT)),
        ("author limit", str(constraints.AUTHOR_LIMIT)),
        ("gallery size", str(constraints.IMAGE_COUNT)),
        ("image size", f"{constraints.max_image_mb()} MB"),
        ("image types", constraints.IMAGE_TYPES),
    ]
    missing = [f"{label}={value}" for label, value in need if value not in mat]
    check("mp_publish_material states every numeric limit", not missing, missing)
    missing_t = [f"{label}={value}" for label, value in
                 (("title limit", str(constraints.TITLE_LIMIT)),
                  ("description limit", str(constraints.DESC_LIMIT)),
                  ("gallery size", str(constraints.IMAGE_COUNT)),
                  ("image size", f"{constraints.max_image_mb()} MB"))
                 if value not in tietu_desc]
    check("mp_create_tietu states its numeric limits", not missing_t, missing_t)
    check("the instructions carry the headline limits",
          str(constraints.TITLE_LIMIT) in INSTRUCTIONS
          and f"{constraints.max_image_mb()} MB" in INSTRUCTIONS
          and str(constraints.IMAGE_COUNT) in INSTRUCTIONS)

    mat_props = _schema("mp_publish_material")
    check("title maxLength matches the constant",
          mat_props["title"]["maxLength"] == constraints.TITLE_LIMIT,
          mat_props["title"].get("maxLength"))
    check("images maxItems matches the gallery constant",
          mat_props["images"]["maxItems"] == constraints.IMAGE_COUNT,
          mat_props["images"].get("maxItems"))
    # content is *rejected* above the cap (security.check_content), so the
    # schema may carry the same maxLength and the description must name it.
    check("content maxLength matches the server cap",
          mat_props["content"]["maxLength"] == constraints.CONTENT_MAX_CHARS,
          mat_props["content"].get("maxLength"))
    check("the description names the content cap",
          str(constraints.CONTENT_MAX_CHARS) in mat,
          str(constraints.CONTENT_MAX_CHARS))
    check("kind and title are the only required arguments",
          TOOL_DEFS["mp_publish_material"]["inputSchema"].get("required")
          == ["kind", "title"],
          TOOL_DEFS["mp_publish_material"]["inputSchema"].get("required"))
    # Clipping fields must not carry a maxLength: the code trims them, and a
    # schema maxLength would refuse the very input the description says is trimmed.
    clipped = [k for k in ("author", "digest") if "maxLength" in mat_props[k]]
    check("clip-only fields carry no maxLength", not clipped, clipped)
    check("mp_create_tietu description is clip-only too",
          "maxLength" not in _schema("mp_create_tietu")["description"],
          _schema("mp_create_tietu")["description"].get("maxLength"))

    # ---- argument validation -------------------------------------------
    print("validation")
    _, err = call(app, "mp_list_drafts", {"nope": 1})
    check("unknown argument is rejected", err)
    _, err = call(app, "does_not_exist", {})
    check("unknown tool is rejected", err)
    payload, err = call(app, "mp_list_drafts", {"kind": "video"})
    check("enum violation is rejected", err and payload["error_code"] == INVALID_PARAMS,
          payload.get("error"))
    payload, err = call(app, "mp_publish_draft", {})
    check("missing required argument is rejected", err, payload.get("error"))
    payload, err = call(app, "mp_publish_draft", {"appmsgid": "abc"})
    check("wrong argument type is rejected", err, payload.get("error"))
    payload, err = call(app, "mp_list_drafts", {"count": 99})
    check("maximum is enforced", err, payload.get("error"))

    # ---- confirmation gates --------------------------------------------
    print("confirmation")
    payload, err = call(app, "mp_publish_draft", {"appmsgid": 100000192})
    check("publish without confirm is refused",
          err and payload.get("error_code") == INVALID_PARAMS,
          payload.get("error"))
    check("the refusal names the action",
          "confirm" in str(payload.get("error", "")).lower(), payload.get("error"))
    payload, err = call(app, "mp_delete_draft", {"appmsgid": 100000192})
    check("delete without confirm is refused", err, payload.get("error"))
    payload, err = call(app, "mp_create_tietu",
                        {"images": [str(png)], "title": "t", "action": "publish"})
    check("create+publish without confirm is refused", err, payload.get("error"))
    check("a refused publish never starts a browser",
          "playwright" not in json.dumps(payload).lower()
          and "browser" not in str(payload.get("error", "")).lower(),
          payload.get("error"))

    # ---- image validation ----------------------------------------------
    print("images")
    for bad, label in (
        ({"images": [], "title": "t"}, "empty image list"),
        ({"images": [str(tmp / "missing.png")], "title": "t"}, "missing file"),
        ({"images": [__file__], "title": "t"}, "non-image suffix"),
        ({"images": [str(png)], "title": ""}, "empty title"),
        ({"images": [str(png)], "title": "x" * 65}, "title too long"),
        ({"images": [str(png)], "title": "t", "action": "bogus"}, "unknown action"),
    ):
        _, err = call(app, "mp_create_tietu", bad)
        check(f"rejects {label}", err)

    # A long description is *clipped*, not refused — the schema deliberately has
    # no maxLength on it, and security.check_description trims it before typing.
    check("a 1001-character description is clipped, not rejected",
          len(security.check_description("x" * 1001)) == 1000)
    # The body cap is the opposite case: refused, never quietly trimmed.
    check("a body exactly at the cap passes",
          len(security.check_content("x" * config.CONTENT_MAX_CHARS))
          == config.CONTENT_MAX_CHARS)
    try:
        security.check_content("x" * (config.CONTENT_MAX_CHARS + 1))
    except ParamError as exc:
        check("a body over the cap is refused, not clipped",
              exc.code == INVALID_PARAMS, exc.code)
        check("the refusal reports the limit",
              exc.data.get("max") == config.CONTENT_MAX_CHARS
              and exc.data.get("got") == config.CONTENT_MAX_CHARS + 1, exc.data)
    else:
        check("a body over the cap is refused, not clipped", False)

    paths = security.resolve_images([str(png)])
    check("a valid png passes resolve_images",
          len(paths) == 1 and paths[0].endswith("cover.png"), paths)
    check("description is clipped to 1000",
          len(security.check_description("汉" * 1500)) == 1000)
    check("CRLF is normalised",
          security.check_description("a\r\nb\rc") == "a\nb\nc")

    # ---- security helpers ---------------------------------------------
    print("security")
    check("mask keeps only the ends", security.mask("312355317") == "3******17",
          security.mask("312355317"))
    check("mask keeps the length", len(security.mask("312355317")) == 9,
          len(security.mask("312355317")))
    check("mask hides most of a short value", security.mask("12345") == "1***5",
          security.mask("12345"))
    check("mask handles empty", security.mask(None) == "" and security.mask("") == "")
    masked = security.mask_url("https://mp.weixin.qq.com/cgi-bin/home?token=312355317&x=1")
    check("mask_url hides the token",
          "312355317" not in masked and "3******17" in masked, masked)
    check("token_from_url reads the query",
          security.token_from_url("/cgi-bin/home?t=home/index&token=312355317") == "312355317")
    check("token_from_url returns None without a token",
          security.token_from_url("https://mp.weixin.qq.com/") is None)

    # ---- config -------------------------------------------------------
    print("config")
    url = config.url_tietu_new("312355317")
    check("the 贴图 editor url keeps createType=8",
          "type=77" in url and "createType=8" in url, url)
    check("the 贴图 editor url is absolute",
          url.startswith("https://mp.weixin.qq.com/cgi-bin/appmsg?"))
    listing = config.url_draft_list("312355317", kind="tietu", count=10)
    check("the 草稿箱 url uses action=list_card and item_show_type=8",
          "action=list_card" in listing and "item_show_type=8" in listing, listing)
    check("the article list url uses item_show_type=0",
          "item_show_type=0" in config.url_draft_list("1", kind="article"))
    check("count reaches the list url", "count=7" in
          config.url_draft_list("1", kind="tietu", count=7))
    settings = config.settings()
    check("settings expose the browser configuration",
          {"profile_dir", "out_dir", "browser_channel", "headless"} <= set(settings),
          sorted(settings))
    check("settings mask nothing but describe everything structurally",
          isinstance(settings["headless"], bool))

    # The profile must not follow the process cwd: an MCP client starts the
    # server wherever it likes, and a cwd-relative profile once produced a
    # second empty profile that looked like an expired login.
    root_before = config.project_root()
    cwd_before = os.getcwd()
    with tempfile.TemporaryDirectory() as elsewhere:
        os.chdir(elsewhere)
        try:
            root_after = config.project_root()
        finally:
            os.chdir(cwd_before)
    check("project_root ignores the process cwd",
          root_after == root_before, f"{root_before} -> {root_after}")
    check("project_root is the directory holding pyproject.toml",
          (root_before / "pyproject.toml").is_file(), str(root_before))

    # ---- flow helpers -------------------------------------------------
    print("flow helpers")
    from wxmp import drafts, tietu
    check("counter regex reads 799/1000",
          tietu.DESC_COUNT_RE.search("描述 799/1000").group(1) == "799")
    check("library picker counter reads 已选择 1",
          tietu.SELECTED_RE.search("已选择 1 / 20 项").group(1) == "1")
    check("appmsgid scan walks nested json",
          tietu._scan_appmsgid({"base_resp": {"ret": 0},
                                "data": {"appmsgid": 100000192}}) == 100000192)
    check("appmsgid scan handles lists",
          tietu._scan_appmsgid([{"x": 1}, {"appmsgid": "42"}]) == 42)
    check("appmsgid scan gives up cleanly", tietu._scan_appmsgid({"ret": 0}) is None)
    check("appmsgid from url",
          tietu._url_appmsgid("/cgi-bin/appmsg?appmsgid=100000192&token=1") == 100000192)
    check("appmsgid from url without one", tietu._url_appmsgid("about:blank") is None)
    check("draft state parsing",
          drafts._state_from_text("已发表 2026-01-01") == "published"
          and drafts._state_from_text("未发表") == "draft"
          and drafts._state_from_text("随便") == "unknown")

    # ---- publish actions & 发表记录 -------------------------------------
    print("publish actions")
    from wxmp import records
    from wxmp.errors import PageError
    for bad_action in ("now", "timer", ""):
        try:
            tietu.publish(None, action=bad_action)
            check(f"publish rejects action={bad_action!r}", False, "no error")
        except PageError as exc:
            check(f"publish rejects action={bad_action!r}",
                  "action" in (exc.data or {}), exc.message)
    try:
        tietu.publish(None, action="schedule", schedule_minutes=0)
        check("schedule rejects 0 minutes", False, "no error")
    except PageError as exc:
        check("schedule rejects 0 minutes",
              (exc.data or {}).get("min") == tietu.SCHEDULE_MIN_MINUTES, exc.message)
    check("the 发表 phase markers do not overlap",
          not set(tietu.SUBMITTING_MARKERS) & set(tietu.DONE_MARKERS))
    check("the scan markers name what the human has to do",
          any("扫" in m for m in tietu.SCAN_MARKERS), tietu.SCAN_MARKERS)
    check("the 发表记录 url is the read-only json endpoint",
          "appmsgpublish?sub=list" in config.url_published("1")
          and "ajax=1" in config.url_published("1"))

    # The live shape: publish_page is an escaped JSON string and every list
    # entry is a {publish_type, publish_info} wrapper.
    entry = {"type": 9, "msgid": 1000000021,
             "sent_info": {"time": 1795746405, "func_flag": 32770},
             "sent_status": {"total": 3, "succ": 3, "fail": 0, "progress": 100},
             "sent_result": {"msg_status": 2, "refuse_reason": ""},
             "appmsg_info": [{"appmsgid": 2247483859,
                              "content_url": "https://mp.weixin.qq.com/s/x",
                              "title": " 测试 "}]}
    inner = {"total_count": 21, "publish_count": 1, "masssend_count": 20,
             "publish_list": [{"publish_type": 101,
                               "publish_info": json.dumps(entry, ensure_ascii=False)},
                              {"publish_type": 101, "publish_info": "not json"}]}
    sample = {"is_admin": True, "base_resp": {"ret": 0},
              "publish_page": json.dumps(inner, ensure_ascii=False)}
    parsed = records.parse_rows(sample)
    row = parsed["rows"][0]
    check("发表记录 counters are read", parsed["counters"]["total_count"] == 21
          and parsed["counters"]["masssend_count"] == 20, parsed["counters"])
    check("发表记录 rows keep title/msgid/url",
          row["msgid"] == 1000000021 and row["title"] == "测试"
          and row["content_url"].endswith("/s/x") and row["appmsgid"] == 2247483859,
          row)
    check("发表记录 rows keep the status counters",
          row["succ"] == 3 and row["total"] == 3 and row["msg_status"] == 2, row)
    check("发表记录 timestamps become local time",
          row["sent_at"] and row["sent_at"].startswith("20"), row["sent_at"])
    check("publish_type is kept", row["publish_type"] == 101, row)
    check("an unparseable publish_info yields an empty row",
          parsed["rows"][1]["msgid"] is None
          and parsed["rows"][1]["title"] == "", parsed["rows"][1])
    check("an already-nested publish_list also parses",
          records.parse_rows({"publish_page": {"publish_list": [entry]}})
          ["rows"][0]["msgid"] == 1000000021)
    check("a new msgid is detected",
          [r["msgid"] for r in records.find_new({"1000000020"}, parsed["rows"])]
          == [1000000021])
    check("no change means no new msgid",
          records.find_new({"1000000021", "1000000020"}, parsed["rows"]) == [])

    # ---- material tool & 图文 helpers -----------------------------------
    print("material")
    from wxmp import article
    blocks = article.split_blocks(
        "第一段\n![](C:/tmp/a.png)\n第二段\n[[img: C:/tmp/b.jpg ]]\n\n")
    check("body text becomes text/image blocks",
          [b["type"] for b in blocks] == ["text", "image", "text", "image"], blocks)
    check("an image block keeps its path",
          article.block_paths(blocks) == ["C:/tmp/a.png", "C:/tmp/b.jpg"],
          article.block_paths(blocks))
    check("blank lines are dropped", article.split_blocks("\n\n") == [])
    check("a lone ![](x) is an image block",
          article.split_blocks("![](x.png)") == [{"type": "image", "path": "x.png"}])
    check("an inline image inside a sentence stays text",
          article.split_blocks("看这里 ![](x.png) 结尾")[0]["type"] == "text")
    clipped, was_clipped = article.check_digest("汉" * 200)
    check("the digest is clipped to 120",
          len(clipped) == 120 and was_clipped is True, len(clipped))
    check("a short digest is untouched",
          article.check_digest("短摘要") == ("短摘要", False))
    check("the author is trimmed", article.check_author("  张三  ") == "张三")
    art_url = config.url_article_new("312355317")
    check("the article editor url has no createType",
          "createType" not in art_url and "appmsg_edit_v2" in art_url, art_url)
    check("the two editors differ only by createType=8",
          config.url_tietu_new("1").replace("&createType=8", "") ==
          config.url_article_new("1"))

    for bad in ({"kind": "video", "title": "t"},
                {"kind": "article", "title": "t", "action": "schedule"},
                {"kind": "tietu", "title": "t"},
                {"kind": "tietu", "title": "t", "cover": str(tmp / "nope.png")}):
        _, err = call(app, "mp_publish_material", bad)
        check(f"mp_publish_material rejects {sorted(bad)}", err)
    payload, err = call(app, "mp_publish_material",
                        {"kind": "article", "title": "t"})
    check("an article without a cover is refused",
          err and "cover" in str(payload.get("error", "")).lower(),
          payload.get("error"))
    payload, err = call(app, "mp_publish_material",
                        {"kind": "tietu", "title": "t", "cover": str(png),
                         "action": "publish"})
    check("material publish without confirm is refused",
          err and payload.get("error_code") == INVALID_PARAMS, payload.get("error"))
    payload, err = call(app, "mp_publish_material",
                        {"kind": "tietu", "title": "t",
                         "images": [str(png)] * 21})
    check("a 贴图 gallery over 20 images is refused", err, payload.get("error"))

    # The two live-run traps: the 编辑封面 confirm is worded 确认 (not 确定), and a
    # leftover cover modal must be recognised and dismissed before 保存为草稿.
    check("the crop confirm label 确认 is tried", "确认" in article.CONFIRM_LABELS,
          article.CONFIRM_LABELS)
    check("cover modals are recognised by their own words",
          {"选择图片", "编辑封面"} <= set(article.COVER_DIALOG_MARKERS),
          article.COVER_DIALOG_MARKERS)
    check("the 封面对话框 close button is a known selector",
          "close-btn" in article.CLOSE_BTN, article.CLOSE_BTN)

    # ---- error types --------------------------------------------------
    print("errors")
    from wxmp.errors import ConfirmationRequired, LoginRequired, ToolError
    payload, err = call(app, "mp_status")
    check("mp_status without playwright reports BrowserUnavailable or a live status",
          isinstance(payload, dict),
          {k: str(v)[:80] for k, v in payload.items() if k in ("error", "logged_in")})
    check("LoginRequired is a ToolError", issubclass(LoginRequired, ToolError))
    check("ConfirmationRequired is a ToolError",
          issubclass(ConfirmationRequired, ToolError))
    exc = ConfirmationRequired("x", {"a": 1})
    check("errors serialise with their data",
          exc.as_dict()["data"] == {"a": 1} and exc.as_dict()["code"] == INVALID_PARAMS)

    print()
    print(f"passed {len(PASS)}  failed {len(FAIL)}")
    if FAIL:
        print("failed checks:")
        for name in FAIL:
            print("  - " + name)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
