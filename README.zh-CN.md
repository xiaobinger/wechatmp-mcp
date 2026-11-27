# wechatmp-mcp

一个 MCP Server，从 MCP 客户端驱动**微信公众号后台**：用标题、封面图、正文（可含插图）
做一条**贴图**或一篇**图文**，然后**留作草稿**，或者**直接在编辑器里发表**（不是先存草稿
再进草稿箱发表）——每一个不可撤销的动作都留一个人在环里。

[English](README.md) | **简体中文**

- 不用 MCP SDK：手写 JSON-RPC 2.0，协议层只用标准库。
- 两种传输：`stdio`（默认）和 Streamable HTTP。
- **工具文案是中英双语的。** MCP 每个工具只暴露一个 `description`，各平台抓的也是
  同一个字段，所以每条描述里先放英文段、再放中文段；参数描述用更短的
  `english / 中文` 形式。服务端说明（instructions）和 `server.json` 同理，这样上架
  时中英文介绍都在。
- **`server.json` 必须压进 100 字符。** 注册表 schema 把那条 `description` 限死在
  100 字符，所以上架那一行是一句 90 字符的双语短句；详细说明放在工具描述和服务端
  instructions 里，不放在注册表条目里。
- 登录态存在 Playwright 的持久化 profile 里。服务端从不读取、导出或打印 cookie、
  localStorage 或可用的 token。

```
mp_status ──► mp_account_login（扫码）──► mp_publish_material ──► mp_list_drafts
                                              kind=tietu│article        │
                                                    │                  ├─► mp_publish_draft ─┐
                                      action=draft ─┤                  │  （需 confirm）      │
                                    action=publish ┤                  └─► mp_delete_draft   │
                                                   │            （需 confirm）                ▼
                                    管理员扫码 ──► 约 2 分钟 ──► mp_list_published
                                                                     （唯一证据）
```

## 当前状态：到底哪些是真的验证过

这个项目是从一个真机手工会话里抠出来的（一个未认证的个人订阅号），然后在同一台机器上
重新验证。覆盖范围说实话，比功能清单重要。

| 能力 | 状态 |
| --- | --- |
| 启动浏览器（系统 Edge、持久化 profile）、登录态判定、二维码截图、跳转后取 token、所有回包里的 token 打码 | **已验证**，真机账号 |
| `mp_create_tietu` 端到端：上传、封面提示、标题、描述、存草稿、草稿 id | **已验证**——图片通过 webuploader 的 input 上传，`默认首图为封面` 出现，标题和描述写入，草稿 id 从跳转 URL 取到 |
| `mp_publish_material` 的 `kind=tietu, action=draft` | **已在草稿 `100000219` 上验证**——统一入口走同一条贴图链路，回包给出新草稿 id |
| `mp_publish_material` 的 `kind=article, action=draft` | **已在草稿 `100000232` 上验证**——标题、两段正文、一张正文插图、作者与摘要写入，封面从图片库选上，回包给出草稿 id；重开草稿能看到标题、两段正文、插图和真实的 `mmbiz.qpic.cn` 封面 |
| 图文封面（后台**没有**本地上传入口） | **已验证**，走 从图片库选择：弹窗里的 `上传文件` input 收下本地文件，条目上传后即为勾选状态，`下一步` → `编辑封面`（2.35:1、1:1）→ `确认`，已存草稿里封面渲染成 235x100 的 CSS 背景图 |
| 图文正文插图 | **已验证**——工具栏 `图片` → `本地上传` 的 file input 把图插在光标处（`.ProseMirror img` 从 0 变 2，编辑器自己还加一个包装节点，所以这个数是下限） |
| 草稿箱列表、卡片以 `data-appid` 为键 | **已验证**；贴图标签页为空时，控制台会把 `item_show_type` 规范成文章的值 `0`，回包里同时报「请求的值」和「实际落地的值」 |
| 打开已有草稿的编辑器 | **已验证**——用的就是「保存为草稿」之后控制台自己跳转的那个 URL |
| `mp_delete_draft` 端到端 | **已在草稿 `100000205` 上验证**——卡片图标行只有悬停才出现且没有文字，所以逐个悬停到 tooltip 读到 `删除`（index 0；index 2 是 `编辑`）；确认是 **popover** 而不是 modal（`确定删除？删除该内容不会删除已发表的内容` + 主按钮 `删除`），之后该 id 从列表消失 |
| `mp_publish_draft` 的 `action=publish` | **端到端验证过一次**，草稿 `100000210` → msgid `1000000021`：发表弹窗提交后**管理员扫码确认**，页面显示`该草稿正在发表，请勿重复操作`，后台异步约 2 分钟后落地，编辑器标签自己关掉，草稿从草稿箱消失、发表记录从 20 条变 21 条 |
| 发表记录（`mp_list_published`） | **已验证**——返回的 `publish_page` 是一层转义 JSON 字符串，每条记录又包一层 `{publish_type, publish_info}`；计数读到 `total 21 / publish 1 / masssend 20`，最新一条能还原出 msgid `1000000021`、`sent_status 3/3/0`、`msg_status 2` 和公开链接 |
| `action=schedule`（定时发表） | **机制已验证，提交未验证**——开关、时间选择器（今天，`HH:MM`）、footer 的发表都点到了，控制台自己的 `check_hot_time` / `check_same_material` / `check_ad` 预检也都跑了，但之后发表记录没有新增条目。所以返回里 `verified` 是 `false`，回包会写明 |
| 账号配额（控制台自报） | **已观察**：群发额度剩 1 次（每日 `1/1`，2026-11-27 重置）、`is_admin true`、`is_force_not_masssend 0`、`time_send_oper_left 20`、`face_check_resp.need_check false`、`user_publish_mode 1` |
| 图文（富文本文章）创建（`kind=article`） | **草稿链路已验证**（见上表）。图文的**发表**从未提交：它需要管理员扫码且会产生公开内容，所以 `action=publish` 对图文是**写了但未验证** |
| 群发预览、素材库管理 | **未实现** |
| 工具文案中英双语（一条 description 里英文段 + 中文段，参数写成 `english / 中文`） | **由测试强制**——任何工具或参数丢掉其中一种语言，`selftest` 就会失败 |

