# -*- coding: utf-8 -*-
"""Streamable HTTP transport (MCP 2025-03-26+): single /mcp endpoint.

POST  /mcp    JSON-RPC request/notification/batch -> application/json or SSE
GET   /mcp    405 (server-initiated SSE streams are not offered)
DELETE /mcp   terminate a session
OPTIONS       CORS preflight

Only the Python standard library is used. Note that the browser tools share one
Playwright session, so concurrent tool calls are serialised by the server itself
— a second request waits instead of opening a second browser.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

LOG = logging.getLogger("wxmp.http")


def _compact(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except (ValueError, TypeError):
        return text.replace("\n", "")


class _State:
    def __init__(self, app, path: str, token: str | None):
        self.app = app
        self.path = path
        self.token = token
        self.sessions: dict[str, dict] = {}
        self.lock = threading.Lock()


def _handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "wechatmp-mcp"

        def log_message(self, fmt, *args):
            LOG.debug("%s - %s", self.address_string(), fmt % args)

        # -- helpers ------------------------------------------------------
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization, Mcp-Session-Id, Mcp-Protocol-Version, Accept")
            self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id")

        def _auth(self) -> bool:
            if not state.token:
                return True
            return (self.headers.get("Authorization") or "") == "Bearer " + state.token

        def _send(self, code: int, body: bytes = b"",
                  ctype: str = "application/json", extra: dict | None = None):
            self.send_response(code)
            if body:
                self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _unauthorized(self):
            self._send(401, b'{"error":"unauthorized"}',
                       extra={"WWW-Authenticate": "Bearer"})

        def _read_body(self):
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if n <= 0 or n > 8 * 1024 * 1024:
                return None
            return self.rfile.read(n)

        # -- verbs --------------------------------------------------------
        def do_OPTIONS(self):
            self._send(204)

        def do_GET(self):
            if not self._auth():
                return self._unauthorized()
            # A server that does not offer a standalone stream MUST return 405.
            self._send(405, b'{"error":"GET stream not offered; use POST /mcp"}',
                       extra={"Allow": "POST, DELETE, OPTIONS"})

        def do_DELETE(self):
            if not self._auth():
                return self._unauthorized()
            sid = self.headers.get("Mcp-Session-Id")
            if sid:
                with state.lock:
                    state.sessions.pop(sid, None)
            self._send(204)

        def do_POST(self):
            if urlsplit(self.path).path.rstrip("/") != state.path.rstrip("/"):
                return self._send(404, b'{"error":"not found"}')
            if not self._auth():
                return self._unauthorized()
            body = self._read_body()
            if body is None:
                return self._send(400, b'{"error":"invalid Content-Length"}')

            extra: dict = {}
            sid = self.headers.get("Mcp-Session-Id")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            initializing = (isinstance(parsed, dict)
                            and parsed.get("method") == "initialize")
            if initializing:
                sid = uuid.uuid4().hex
                with state.lock:
                    state.sessions[sid] = {
                        "protocol": (parsed.get("params") or {}).get("protocolVersion")}
                extra["Mcp-Session-Id"] = sid
            elif sid and sid not in state.sessions:
                return self._send(404, b'{"error":"unknown session"}')

            reply = state.app.process(body)
            if reply is None:
                # Notification: 202 Accepted with an empty body.
                return self._send(202, extra=extra)

            accept = self.headers.get("Accept", "")
            if "text/event-stream" in accept and "application/json" not in accept:
                payload = ("event: message\ndata: " + _compact(reply) + "\n\n").encode("utf-8")
                return self._send(200, payload, "text/event-stream", extra)
            return self._send(200, reply.encode("utf-8"), "application/json", extra)

    return Handler


def run_http(app, *, host: str = "127.0.0.1", port: int = 8790,
             path: str = "/mcp", token: str | None = None) -> int:
    state = _State(app, path, token)
    server = ThreadingHTTPServer((host, port), _handler(state))
    server.daemon_threads = True
    LOG.warning("Streamable HTTP listening on http://%s:%s%s (token=%s)",
                host, port, path, "set" if token else "off")
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            from ..browser import shutdown
            shutdown()
        except Exception:  # noqa: BLE001
            pass
    return 0