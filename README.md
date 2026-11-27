# wechatmp-mcp

An MCP server that drives the **WeChat Official Account back office** from
an MCP client: build an **image message** or a **rich-text article** from a
title, a cover image, the body text and local inline images, then keep it as a
**draft** or **publish it straight from the editor** — with a human in the loop
for every irreversible step.

**English** | [Simplified Chinese](README.zh-CN.md)

- No MCP SDK — a hand-written JSON-RPC 2.0 layer, standard library only at the
  protocol level.
- Two transports: `stdio` (default) and Streamable HTTP.
- **Tool text is bilingual.** MCP exposes exactly one `description` per tool and
  registries ingest that same string, so each description holds an English block
  followed by a Chinese block; argument descriptions use the shorter
  `english / Chinese` form. The same applies to the server instructions and to
  `server.json`, so a marketplace listing shows both languages.
- The login session lives inside a persistent Playwright profile. The server never
  reads, exports or logs a cookie, a storage entry or a usable token.

```
mp_status ──► mp_account_login (scan) ──► mp_publish_material ──► mp_list_drafts
                                             kind=tietu│article        │
                                                   │                  ├─► mp_publish_draft ─┐
                                     action=draft ─┤                  │   (confirm)        │
                                   action=publish ┤                  └─► mp_delete_draft   │
                                                  │             (confirm)                  ▼
                                    admin scans a QR ──► ~2 min ──► mp_list_published
                                                                       (the proof)
```

> A note on the console's language: every label, hint and error on
> `mp.weixin.qq.com` is Chinese. The exact literals are kept as module constants
> in `src/wxmp/tietu.py`, `src/wxmp/article.py` and `src/wxmp/drafts.py`, so there
> is one place to update them when the console changes. This document describes
> them in English.

## Status: what is actually verified

This project was carved out of a hand-run session on a live account (an unverified
personal subscription account) and then re-verified on the same machine. Honesty
about coverage matters more than a feature list.

| Area | State |
| --- | --- |
| Browser launch (system Edge, persistent profile), console login detection, QR screenshot, redirect → token extraction, token masking in every reply | **verified** on a live account |
| `mp_create_tietu` end to end: upload, cover hint, title, description, save draft, draft id | **verified** — one image attached through the uploader input, the cover hint appeared, title and description typed, draft id returned |
| `mp_publish_material` with `kind=tietu, action=draft` | **verified** on draft `100000219` — the unified entry point builds the same image message and reports the new draft id |
| `mp_publish_material` with `kind=article, action=draft` | **verified** on draft `100000232` — title, two body paragraphs, one inline picture, 作者 and 摘要 written, 封面 set through the image library, draft id returned; reopening the draft showed the title, both paragraphs, the inline picture and a real `mmbiz.qpic.cn` cover |
| Cover of a 图文 (the console has **no** local cover upload) | **verified** through 从图片库选择: the picker's 上传文件 input takes the local file, the new entry arrives already ticked, 下一步 → 编辑封面 (2.35:1 / 1:1) → 确认, and the saved draft renders the cover as a 235x100 CSS background image |
| Inline pictures inside a 图文 body | **verified** — the toolbar 图片 → 本地上传 file input inserts the picture at the caret (`.ProseMirror img` went 0 → 2, the editor adds a wrapper node, so the count is a floor) |
| Draft box listing, cards keyed by `data-appid` | **verified**; the console normalises the image-message tab filter to the article value (`0`) whenever that tab is empty, and both the requested and the landed value are reported |
| Opening an existing draft in its composer | **verified** — it is the URL the console itself redirects to after saving a draft |
| `mp_delete_draft` end to end | **verified on draft `100000205`** — the card's icon row is hover-only and textless, so each icon is hovered until its tooltip reads "delete" (index 0; index 2 is "edit"); the confirmation is a **popover**, not a modal, and the id was gone from the list afterwards |
| `mp_publish_draft` with `action=publish` | **verified once, end to end**, on draft `100000210` → msgid `1000000021`: the publish dialog was submitted, **the admin scanned a QR page**, the console then reported "this draft is being published, do not repeat the operation", finished in the background about two minutes after the scan, closed the editor tab itself, the draft disappeared from the draft box and publish records grew from 20 to 21 entries |
| Publish records (`mp_list_published`) | **verified** — the payload is an escaped JSON string whose entries are `{publish_type, publish_info}` wrappers; counters read `total 21 / publish 1 / masssend 20` and the newest entry reproduces msgid `1000000021`, `sent_status 3/3/0`, `msg_status 2`, and its public URL |
| `action=schedule` | **mechanics verified, submission NOT verified** — the switch, the time picker (today, `HH:MM`) and the footer submit were all driven and the console's own pre-flight checks ran, but no publish-record entry appeared afterwards. `verified` is therefore `false` and the reply says so |
| Account quotas as reported by the console | **observed**: one mass-send left (daily `1/1`), `is_admin true`, `is_force_not_masssend 0`, `time_send_oper_left 20`, `face_check_resp.need_check false`, `user_publish_mode 1` |
| Rich-text article composition (`kind=article`) | **draft path verified** (see above). The article **publish** was never submitted: it needs the admin scan and produces public content, so `action=publish` for a 图文 is implemented but **unproven** |
| Group-send preview, asset library management | **not implemented** |
| Bilingual tool text (English + Chinese in one description, arguments as `english / Chinese`) | **enforced by the test suite** — a tool or argument that loses either language fails `selftest` |