> **一处更正（重要）。** 早先这版文档写过「发表不需要扫码」，理由是我的脚本只抓到
> `该草稿正在发表` 的文字。账号主人确认：那一次**是扫了二维码之后才发表的**。
> 发表由管理员扫码把关；服务端只负责把扫码页截图存下来、等人扫完，并且只认「发表记录
> 里出现新 msgid」这一条证据。

标「未验证」的行在你的账号上可能需要调选择器。失败时错误回包一定带页面 URL（token 已
打码）、截图路径和点过什么，所以定位得到，不会静默失败。

## 环境要求

- Python 3.10+
- 一个你能用微信登录的公众号
- 浏览器：**Microsoft Edge**（默认）或 Chrome。用 `WXMP_BROWSER_CHANNEL` 指向已安装的
  浏览器时，**不需要** `playwright install`。

## 安装

```powershell
git clone https://github.com/xiaobinger/wechatmp-mcp
cd wechatmp-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

发行包名是 `wechatmp-publish-mcp`（PyPI 上的名字），而代码、命令行入口和 MCP server
名仍然是 `wxmp` / `wechatmp-mcp`。包里有两个入口脚本指向同一个函数——`wxmp` 和
`wechatmp-publish-mcp`——这样包上到 PyPI 之后 `uvx wechatmp-publish-mcp` 就能启动服务，
`server.json` 里的 identifier 也才能和发行包名对上。

## 第一次运行：登录一次

登录是手动设计：不该有人把公众号密码敲进工具里，扫码也正是控制台自己的路径。

1. 调 `mp_status`。它在受控浏览器里打开 `https://mp.weixin.qq.com/`，报 `logged_in:
   false` 以及它看到的登录标记。
2. 调 `mp_account_login`，`timeout_s` 默认 180。它把二维码 PNG 存到 `out/` 然后等。
   - 扫**浏览器窗口里**的那张二维码（PNG 只是无人值守时的兜底；需要更高分辨率就设
     `WXMP_DEVICE_SCALE=2`）。
   - 控制台一旦带着 session token 跳转，这个调用立刻返回。
3. 登录态存在 `WXMP_PROFILE_DIR`，后续调用复用，直到控制台过期。过期时回包会说明，
   二维码会重新出现。

profile 目录里是活的登录 cookie。它已 gitignore；请保持这样，并把整个目录当机密看。

它的位置按包的位置解析，**不看进程工作目录**：MCP 客户端可能从任意目录启动服务，而
cwd 相对的 profile 会悄悄建出**第二个空 profile**，控制台回「未登录」，可真实 profile
里还握着会话。想让多个客户端共用一个登录，就把 `WXMP_PROFILE_DIR` 指到同一个目录。

## 工具

| 工具 | 确认 | 做什么 |
| --- | --- | --- |
| `server_health` | — | 版本、协议版本、已注册工具、浏览器配置、profile 状态。 |
| `mp_status` | — | 打开控制台根路径，报 `logged_in`、**打码后**的 token、能读到时的账号昵称。 |
| `mp_account_login` | — | 二维码截图 + 轮询到扫码完成。 |
| `mp_publish_material` | `action=publish` 需要 `confirm=true` | **一次调用搞定**。传入标题、封面、正文（文字 + `![](/绝对路径.png)` 行）和 `kind=tietu\|article`，然后要么存草稿，要么**直接在编辑器里发表**——不走「先存草稿再进草稿箱发表」。 |
| `mp_create_tietu` | `action=publish` 或 `action=schedule` 需要 `confirm=true` | 上传 1–20 张本地图，写标题（≤64）和描述（≤1000），然后停成草稿、立刻发表，或定时发表。留给多图图集；`mp_publish_material` 用一套参数覆盖同样的事。 |
| `mp_list_drafts` | — | 列草稿箱（`kind=tietu` 贴图 / `kind=article` 文章）。 |
| `mp_publish_draft` | **必填** | 打开草稿、点发表、确认弹窗，然后按 `action` 立刻发表或定时发表。不可撤销、公开可见。 |
| `mp_delete_draft` | **必填** | 删一条草稿，并报它是否从列表里消失了。 |
| `mp_list_published` | — | 读**发表记录**：msgid、标题、公开链接、发送时间、状态计数。只读；这是发表的唯一证据。 |

### 发布：三个动作，一步靠人

`action` 是唯一的开关：

| `action` | 会发生什么 | 结果字段 |
| --- | --- | --- |
| `draft`（默认） | 只按「保存为草稿」 | `state=draft`；拿到草稿 id 时 `verified=true` |
| `publish` | 发表 → 弹窗 → **管理员扫码** → 控制台后台干活 | 只有在 `wait_publish_s`（默认 180 秒）内发表记录出现新 msgid 才 `verified=true`；实测扫码后约 2 分钟落地 |
| `schedule` | 发表 → 打开定时发表 → 填 `HH:MM`（今天）→ 弹窗提交 | `state=scheduled_unverified`、`verified=false`——这次提交没有产生发表记录条目 |

`wait_publish_s=0` 跳过轮询，立刻返回 `verified=false`。任何时候都不会凭页面文字宣布
「已发表」。

### `mp_publish_material` 细节

```jsonc
{
  "kind": "article",              // "tietu"（贴图）| "article"（图文）
  "title": "…",                   // 标题，≤64 字
  "cover": "E:\\pics\\cover.png",  // 图文必填，贴图可省
  "content": "第一段\n![](E:\\pics\\inline.png)\n第二段",
  "images": [],                   // 额外图片（贴图图集，含封面 ≤20 张）
  "author": "…",                  // 作者（仅图文）
  "digest": "…",                  // 摘要（仅图文，超过 120 字截断）
  "action": "draft",              // "draft"（默认）| "publish"
  "confirm": false                // action=publish 时必须为 true
}
```

- **`tietu`**：图集 = `cover` + `images`（≤20 张）。`content` 写入描述（≤1000 字，
  换行即分段）。
- **`content` 硬上限**：正文/描述超过 50000 字符直接返回 `-32602`，不会悄悄截断。
  这个数字是服务端自己防失控的闸门（`config.CONTENT_MAX_CHARS`），不是后台的限制；
  真正的编辑器限制只有描述 1000 字截断这一条。
- **`article`**：`content` 是正文。整行只有 `![](/绝对路径.png)` 或
  `[[img:/绝对路径.png]]` 的，会走工具栏 `图片` → `本地上传` 插在光标处；其余每行是一段。
  `cover` **必填**（原因见下）。
- **封面**：后台**没有**本地上传入口——封面槽的菜单只有 从正文选择 / 从图片库选择 /
  微信扫码上传 / 一键生成封面。服务端走 从图片库选择 → `上传文件` 把本地文件传进素材库，
  保持条目勾选，点 `下一步`，等 `编辑封面` 的 `确认` 由灰变亮再点，然后保存，
  **最后重开草稿把封面读回来**。
  - 这个弹窗是**文件名列表**不是缩略图墙，而且点击条目是**切换勾选**：上传完成后新条目
    已经是勾选状态，再点一次文件名反而取消勾选，`下一步` 变灰。真机就栽在这里
    （草稿 `100000245` 就是这样存成了没封面），所以现在代码先读勾选状态再决定点不点。
  - 编辑器里的封面预览在提交瞬间常常是 `0x0` 加 `url("")`，而空槽上那句
    「拖拽或选择封面」永远不消失——两者都不能当信号。所以 `cover_ok` 只认
    **重开后的草稿**（实测 235x100，背景是 `mmbiz.qpic.cn` 的图）。
- **`action=publish`**：点编辑器自己的 `发表` → 确认弹窗 → 管理员扫码 → 只有发表记录里
  出现**新 msgid** 才算 `verified`。图文这条路代码写了但**没提交验证过**（发表会产生公开
  内容，所以从没在这里真的按下）。

### `mp_create_tietu` 细节

- `images`：绝对路径，png/jpg/jpeg/gif/webp，单张 ≤10 MB（可用
  `WXMP_MAX_IMAGE_BYTES` 改）。**第一张图就是封面**。
- `description`：换行变成段落。超过 1000 字会在输入前截断。控制台的计数器以
  `desc_counter` 返回——它不是 1:1 的字数（输入 995 字含换行，实测显示 `807/1000`）。
- **上传走哪条路很关键。** 编辑器里有两个 file input：属于「图片库」的那个在这儿是**死
  的**——交给它文件不发请求、编辑器依旧空着。只有「本地上传」背后的 webuploader input
  才真的上传，传完会出现封面提示。上传菜单要在点了「选择或拖拽图片」之后才生成，所以流程
  是先点方块、再喂文件。万一 webuploader 不收，服务端会退到「从图片库选择」（附上素材库
  里最近的图，新的在前），并在 `upload.method` 里说明。
- 描述用 `insert_text` 逐字输入，**不走系统剪贴板**。实测 HTML 剪贴板风味会把中文搞成
  乱码。

## MCP 客户端配置

仓库里的 `mcp.entry.json` 是现成的 stdio 条目：

```json
{
  "wxmp": {
    "command": "python",
    "args": ["-m", "wxmp", "--transport", "stdio"],
    "env": { "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1" }
  }
}
```

`command` 换成你装依赖那个解释器的绝对路径，例如
`E:\path\to\wechatmp-mcp\.venv\Scripts\python.exe`。

改用 Streamable HTTP：

```powershell
wxmp --transport http --host 127.0.0.1 --port 8790 --path /mcp --token <secret>
```

`GET /mcp` 按设计返回 405（没有服务端主动推送流）；`POST` 接受 JSON-RPC 请求、通知和
批量。

## 环境变量

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `WXMP_PROFILE_DIR` | `./.state/profile` | 放登录态的 Playwright profile。机密。 |
| `WXMP_OUT_DIR` | `./out` | 截图目录：登录二维码、编辑器、发表证据、扫码页。 |
| `WXMP_BROWSER_CHANNEL` | `msedge` | 驱动哪个已安装浏览器（`msedge`、`chrome`）。留空则用自带 Chromium，需要 `playwright install chromium`。 |
| `WXMP_HEADLESS` | `0` | `1` 无窗口运行。不建议：扫码得有窗口。 |
| `WXMP_CDP_URL` | — | 挂到已经在跑的 Chrome（`http://127.0.0.1:9222`），不再自己启动。 |
| `WXMP_TIMEOUT_MS` | `30000` | 默认动作超时。 |
| `WXMP_LOGIN_TIMEOUT` | `180` | `mp_account_login` 默认等待时长。 |
| `WXMP_DEVICE_SCALE` | `1` | 设备像素比；`2` 让截图分辨率翻倍。 |
| `WXMP_VIEWPORT_W/H` | `1280` / `900` | 窗口尺寸。 |
| `WXMP_SLOW_MO` | `0` | 每个 Playwright 动作前等多少毫秒，方便人看。 |
| `WXMP_MAX_IMAGE_BYTES` | `10485760` | 单张图大小上限。 |
| `WXMP_HTTP_TOKEN` | — | HTTP 传输的 Bearer token。 |
| `WXMP_LOG_LEVEL` | `WARNING` | 日志级别；日志只进 stderr，绝不进 stdout。 |

