#!/usr/bin/env python3
"""Register the local agent on ai4trade.ai and store the token safely.

The password is generated here and written straight to a mode-600 config file.
It is never printed to stdout and never passed on a command line, so it cannot
leak into shell history, a process listing, or a log file.

Docs in the repo are stale: the host is ai4trade.ai (there is no api. DNS
record) and selfRegister now requires a password field.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://ai4trade.ai"
CONFIG_DIR = Path.home() / ".config" / "ai-trader"
CONFIG_PATH = CONFIG_DIR / "platform-token.json"

USER_AGENT = "wempys-ai-trader-client/1.0 (+local agent registration)"


def post(path: str, payload: dict, token: str | None = None) -> tuple[int, dict | str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    if token:
        request.add_header("X-Claw-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body_text)
        except json.JSONDecodeError:
            return exc.code, body_text[:400]


def get(path: str, token: str | None = None) -> tuple[int, dict | str]:
    request = urllib.request.Request(BASE + path, method="GET")
    request.add_header("User-Agent", USER_AGENT)
    if token:
        request.add_header("X-Claw-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body_text)
        except json.JSONDecodeError:
            return exc.code, body_text[:400]


def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else ""
    if not email or "@" not in email:
        print("usage: register_agent.py <email>")
        return 2

    password = secrets.token_urlsafe(24)
    status, payload = post("/api/claw/agents/selfRegister", {
        "name": "WempysAgent",
        "email": email,
        "password": password,
    })

    print(f"selfRegister -> HTTP {status}")
    if status != 200 or not isinstance(payload, dict):
        print("registration failed, response:")
        print(json.dumps(payload, indent=2)[:800] if isinstance(payload, dict) else payload)
        return 1

    token = payload.get("token")
    if not token:
        print("no token in response:")
        print(json.dumps(payload, indent=2)[:800])
        return 1

    # Never print the token or the password.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({
        "base_url": BASE,
        "email": email,
        "agent_id": payload.get("botUserId") or payload.get("agent_id"),
        "token": token,
        "password": password,
        "points": payload.get("points"),
        "registered_at_ms": int(__import__("time").time() * 1000),
    }, indent=2), encoding="utf-8")
    os.chmod(CONFIG_PATH, 0o600)

    print(f"token stored  : {CONFIG_PATH}")
    print(f"file mode     : {oct(CONFIG_PATH.stat().st_mode & 0o777)}")
    print(f"agent id      : {payload.get('botUserId') or payload.get('agent_id')}")
    print(f"points        : {payload.get('points')}")
    print("token value   : (not printed, stored only in the mode-600 file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
