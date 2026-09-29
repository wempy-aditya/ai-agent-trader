"""Bounded six-cycle paper execution observer; local ledger only."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from fresh_observation import FreshObservationRunner
from hyperliquid_provider import HyperliquidBTC1hProvider
from ledger_adapter import LocalPaperLedger

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "paper_execute_6cycle.jsonl"
AUDIT = ROOT / "data" / "paper_execute_6cycle.audit.jsonl"
STATE = ROOT / "data" / "paper_execute_6cycle.state.json"
CONFIG = Path.home() / ".config/ai-trader/hermes-local.json"
MAX_CYCLES = 6
CADENCE_SECONDS = 3600


def config() -> dict:
    return json.loads(CONFIG.read_text())


def positions(cfg: dict) -> dict:
    req = Request(cfg["base_url"].rstrip("/") + "/api/positions", headers={"Authorization": "Bearer " + cfg["token"]})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def main() -> None:
    cfg = config()
    account = positions(cfg)
    print(json.dumps({"preflight": account, "execute": True, "max_cycles": MAX_CYCLES}, sort_keys=True), flush=True)
    ledger = LocalPaperLedger(cfg["base_url"], cfg["token"])
    runner = FreshObservationRunner(HyperliquidBTC1hProvider(), AUDIT, STATE, execute=True, ledger=ledger.execute)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    accepted = 0
    while accepted < MAX_CYCLES:
        account = positions(cfg)
        pos = account.get("positions", [])
        mark = HyperliquidBTC1hProvider().latest_closed(int(time.time() * 1000))["close"]
        exposure = sum(float(p["quantity"]) * mark for p in pos if p.get("symbol") == "BTC")
        quantity = sum(float(p["quantity"]) for p in pos if p.get("symbol") == "BTC")
        result = runner.run_cycle(int(time.time() * 1000), cash=float(account["cash"]), current_exposure=exposure, open_position_quantity=quantity)
        result.update({"cycle": accepted + 1, "cash": account["cash"], "mark": mark, "exposure": exposure, "position_quantity": quantity, "observed_at_ms": int(time.time() * 1000)})
        OUT.open("a", encoding="utf-8").write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps(result, sort_keys=True), flush=True)
        if not result["accepted"] and result.get("reason") in {"kill_switch", "execute_requires_ledger"}:
            print(json.dumps({"stop_reason": result["reason"], "cycles": accepted}, sort_keys=True), flush=True)
            return
        if result["accepted"]:
            accepted += 1
        if accepted >= MAX_CYCLES:
            break
        time.sleep(CADENCE_SECONDS)
    print(json.dumps({"cycles": accepted, "execute": True, "stop_reason": "max_cycles", "audit_path": str(AUDIT), "evidence_path": str(OUT)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
