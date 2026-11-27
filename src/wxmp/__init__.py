# -*- coding: utf-8 -*-
"""wechatmp-mcp: an MCP server that drives the WeChat Official Account backend.

The server speaks MCP over stdio or Streamable HTTP and automates the real
mp.weixin.qq.com console with Playwright: it keeps one persistent browser
profile, logs in by QR scan once, then creates 贴图 (image messages), keeps them
as drafts and — only with an explicit confirm flag — publishes them now, schedules
them, or deletes them. 发表 itself is gated by an admin QR scan and lands
asynchronously, so a publish is only reported as verified once a new msgid shows
up in 发表记录.
"""

__version__ = "0.1.1"
SERVER_NAME = "wechatmp-mcp"

__all__ = ["__version__", "SERVER_NAME"]