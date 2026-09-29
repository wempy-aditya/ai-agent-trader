#!/usr/bin/env python3
"""Minimal Hermes-facing client for local AI-Trader paper mode.

Reads token from ~/.config/ai-trader/hermes-local.json (mode 600).
No live broker/exchange execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CONFIG = Path.home() / ".config/ai-trader/hermes-local.json"


def load_config() -> dict:
    if not CONFIG.exists():
        raise SystemExit(f"Missing credential file: {CONFIG}")
    if CONFIG.stat().st_mode & 0o077:
        raise SystemExit(f"Credential file permissions too broad: {CONFIG}")
    return json.loads(CONFIG.read_text())


def call(method: str, path: str, payload: dict | None = None) -> dict:
    config = load_config()
    url = config["base_url"].rstrip("/") + path
    headers = {"Authorization": f"Bearer {config['token']}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"AI-Trader API {exc.code}: {body}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("me")
    sub.add_parser("heartbeat")
    signal = sub.add_parser("paper-buy")
    signal.add_argument("--market", default="crypto")
    signal.add_argument("--symbol", default="BTC")
    signal.add_argument("--price", type=float, required=True)
    signal.add_argument("--quantity", type=float, required=True)
    args = parser.parse_args()

    if args.command == "me":
        result = call("GET", "/api/claw/agents/me")
    elif args.command == "heartbeat":
        result = call("POST", "/api/claw/agents/heartbeat")
    else:
        result = call("POST", "/api/signals/realtime", {
            "market": args.market,
            "action": "buy",
            "symbol": args.symbol,
            "price": args.price,
            "quantity": args.quantity,
            "content": "Hermes local paper client",
            "executed_at": "now",
        })
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