> **Correction (important).** An earlier revision of this file claimed that
> publishing needed no QR scan, because the automation only ever saw the "being
> published" text. The account owner confirmed they **scanned a QR page** on that
> run. Publishing is gated by an admin scan; the server screenshots that page,
> waits for the human, and only trusts a new publish-record entry as proof.

Anything in the "not verified" rows may need selector work on your account. The
error payload always carries the page URL (token masked), a screenshot path and
what was clicked, so a failure is diagnosable instead of silent.

## Requirements

- Python 3.10+
- A WeChat Official Account you can log into with the WeChat app
- A browser: **Microsoft Edge** (default) or Chrome. `playwright install` is *not*
  required when you use an installed browser via `WXMP_BROWSER_CHANNEL`.

## Install

```powershell
git clone https://github.com/xiaobinger/wechatmp-mcp
cd wechatmp-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## First run: log in once

The login is manual by design — nobody should be typing a console password into a
tool, and the QR flow is what the console itself offers.

1. Call `mp_status`. It opens `https://mp.weixin.qq.com/` in the controlled browser
   and reports `logged_in: false` plus the login markers it saw.
2. Call `mp_account_login` with `timeout_s` (default 180). It writes a PNG of the
   QR code into `out/` and waits.
   - Scan the QR that is visible **in the browser window** (the PNG is a fallback
     for unattended setups; set `WXMP_DEVICE_SCALE=2` if you need a
     higher-resolution PNG).
   - The call returns as soon as the console redirects with a session token.
3. The session is stored in `WXMP_PROFILE_DIR` and reused by later calls until the
   console expires it. If it expires, the call says so and the QR appears again.

The profile directory contains live login cookies. It is git-ignored; keep it that
way and treat the whole directory as a secret.

Its location is resolved from the package, never from the process working
directory: an MCP client may start the server anywhere, and a cwd-relative profile
would silently create a *second, empty* profile whose console answer is "not logged
in" even though the real one still holds the session. Point `WXMP_PROFILE_DIR` at
the same directory in every client to keep one shared login.

## Tools