## 安全模型

- **只能人工登录。** 服务端截图二维码、轮询跳转，从不处理密码、cookie 或 token 值。
- **token 一律打码。** 9 位控制台 token 只保留首位和末尾两位，包括错误回包里的 URL。
- **公开之前一定有人扫码。** 发表弹窗之后控制台会出现扫码页；服务端把它截图到 `out/`，
  等 `scan_wait_s`（默认 120 秒）让人扫，自己绝不点它。
- **不可撤销动作必须 `confirm=true`**：发表、删除，以及 `mp_create_tietu` /
  `mp_publish_material` 的 `action=publish`。不给确认就在**碰浏览器之前**拒绝，草稿原样不动。
- **默认只存草稿。** 建贴图或图文默认只存草稿；发表永远是单独的、显式的一步。
- **`verified` 只认发表记录，不认页面文字。** 只有发表记录里出现**新 msgid** 才报
  `verified=true`。
- **图文封面是被证明的，不是被假设的。** `cover_ok` 只有在重开草稿、看到封面渲染出真实
  `mmbiz.qpic.cn` 图片时才为 true；编辑器里还读着 `url("")` 的预览不算数。
- **证据落盘。** 每个改变状态的调用都写一张整页 PNG 到 `out/`，事后可以审计。
- **浏览器独占。** 每个进程一个 Playwright 会话；第二个请求排队等，而不是再开一个浏览器。

