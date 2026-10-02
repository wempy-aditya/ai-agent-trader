"""Re-test the chosen parameters on every disjoint half of the data.

One good out-of-sample half can be luck. The chosen parameter set is applied
unchanged to each consecutive slice in turn, so the question becomes: does the
same rules make money on slices that had no part in picking them?

No tuning happens here. The parameters are frozen at the values the walk-forward
selected, precisely so this pass cannot quietly become a second optimisation.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from mean_reversion import MRConfig, simulate_mean_reversion, simulate_random_timing
from replay import ReplayConfig, simulate_buy_and_hold
from run_replay import load_candles
from timeframe import TF_MINUTES, resample

SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)
SLICE = 1000


def evaluate(rows: list[dict[str, Any]], config: MRConfig) -> dict[str, Any]:
    strategy = simulate_mean_reversion(rows, config)
    controls = [simulate_random_timing(rows, config, seed=s) for s in SEEDS]
    random_avg = sum(c["return_pct"] for c in controls) / len(controls)
    return {
        "return_pct": strategy["return_pct"],
        "max_drawdown_pct": strategy["max_drawdown_pct"],
        "entries": strategy["entries"],
        "wins": strategy["wins"],
        "losses": strategy["losses"],
        "costs_paid": strategy["costs_paid"],
        "max_exposure_used": strategy["max_exposure_used"],
        "random_avg_return_pct": round(random_avg, 4),
        "edge_over_random_pp": round(strategy["return_pct"] - random_avg, 4),
    }


def main() -> int:
    windows = [int(x) for x in sys.argv[1:] if not x.startswith("-")] or [5000]
    tf_arg = next((x for x in sys.argv[1:] if x.startswith("--timeframe=")), None)
    tf_minutes = TF_MINUTES[(tf_arg or "--timeframe=1h").split("=", 1)[1]]
    tuned = replace(MRConfig(), rsi_oversold=30.0, near_low_max=0.20, max_hold_bars=48)
    base = MRConfig()
    report: dict[str, object] = {"timeframe_minutes": tf_minutes, "slice": SLICE,
                                 "frozen_params": {"rsi_oversold": 30.0, "near_low_max": 0.20,
                                                   "max_hold_bars": 48}}

    for window in windows:
        rows = resample(load_candles(window), tf_minutes)
        print(f"=== window {window}  tf {tf_minutes}m  {len(rows)} bars  frozen params, no tuning ===")
        print(f"{'slice':>12s} {'bars':>6s} {'MR':>9s} {'default':>9s} {'random':>9s} "
              f"{'B&H':>9s} {'MR-DD':>7s} {'B&H-DD':>7s} {'entries':>8s} {'win':>5s}")
        slices: list[dict[str, Any]] = []
        wins_vs_bh = 0
        wins_vs_default = 0
        wins_vs_random = 0
        scored = 0

        for start in range(0, len(rows) - SLICE + 1, SLICE):
            chunk = rows[start: start + SLICE]
            if len(chunk) < base.warmup + 50:
                continue
            mr = evaluate(chunk, tuned)
            default = evaluate(chunk, base)
            bh = simulate_buy_and_hold(chunk, ReplayConfig())
            if mr["entries"] == 0:
                continue
            scored += 1
            wins_vs_bh += mr["return_pct"] > bh["return_pct"]
            wins_vs_default += mr["return_pct"] > default["return_pct"]
            wins_vs_random += mr["return_pct"] > mr["random_avg_return_pct"]
            slices.append({
                "start": start, "bars": len(chunk),
                "tuned": mr, "default": default,
                "buy_and_hold": {"return_pct": bh["return_pct"],
                                 "max_drawdown_pct": bh["max_drawdown_pct"]},
            })
            print(f"{f'[{start}:{start + SLICE}]':>12s} {len(chunk):6d} "
                  f"{mr['return_pct']:+8.3f}% {default['return_pct']:+8.3f}% "
                  f"{mr['random_avg_return_pct']:+8.3f}% {bh['return_pct']:+8.3f}% "
                  f"{mr['max_drawdown_pct']:6.2f}% {bh['max_drawdown_pct']:6.2f}% "
                  f"{mr['entries']:8d} {mr['wins']:5d}")

        if not scored:
            print("no slice produced a trade; nothing to score")
            continue

        print()
        print(f"slices that traded: {scored}")
        print(f"beat buy-and-hold: {wins_vs_bh}/{scored} ({100 * wins_vs_bh / scored:.0f}%)")
        print(f"beat default params: {wins_vs_default}/{scored} ({100 * wins_vs_default / scored:.0f}%)")
        print(f"beat random timing: {wins_vs_random}/{scored} ({100 * wins_vs_random / scored:.0f}%)")
        totals = {
            "slices_scored": scored,
            "beat_buy_and_hold": wins_vs_bh,
            "beat_default": wins_vs_default,
            "beat_random": wins_vs_random,
            "tuned_avg_return_pct": round(sum(s["tuned"]["return_pct"] for s in slices) / scored, 4),
            "default_avg_return_pct": round(sum(s["default"]["return_pct"] for s in slices) / scored, 4),
            "random_avg_return_pct": round(sum(s["tuned"]["random_avg_return_pct"] for s in slices) / scored, 4),
            "buy_and_hold_avg_return_pct": round(sum(s["buy_and_hold"]["return_pct"] for s in slices) / scored, 4),
        }
        # A coin flip is 50%. Anything near that is not a signal.
        edge_real = wins_vs_bh > scored * 0.6
        totals["verdict"] = "consistent edge vs buy-and-hold" if edge_real else "no consistent edge vs buy-and-hold"
        print(f"verdict: {totals['verdict']}")
        print()
        report[str(window)] = {"totals": totals, "slices": slices}

    out = Path(f"data/slice_test_{tf_minutes}m.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())