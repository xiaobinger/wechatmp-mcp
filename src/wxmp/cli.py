# -*- coding: utf-8 -*-
"""Command line entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .app import Application


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wxmp",
        description="wechatmp-mcp: WeChat Official Account 贴图 / draft automation over MCP",
    )
    p.add_argument("--transport", choices=("stdio", "http"),
                   default=os.environ.get("WXMP_TRANSPORT", "stdio"),
                   help="stdio (default) or http (Streamable HTTP)")
    p.add_argument("--host", default=os.environ.get("WXMP_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=_env_int("WXMP_PORT", 8790))
    p.add_argument("--path", default=os.environ.get("WXMP_PATH", "/mcp"))
    p.add_argument("--token", default=os.environ.get("WXMP_HTTP_TOKEN"),
                   help="optional bearer token for the http transport")
    p.add_argument("--log-level", default=os.environ.get("WXMP_LOG_LEVEL", "WARNING"))
    p.add_argument("--version", action="version", version=f"wechatmp-mcp {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.WARNING),
        stream=sys.stderr,
        format="[wxmp] %(levelname)s %(message)s",
    )
    app = Application()
    if args.transport == "stdio":
        from .transports.stdio import run_stdio
        return run_stdio(app)
    from .transports.http import run_http
    return run_http(app, host=args.host, port=args.port,
                    path=args.path, token=args.token)


if __name__ == "__main__":
    raise SystemExit(main())