## 排障

| 现象 | 含义 |
| --- | --- |
| 之前登录过，`mp_status` 却说 `logged_in: false` | 它打开的 profile 不是握着会话的那个。看 `server_health` 里的 `settings.profile_dir`，把 `WXMP_PROFILE_DIR` 指过去。 |
| 发表调用返回 `verified: false` | 没扫完码、还在队列里，或者记录读得太早。先重跑 `mp_list_published` 再判失败。 |
| 发表调用返回 `needs_scan: true` | 这是正常路径。打开浏览器窗口扫码，然后重新读发表记录。 |
| `action=schedule` 返回 `scheduled_unverified` | 暂时就是如此：这次提交没有产生发表记录条目。依赖它之前先去控制台确认。 |
| 图片一直没进编辑器 | uploader input 没接受文件；回包里的 `upload` 块说明了试过哪种方式。页面上的弹窗（账号未认证、新设备验证）是常见原因。 |
| 图文回包里 `cover_ok: false` | 重开草稿没看到封面图。发表前请手动进草稿选一次封面——后台没封面不许发表。`cover.pick` / `cover.crop_confirm` 会说明是哪一步没落地。 |
| 报 `the 保存为草稿 button was not found` | 有封面对话框还盖在页面上，把点击吃掉了；`error_data.open_dialogs` 会写出它是哪个。现在代码会先关掉这些弹窗，所以再出现就意味着冒出了**新的**弹窗——把它的文案发我。 |
| 日志里出现 `Execution context was destroyed` | 控制台中途跳转或关了标签页。发表链路容错处理了它；证据仍然是发表记录。 |

