#!/usr/bin/env python3
"""Historical replay: LLM agent vs deterministic baseline vs buy-and-hold.

Read-only. No ledger, no orders, no live path. Costs are charged on both sides.

Usage:
    PYTHONPATH=. python run_replay.py --backend remote --limit 200
    PYTHONPATH=. python run_replay.py --backend remote --limit 200 --dry-agent
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from entry_agent import EntryModeAgent
from llm_agent import BACKEND_REMOTE, build_agent
from replay import ReplayConfig, replay_candles, simulate_baseline, simulate_buy_and_hold

DATA = Path("data")
DATASET = DATA / "btc_1h_last365d.json"
DEFAULT_EVIDENCE = DATA / "replay_report.json"


def load_candles(limit: int) -> list[dict[str, Any]]:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = payload["candles"] if isinstance(payload, dict) else payload
    rows = [r for r in rows if isinstance(r, dict) and r.get("close") is not None]
    rows.sort(key=lambda r: r["timestamp"])
    if limit > 0 and limit < len(rows):
        rows = rows[-limit:]
    return rows


class DryAgent:
    """Answers from a deterministic rule, costs nothing, calls no API.

    Used for a control run: whatever the LLM claims, this measures whether the
    harness itself can find an edge. If the dry agent matches the LLM, the LLM
    is adding nothing.
    """

    model_id = "dry-baseline-control"

    def available(self) -> bool:
        return True

    def propose(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None, equity: float = 1000.0) -> dict[str, Any]:
        ctx = context or {}
        spread = ctx.get("ema_spread_pct")
        rsi14 = ctx.get("rsi14")
        buy = baseline_signal == "buy" and (spread is None or spread > 0) and (rsi14 is None or rsi14 < 70)
        return {
            "schema_version": "p5.v1",
            "signal_id": f"dry-{candle_timestamp}",
            "candle_timestamp": candle_timestamp,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": "buy" if buy else "hold",
            "quantity": 0.0002 if buy else 0.0,
            "reference_price": close if buy else 0.0,
            "confidence": 0.5 if buy else 0.3,
            "reason_codes": ["dry_control"],
            "invalid_conditions": [],
            "baseline_signal": baseline_signal,
            "model_id": self.model_id,
        }


class GateAgent(EntryModeAgent):
    """Deterministic entry-aware agent. No LLM, no API.

    Answers from the entry gate alone: buy when every criterion holds, sell when
    the position is open and the exit rule fires. This is the floor the LLM has to
    beat, and it costs nothing to measure.
    """

    model_id = "gate-only-control"

    def __init__(self):
        super().__init__(model_id=self.model_id)

    def propose(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None, equity: float = 1000.0, has_position: bool = False, entry_price: float | None = None) -> dict[str, Any]:
        if has_position:
            # Holding is the default. Selling every bar would churn the fees away.
            action = "sell" if self.should_force_exit(self.build_exit_criteria(context, True, entry_price)) else "hold"
        elif all(self.build_criteria(context).values()):
            action = "buy"
        else:
            action = "hold"
        return {
            "schema_version": "p5.v1",
            "signal_id": f"gate-{candle_timestamp}",
            "candle_timestamp": candle_timestamp,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": action,
            "quantity": 0.0002 if action == "buy" else 0.0,
            "reference_price": close if action == "buy" else 0.0,
            "confidence": 0.6 if action != "hold" else 0.3,
            "reason_codes": ["gate_control"],
            "invalid_conditions": [],
            "baseline_signal": baseline_signal,
            "model_id": self.model_id,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["ollama", BACKEND_REMOTE, "dry", "gate"], default="dry")
    parser.add_argument("--entry-mode", action="store_true", help="wrap the backend in the deterministic entry gate")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--config", default="")
    parser.add_argument("--limit", type=int, default=200, help="how many trailing candles to replay")
    parser.add_argument("--warmup", type=int, default=51)
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between API calls")
    args = parser.parse_args()

    candles = load_candles(args.limit)
    if len(candles) < args.warmup + 2:
        print(json.dumps({"stop_reason": "not_enough_candles", "loaded": len(candles)}))
        return 1

    config = ReplayConfig(initial_capital=args.capital, warmup=args.warmup)

    if args.backend == "dry":
        agent: Any = DryAgent()
    elif args.backend == "gate":
        agent = GateAgent()
    else:
        try:
            agent = build_agent(args.backend, args.model, args.config or None)
        except Exception as exc:
            print(json.dumps({"stop_reason": "llm_config_invalid", "detail": str(exc)}))
            return 3
        if not agent.available():
            print(json.dumps({"stop_reason": "llm_unavailable", "backend": args.backend}))
            return 3
        if args.pause:
            original = agent.propose

            def throttled(**kwargs: Any) -> dict[str, Any]:
                time.sleep(args.pause)
                return original(**kwargs)

            agent.propose = throttled  # type: ignore[method-assign]

    if args.entry_mode:
        if hasattr(agent, "build_criteria"):
            print(json.dumps({"stop_reason": "backend_already_entry_aware"}))
            return 3
        backend = agent
        agent = EntryModeAgent(
            model_id=f"{getattr(backend, 'model_id', args.model)}-entry",
            complete=backend.complete,
        )

    started = time.time()
    baseline = simulate_baseline(candles, config)
    hold = simulate_buy_and_hold(candles, config)
    agent_result = replay_candles(candles, agent, config)

    report = {
        "generated_at_ms": int(time.time() * 1000),
        "dataset": str(DATASET),
        "candles": len(candles),
        "window_start": candles[0]["timestamp"],
        "window_end": candles[-1]["timestamp"],
        "price_start": candles[0]["close"],
        "price_end": candles[-1]["close"],
        "backend": args.backend,
        "model": getattr(agent, "model_id", args.model),
        "capital": args.capital,
        "elapsed_seconds": round(time.time() - started, 1),
        "buy_and_hold": hold,
        "baseline_ema": baseline,
        "agent": agent_result,
    }

    path = Path(args.evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())