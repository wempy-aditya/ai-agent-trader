#!/usr/bin/env python3
"""Local LLM agent trading loop with read-only paper dashboard.

Default: execute=false (LLM proposes, nothing is ordered).
--execute is allowed ONLY with --i-understand-this-orders-paper and is bounded.
Live trading is not implemented anywhere in this repo.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from agent_loop import AgentTradingLoop
from dashboard import DashboardState
from dashboard_server import serve
from hyperliquid_provider import HyperliquidBTC1hProvider
from ledger_adapter import LocalPaperLedger
from llm_agent import LocalLLMAgent

CONFIG = Path.home() / ".config/ai-trader/hermes-local.json"
DATA = Path("data")


def load_ledger_client() -> LocalPaperLedger:
    config = json.loads(CONFIG.read_text())
    return LocalPaperLedger(base_url=config["base_url"], token=config["token"])


def fetch_snapshot(ledger: LocalPaperLedger, provider: HyperliquidBTC1hProvider, now_ms: int) -> dict:
    positions = ledger_positions(ledger)
    cash = positions.get("cash")
    rows = positions.get("positions", [])
    mark = None
    try:
        mark = float(provider.latest_closed(now_ms)["close"])
    except Exception:
        mark = None
    exposure = 0.0
    compact = []
    for row in rows:
        qty = float(row.get("quantity") or 0.0)
        if mark is not None:
            exposure += qty * mark
        compact.append({
            "id": row.get("id"),
            "symbol": row.get("symbol"),
            "quantity": qty,
            "entry_price": row.get("entry_price"),
            "ledger_current_price": row.get("current_price"),
            "ledger_pnl": row.get("pnl"),
        })
    return {"cash": cash, "positions": compact, "mark": mark, "exposure": round(exposure, 6)}


def ledger_positions(ledger: LocalPaperLedger) -> dict:
    request = Request(ledger.base_url + "/api/positions", headers={"Authorization": f"Bearer {ledger.token}"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--i-understand-this-orders-paper", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--hold", action="store_true", help="keep dashboard alive after cycles finish")
    args = parser.parse_args()

    if args.execute and not args.i_understand_this_orders_paper:
        print(json.dumps({"stop_reason": "execute_requires_explicit_flag", "execute": True}))
        return 2

    DATA.mkdir(exist_ok=True)
    state = DashboardState(DATA / "agent_dashboard_state.json")
    provider = HyperliquidBTC1hProvider()
    agent = LocalLLMAgent(model=args.model)

    if not agent.available():
        state.update(status="llm_unavailable", model=args.model, execute=bool(args.execute))
        print(json.dumps({"stop_reason": "llm_unavailable", "model": args.model}))
        return 3

    ledger = None
    ledger_error = None
    try:
        ledger = load_ledger_client()
    except Exception as exc:
        ledger_error = type(exc).__name__
        if args.execute:
            state.update(status="ledger_unavailable")
            state.add_error(f"ledger: {ledger_error}")
            print(json.dumps({"stop_reason": "ledger_unavailable", "detail": ledger_error}))
            return 4

    loop = AgentTradingLoop(
        provider=provider,
        agent=agent,
        audit_path=DATA / "agent_live.audit.jsonl",
        state_path=DATA / "agent_live.state.json",
        evidence_path=DATA / "agent_live.jsonl",
        ledger=ledger.execute if (ledger and args.execute) else None,
        execute=args.execute,
    )

    if not args.no_dashboard:
        threading.Thread(target=serve, args=(DATA / "agent_dashboard_state.json", "127.0.0.1", args.port), daemon=True).start()
        state.update(status="running", model=args.model, execute=bool(args.execute))

    stop_reason = "max_cycles"
    for index in range(args.cycles):
        now_ms = int(time.time() * 1000)
        try:
            snapshot = fetch_snapshot(ledger, provider, now_ms) if ledger else {"cash": None, "positions": [], "mark": None, "exposure": 0.0}
        except Exception as exc:
            state.add_error(f"ledger: {type(exc).__name__}")
            snapshot = {"cash": None, "positions": [], "mark": None, "exposure": 0.0}
        state.set_ledger(snapshot["cash"], snapshot["positions"], snapshot["mark"], snapshot["exposure"])
        result = loop.run_cycle(
            now_ms=now_ms,
            cash=float(snapshot["cash"] or 0.0) or 1000.0,
            current_exposure=float(snapshot["exposure"] or 0.0),
            open_position_quantity=sum(p["quantity"] for p in snapshot["positions"]),
        )
        payload = result.as_dict()
        payload["cycle"] = index + 1
        state.add_cycle(payload)
        print(json.dumps(payload, sort_keys=True), flush=True)
        if not result.accepted and result.reason in {"invalid_candle", "unfinished_candle", "duplicate_candle"}:
            continue
        if index + 1 < args.cycles:
            time.sleep(args.interval_seconds)

    state.update(status="stopped")
    print(json.dumps({
        "stop_reason": stop_reason,
        "cycles": state.data["cycles"],
        "accepted": state.data["accepted"],
        "executed": state.data["executed"],
        "invalid": state.data["invalid"],
        "execute": bool(args.execute),
        "evidence": str(DATA / "agent_live.jsonl"),
        "audit": str(DATA / "agent_live.audit.jsonl"),
    }, indent=2, sort_keys=True))
    if not args.no_dashboard:
        print(json.dumps({"dashboard": f"http://127.0.0.1:{args.port}/"}), flush=True)
    if args.hold and not args.no_dashboard:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            state.update(status="stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
