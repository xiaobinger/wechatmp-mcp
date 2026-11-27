# -*- coding: utf-8 -*-
"""Portable smoke test (CI, Linux + Windows, Python 3.10+).

No browser, no network and no console session: it exercises the protocol, the
registry, the confirmation gates and the stdio transport.

    python tests/ci_smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from wxmp.app import Application  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f"  {detail}" if detail else ""))


def call(app: Application, name: str, args: dict) -> tuple[dict, bool]:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": args}}
    reply = app.process(json.dumps(msg, ensure_ascii=False))
    assert reply, f"{name} returned no reply"
    payload = json.loads(reply)
    assert "error" not in payload, f"{name}: {payload['error']}"
    result = payload["result"]
    return result["structuredContent"], result["isError"]


def stdio_handshake() -> bool:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.setdefault("WXMP_OUT_DIR", str(ROOT / "out"))
    proc = subprocess.run(
        [sys.executable, "-m", "wxmp", "--transport", "stdio"],
        input="\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18",
                                   "capabilities": {},
                                   "clientInfo": {"name": "ci", "version": "1"}}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=120, env=env,
        cwd=str(ROOT),
    )
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if len(lines) != 2:
        print("    stdout:", (proc.stdout or "")[:400])
        print("    stderr:", (proc.stderr or "")[:400])
        return False
    first, second = json.loads(lines[0]), json.loads(lines[1])
    names = sorted(t["name"] for t in second["result"]["tools"])
    return (first["result"]["serverInfo"]["name"] == "wechatmp-mcp"
            and "mp_create_tietu" in names
            and "mp_publish_material" in names and len(names) == 9)


def main() -> int:
    app = Application()

    print("protocol")
    for version in ("2025-06-18", "2025-03-26", "2024-11-05"):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": version, "capabilities": {},
                          "clientInfo": {"name": "ci-smoke", "version": "1"}}}
        res = json.loads(app.process(json.dumps(msg)))["result"]
        check(f"initialize {version}", res["protocolVersion"] == version)
    check("unknown method", json.loads(app.process(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "nope"})))["error"]["code"] == -32601)
    check("parse error", json.loads(app.process("{"))["error"]["code"] == -32700)
    check("notification has no reply", app.process(json.dumps(
        {"jsonrpc": "2.0", "method": "notifications/initialized"})) is None)

    print("tools")
    health, is_error = call(app, "server_health", {})
    check("server_health", not is_error and health["tool_count"] == 9,
          health.get("error"))
    check("nine tools", len(health["tools"]) == 9, health["tools"])

    print("safety")
    payload, err = call(app, "mp_publish_draft", {"appmsgid": 1})
    check("publish needs confirm", err and "confirm" in payload["error"].lower(),
          payload.get("error"))
    payload, err = call(app, "mp_delete_draft", {"appmsgid": 1})
    check("delete needs confirm", err, payload.get("error"))
    tmp = Path(tempfile.mkdtemp(prefix="wxmp-ci-"))
    img = tmp / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    payload, err = call(app, "mp_create_tietu",
                        {"images": [str(img)], "title": "t", "action": "publish"})
    check("create+publish needs confirm", err, payload.get("error"))
    payload, err = call(app, "mp_publish_material",
                        {"kind": "tietu", "title": "t", "cover": str(img),
                         "action": "publish"})
    check("material publish needs confirm", err, payload.get("error"))
    payload, err = call(app, "mp_publish_material", {"kind": "article", "title": "t"})
    check("an article needs a cover", err, payload.get("error"))
    payload, err = call(app, "mp_create_tietu",
                        {"images": [str(tmp / "gone.png")], "title": "t"})
    check("missing image is rejected", err, payload.get("error"))

    print("transport")
    check("stdio handshake", stdio_handshake())

    print()
    print(f"passed {len(PASS)}  failed {len(FAIL)}")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