| Tool | Confirmation | What it does |
| --- | --- | --- |
| `server_health` | — | Version, protocol versions, registered tools, browser settings, profile state. |
| `mp_status` | — | Opens the console root, reports `logged_in`, the **masked** token, the account nickname when readable. |
| `mp_account_login` | — | QR screenshot + poll until the scan completes. |
| `mp_publish_material` | `action=publish` needs `confirm=true` | **The one-call entry point.** Takes a title, a cover, the body (text plus `![](/abs/path.png)` lines) and `kind=tietu\|article`, then either saves a draft or publishes **straight from the editor** — never "save, then publish from the draft box". |
| `mp_create_tietu` | `action=publish` or `action=schedule` needs `confirm=true` | Uploads 1–20 local images, writes title (≤64) and description (≤1000), then stops at a draft, publishes now, or schedules for later. Kept for multi-image galleries; `mp_publish_material` covers the same ground with one schema. |
| `mp_list_drafts` | — | Lists the draft box (`kind=tietu` or `kind=article`). |
| `mp_publish_draft` | **required** | Opens the draft, presses publish, confirms the dialog, then publishes or schedules it. Irreversible and public. |
| `mp_delete_draft` | **required** | Deletes a draft and reports whether it disappeared from the list. |
| `mp_list_published` | — | Reads publish records with msgid, title, public URL, send time and status counters. Read-only; this is the proof of a publish. |

### Publishing: three actions, one human step

`action` is the single knob:

| `action` | What happens | Result flags |
| --- | --- | --- |
| `draft` (default) | Only "save as draft" is pressed | `state=draft`, `verified=true` when a draft id came back |
| `publish` | Publish → dialog → **admin scans the QR page** → the console works in the background | `verified=true` **only** if a new msgid appears in publish records within `wait_publish_s` (default 180 s); measured landing time was about two minutes after the scan |
| `schedule` | Publish → turn on scheduling → write `HH:MM` (today) → dialog submit | `state=scheduled_unverified`, `verified=false` — the submission never produced a publish-record entry |

`wait_publish_s=0` skips the polling and answers at once with `verified=false`.
Nothing is ever reported as published from page text alone.

### `mp_publish_material` details

```jsonc
{
  "kind": "article",              // "tietu" (image message) | "article" (图文)
  "title": "…",                   // 标题, ≤64 characters
  "cover": "E:\\pics\\cover.png",  // required for article, optional for tietu
  "content": "第一段\n![](E:\\pics\\inline.png)\n第二段",
  "images": [],                   // extra pictures (tietu: gallery, ≤20 with cover)
  "author": "…",                  // 作者 (article only)
  "digest": "…",                  // 摘要 (article only, clipped to 120)
  "action": "draft",              // "draft" (default) | "publish"
  "confirm": false                // must be true for action=publish
}
```

- **`tietu`**: the gallery is `cover` + `images` (≤20). `content` becomes the
  description (≤1000 characters, newlines are paragraphs).
- **`content` cap.** The body/description is refused above 50000 characters
  with `-32602`, never silently trimmed. That ceiling is the server's own guard
  against a runaway prompt (`config.CONTENT_MAX_CHARS`), not a console limit;
  the 1000-character description clip is the only real editor limit.
- **`article`**: `content` is the body. A line that is exactly
  `![](/abs/path.png)` or `[[img:/abs/path.png]]` becomes an inline picture
  inserted at the caret through the toolbar's 图片 → 本地上传; every other line
  becomes a paragraph. `cover` is **mandatory** (see below).
- **Cover.** The console offers no local cover upload at all: the 封面 slot's menu
  holds 从正文选择 / 从图片库选择 / 微信扫码上传 / 一键生成封面. The server uploads
  the file through 从图片库选择 → 上传文件, keeps the entry ticked, presses 下一步,
  waits for the 编辑封面 confirm to become clickable, presses **确认**, then saves
  and **reopens the draft** to read the cover back.
  - The picker is a *list of file names*, not a thumbnail grid, and the item click
    is a **toggle**: right after the upload the new entry is already ticked, so
    clicking its name again unticks it and 下一步 turns grey. That took a live run
    down (`100000245` saved with no cover), which is why the code now reads the
    selection state instead of clicking blindly.
  - In the composer the cover preview is `0x0` with `url("")` for a while even on
    a good save, and the empty slot's text 「拖拽或选择封面」 never disappears —
    neither can be used as a signal. `cover_ok` therefore only reflects the
    **reopened draft** (measured: 235x100 with a `mmbiz.qpic.cn` background).
