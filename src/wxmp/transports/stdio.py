# -*- coding: utf-8 -*-
"""stdio transport: newline-delimited JSON-RPC over stdin/stdout.

stdout is reserved exclusively for protocol messages and is written as raw
UTF-8 bytes so Windows console code pages can never corrupt the stream.
"""
from __future__ import annotations

import logging
import sys

LOG = logging.getLogger("wxmp.stdio")


def run_stdio(app) -> int:
    stdin = getattr(sys.stdin, "buffer", sys.stdin)
    stdout = getattr(sys.stdout, "buffer", sys.stdout)
    LOG.info("stdio transport ready")
    try:
        for line in stdin:
            if isinstance(line, str):
                raw = line.encode("utf-8")
            else:
                raw = line
            if not raw.strip():
                continue
            try:
                reply = app.process(raw)
            except Exception:  # noqa: BLE001 - one bad message must not kill the server
                LOG.exception("failed to process message")
                continue
            if reply is None:
                continue
            stdout.write(reply.encode("utf-8") + b"\n")
            stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        try:
            from ..browser import shutdown
            shutdown()
        except Exception:  # noqa: BLE001
            pass
    return 0