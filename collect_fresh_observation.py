"""Bounded 24-cycle fresh BTC 1h dry-run collector. No execution."""
from __future__ import annotations

import json
import time
from pathlib import Path

from fresh_observation import FreshObservationRunner
from hyperliquid_provider import HyperliquidBTC1hProvider

MAX_CYCLES = 24
CADENCE_SECONDS = 3600
OUT = Path(__file__).with_name("data") / "fresh_observation_24h.jsonl"
STATE = Path(__file__).with_name("data") / "fresh_observation_24h.state.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    runner = FreshObservationRunner(HyperliquidBTC1hProvider(), OUT, STATE)
    accepted = 0
    skipped = 0
    while accepted < MAX_CYCLES:
        now_ms = int(time.time() * 1000)
        result = runner.run_cycle(now_ms)
        result["observed_at_ms"] = now_ms
        result["cycle"] = accepted + 1
        with OUT.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, sort_keys=True) + "\n")
        if result["accepted"]:
            accepted += 1
            print(json.dumps(result, sort_keys=True), flush=True)
            if accepted >= MAX_CYCLES:
                break
        else:
            skipped += 1
        time.sleep(CADENCE_SECONDS)
    print(json.dumps({"cycles": accepted, "skipped": skipped, "execute": False, "stop_reason": "max_cycles", "audit_path": str(OUT)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