- **`action=publish`** presses the editor's own 发表 → confirms the dialog → the
  admin scans the QR page → `verified` only when a **new msgid** shows up in
  publish records. For a 图文 this path is implemented but **not yet proven**
  (publishing creates public content, so it was never submitted here).

### `mp_create_tietu` details

- `images`: absolute paths, png/jpg/jpeg/gif/webp, ≤10 MB each (override with
  `WXMP_MAX_IMAGE_BYTES`). The **first image becomes the cover**.
- `description`: newlines become paragraphs. Text longer than 1000 characters is
  clipped before it is typed. The counter the console shows is returned as
  `desc_counter` — it is not a 1:1 character count (995 typed characters including
  paragraph breaks measured `807/1000`).
- **The upload path matters.** The editor has two file inputs: the one owned by the
  image-library picker is inert here — handing it a file sends no request and
  leaves the composer empty. Only the webuploader input behind "upload from local"
  actually uploads, after which the cover hint appears. The menu only exists after
  the add tile is clicked, so the flow clicks the tile first, then sets the files.
  If the uploader ever refuses, the server falls back to the image-library picker
  (which attaches images already in the asset library, newest first) and says so in
  `upload.method`.
- The description is typed with `insert_text`, never through the OS clipboard. HTML
  clipboard flavours were measured to garble CJK text in that editor.

## MCP client configuration

`mcp.entry.json` in this repository is a ready-made stdio entry:

```json
{
  "wxmp": {
    "command": "python",
    "args": ["-m", "wxmp", "--transport", "stdio"],
    "env": { "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1" }
  }
}
```

Use the absolute path of the interpreter you installed into, e.g.
`E:\path\to\wechatmp-mcp\.venv\Scripts\python.exe`.

Streamable HTTP instead of stdio:

```powershell
wxmp --transport http --host 127.0.0.1 --port 8790 --path /mcp --token <secret>
```

`GET /mcp` answers 405 by design (no server-initiated stream); `POST` accepts
JSON-RPC requests, notifications and batches.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `WXMP_PROFILE_DIR` | `./.state/profile` | Playwright profile holding the login. Secret. |
| `WXMP_OUT_DIR` | `./out` | Screenshots: login QR, composer, publish evidence, the admin scan page. |
| `WXMP_BROWSER_CHANNEL` | `msedge` | Installed browser to drive (`msedge`, `chrome`). Empty ⇒ bundled Chromium, which needs `playwright install chromium`. |
| `WXMP_HEADLESS` | `0` | `1` runs without a window. Not recommended: scanning needs one. |
| `WXMP_CDP_URL` | — | Attach to an already-running Chrome (`http://127.0.0.1:9222`) instead of launching. |
| `WXMP_TIMEOUT_MS` | `30000` | Default action timeout. |
| `WXMP_LOGIN_TIMEOUT` | `180` | Default `mp_account_login` wait. |
| `WXMP_DEVICE_SCALE` | `1` | Device pixel ratio; `2` doubles screenshot resolution. |
| `WXMP_VIEWPORT_W/H` | `1280` / `900` | Window size. |
| `WXMP_SLOW_MO` | `0` | Milliseconds of delay per Playwright action, for watching a run. |
| `WXMP_MAX_IMAGE_BYTES` | `10485760` | Per-image size cap. |
| `WXMP_HTTP_TOKEN` | — | Bearer token for the HTTP transport. |
| `WXMP_LOG_LEVEL` | `WARNING` | Logging level; logs go to stderr, never stdout. |

## Safety model

- **Manual login only.** The server screenshots the QR and polls the redirect. It
  never handles a password, a cookie or a session token value.
- **Tokens are masked.** A nine-digit console token is reported with its first and
  last two digits only, everywhere, including in URLs inside error payloads.
- **A human scans before anything goes public.** After the publish dialog the
  console shows a QR page; the server screenshots it into `out/`, waits
  `scan_wait_s` (default 120 s) for the scan and never clicks it itself.
