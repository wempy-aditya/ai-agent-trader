"""P5.3 live-candle disagreement soak, execute=false by default."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from p5_soak import SoakRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--cadence-seconds", type=int, default=3600)
    parser.add_argument("--actions", default="hold,buy,hold,buy,hold,buy,hold,buy,hold,buy,hold,buy")
    parser.add_argument("--evidence", default="data/p5_soak.jsonl")
    parser.add_argument("--audit", default="data/p5_soak.audit.jsonl")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    from hyperliquid_provider import HyperliquidBTC1hProvider

    provider = HyperliquidBTC1hProvider()
    now_ms = int(time.time() * 1000)
    rows = provider.recent_closed(now_ms, count=200)
    actions = [a.strip() for a in args.actions.split(",") if a.strip()][: args.cycles]

    candles = [
        {"timestamp": r["timestamp"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]}
        for r in rows
    ]

    # Align each cycle to a distinct recent closed candle so the baseline window grows.
    start = max(0, len(candles) - len(actions) - 100)
    window = candles[start : start + len(actions) + 101]

    evidence = Path(args.evidence)
    audit = Path(args.audit)

    if args.execute:
        print(json.dumps({"stop_reason": "execute_requires_explicit_ledger", "execute": True}))
        return 2

    state_path = Path(audit).with_suffix(".state.json")
    for path in (evidence, audit, state_path, Path(str(audit) + ".state.json")):
        if path.exists():
            path.unlink()

    runner = SoakRunner(candles=window, agent_actions=actions, evidence_path=evidence, audit_path=audit, execute=False)
    report = runner.run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
