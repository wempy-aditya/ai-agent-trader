#!/usr/bin/env python3
"""Poll the agent heartbeat and report what the platform is actually offering.

The point of this is to find out whether anyone is publishing signals worth
copying. An empty heartbeat is the single most important piece of information
here: it means the network has no activity, and copy-trading it cannot produce
anything regardless of how good our local code is.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "ai-trader" / "platform-token.json"
USER_AGENT = "wempys-ai-trader-client/1.0 (+local agent registration)"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"missing {CONFIG_PATH}; run register_agent.py first")
        raise SystemExit(1)
    mode = CONFIG_PATH.stat().st_mode & 0o777
    if mode != 0o600:
        print(f"refusing to use a world-readable token file (mode {oct(mode)})")
        raise SystemExit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def call(path: str, cfg: dict, payload: dict | None = None) -> tuple[int, object]:
    url = cfg["base_url"] + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("User-Agent", USER_AGENT)
    # Live docs use Authorization: Bearer. The X-Claw-Token header mentioned in
    # the local repo docs is stale and returns 401 Invalid token.
    request.add_header("Authorization", f"Bearer {cfg['token']}")
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                # An HTML error page or empty body must not crash the probe.
                return response.status, raw[:300]
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text[:300]
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def show(label: str, path: str, cfg: dict, payload: dict | None = None) -> object:
    status, body = call(path, cfg, payload)
    print(f"--- {label}: {path} -> HTTP {status}")
    if isinstance(body, dict):
        for key, value in body.items():
            if isinstance(value, list):
                print(f"    {key}: {len(value)} items")
                for item in value[:3]:
                    text = json.dumps(item, ensure_ascii=False)
                    print(f"       {text[:220]}")
            else:
                print(f"    {key}: {json.dumps(value, ensure_ascii=False)[:220]}")
    else:
        print(f"    {str(body)[:300]}")
    return body


def main() -> int:
    cfg = load_config()
    print(f"agent id : {cfg.get('agent_id')}")
    print(f"email    : {cfg.get('email')}")
    print(f"token    : (hidden, mode 600)")
    print()

    agent_id = cfg.get("agent_id")
    print("=== heartbeat ===")
    heartbeat = show("heartbeat", "/api/claw/agents/heartbeat", cfg,
                     {"agent_id": agent_id, "status": "alive"})

    if isinstance(heartbeat, dict):
        messages = heartbeat.get("messages") or []
        tasks = heartbeat.get("tasks") or []
        print()
        print(f"  messages: {len(messages)}   tasks: {len(tasks)}")
        if not messages and not tasks:
            print("  EMPTY: nobody is publishing anything to this agent right now.")

    for label, path, payload in [
        ("signals", "/api/claw/signals", None),
        ("marketplace", "/api/claw/marketplace", None),
        ("leaderboard", "/api/claw/leaderboard", None),
        ("providers", "/api/claw/providers", None),
        ("strategies", "/api/claw/strategies", None),
        ("discussions", "/api/claw/discussions", None),
    ]:
        print()
        show(label, path, cfg, payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