## 测试

```powershell
python tests/selftest.py    # 121 条离线检查：协议、注册表、参数校验、
                            # 确认闸门、打码、URL 构造、流程辅助函数、
                            # 发布动作、发表记录解析、中英对照契约、
                            # 给调用方的限制文案、图文分段规则
python tests/ci_smoke.py    # 15 条，含真实 stdio 子进程握手
```

两套都离线：不要浏览器、不要网络、不要登录态。它们在 Linux 上也能跑，适合当 CI 闸门。

## 目录结构

```
src/wxmp/
  app.py         与传输无关的 Application：字节进，JSON 出
  protocol.py    JSON-RPC 2.0 / MCP 方法表（2024-11-05 … 2025-06-18）
  registry.py    工具装饰器、schema 校验、call_tool
  config.py      环境变量配置与控制台 URL
  security.py    确认闸门、图片校验、token 打码
  browser.py     Playwright 会话、持久化 profile、线程重绑定
  console.py     登录判定、二维码截图、token 提取
  tietu.py       贴图流程：上传、标题、描述、存稿、
                 发表 / 定时发表、等管理员扫码
  article.py     图文流程：标题、正文分段、正文插图、作者 / 摘要、
                 封面走图片库、存稿后重开草稿复核
  drafts.py      草稿箱：列表、打开、发表、删除
  records.py     发表记录：证明「真的发出去了」的只读来源
  tools/         九个 MCP 工具
  transports/    stdio + Streamable HTTP
tests/           selftest.py、ci_smoke.py
```

## 许可

MIT。这是对一个私有后台的非官方自动化，与腾讯无关、未获其背书，使用可能受平台条款约
束。请只对自己拥有的账号使用。