- **Irreversible actions need `confirm=true`**: publishing, deleting, and
  `mp_create_tietu` / `mp_publish_material` with `action=publish`. Without it the
  call is refused *before* the browser is touched, and the draft stays exactly as
  it was.
- **Drafts by default.** Creating an image message or a 图文 saves a draft;
  publishing is always a separate, explicit step.
- **`verified` means publish records, not page text.** A publish is only reported
  as verified when a **new msgid** appears in that list.
- **A 图文 cover is proven, not assumed.** `cover_ok` is only true when the saved
  draft was reopened and its cover rendered a real `mmbiz.qpic.cn` picture; a
  composer preview that still reads `url("")` proves nothing and never counts.
- **Evidence on disk.** Every state-changing call writes a full-page PNG into
  `out/`, so a publish can be audited afterwards.
- **Serialised browser access.** One Playwright session per process; a second
  request waits instead of opening a second browser.

## Troubleshooting

| Symptom | What it means |
| --- | --- |
| `mp_status` says `logged_in: false` while you logged in before | The profile it opened is not the one holding the session. Check `settings.profile_dir` in `server_health` and point `WXMP_PROFILE_DIR` there. |
| The publish call returns `verified: false` | The scan was not completed, the publish is still queued, or the list was read too early. Re-run `mp_list_published` before assuming failure. |
| The publish call returns `needs_scan: true` | That is the expected path. Open the browser window, scan the QR, then re-read publish records. |
| `action=schedule` returns `scheduled_unverified` | Expected for now: the submission never produced a publish-record entry. Verify in the console before relying on it. |
| The image never reaches the composer | The uploader input did not accept the file; the reply's `upload` block says which method was tried. A modal on the page (unverified account, new-device check) is the usual cause. |
| A 图文 reply has `cover_ok: false` | The reopened draft showed no cover picture. Re-open the draft and pick the 封面 by hand before publishing — the console refuses to publish without one. `cover.pick` / `cover.crop_confirm` say which step did not land. |
| `the 保存为草稿 button was not found` | A cover modal was still on screen and swallowed the click; `error_data.open_dialogs` names it. The code now dismisses those dialogs first, so seeing this means a *new* modal appeared — report its wording. |
| `Execution context was destroyed` in the logs | The console navigated or closed the tab mid-call. The publish path tolerates it; the publish record is still the proof. |

## Tests

```powershell
python tests/selftest.py    # 108 offline checks: protocol, registry, validation,
                            # confirmation gates, masking, URL building, helpers,
                            # publish actions, publish-record parsing, the
                            # bilingual tool-text contract, the 图文 block rules
python tests/ci_smoke.py    # 15 checks including a real stdio subprocess handshake
```

Both are offline: no browser, no network, no console session. They also run on
Linux, so they are safe as CI gates.

## Layout

```
src/wxmp/
  app.py         transport-agnostic Application: bytes in, JSON out
  protocol.py    JSON-RPC 2.0 / MCP method table (2024-11-05 … 2025-06-18)
  registry.py    tool decorator, schema validation, call_tool
  config.py      env-driven settings and console URLs
  security.py    confirmation gates, image checks, token masking
  browser.py     Playwright session, persistent profile, thread re-binding
  console.py     login detection, QR capture, token extraction
  tietu.py       image-message flow: upload, title, description, save,
                 publish / schedule, admin-scan wait
  article.py     图文 flow: title, body blocks, inline pictures, 作者 / 摘要,
                 封面 through the image library, and the draft re-read
  drafts.py      draft box: list, open, publish, delete
  records.py     publish records: the read-only proof that a publish happened
  tools/         the nine MCP tools
  transports/    stdio + Streamable HTTP
tests/           selftest.py, ci_smoke.py
```

## License

MIT. This is unofficial automation of a private console; it is not affiliated with
or endorsed by Tencent, and using it may be subject to the platform's terms. Run it
against an account you own.