"""Run mean reversion on real BTC bars, next to the controls that matter.

Two controls sit beside it: buy-and-hold (does sitting in the market pay?) and
random timing with the same size, cost and exit rule (does the dip rule add
anything, or would any trade schedule have done the same?).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mean_reversion import MRConfig, simulate_mean_reversion, simulate_random_timing
from replay import ReplayConfig, simulate_buy_and_hold
from run_replay import load_candles
from timeframe import TF_MINUTES, resample

SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


def main() -> int:
    windows = [int(x) for x in sys.argv[1:] if not x.startswith("-")] or [1000, 2000, 5000]
    tf_arg = next((x for x in sys.argv[1:] if x.startswith("--timeframe=")), None)
    tf_minutes = TF_MINUTES[(tf_arg or "--timeframe=1h").split("=", 1)[1]]
    cfg = MRConfig()
    all_rows: dict[str, object] = {"timeframe_minutes": tf_minutes, "position_value": cfg.position_value}

    for window in windows:
        rows = resample(load_candles(window), tf_minutes)
        if len(rows) < cfg.warmup + 10:
            print(f"=== window {window} tf {tf_minutes}m: only {len(rows)} bars, skipping ===")
            continue

        bh = simulate_buy_and_hold(rows, ReplayConfig())
        mr = simulate_mean_reversion(rows, cfg)
        controls = [simulate_random_timing(rows, cfg, seed=s) for s in SEEDS]
        avg = sum(c["return_pct"] for c in controls) / len(controls)
        worst = min(c["return_pct"] for c in controls)
        best = max(c["return_pct"] for c in controls)

        print(f"=== window {window}  tf {tf_minutes}m  {len(rows)} bars  position {cfg.position_value:.0f} ===")
        print(f"{'strategy':22s} {'return':>9s} {'maxDD':>8s} {'entries':>8s} {'wins':>5s} {'loss':>5s}")
        print(f"{'buy_and_hold':22s} {bh['return_pct']:+8.3f}% {bh['max_drawdown_pct']:7.3f}% "
              f"{'-':>8s} {bh.get('wins', '-'):>5} {bh.get('losses', '-'):>5}")
        print(f"{'mean_reversion':22s} {mr['return_pct']:+8.3f}% {mr['max_drawdown_pct']:7.3f}% "
              f"{mr['entries']:8d} {mr['wins']:5d} {mr['losses']:5d}")
        print(f"{'random_timing avg':22s} {avg:+8.3f}% {'':8s} {'-':>8s} {'-':>5s} {'-':>5}   "
              f"(min {worst:+.3f}% max {best:+.3f}%)")
        verdict = "beats random" if mr["return_pct"] > avg else "loses to random"
        print(f"verdict: mean_reversion {verdict}, "
              f"{'beats' if mr['return_pct'] > bh['return_pct'] else 'loses to'} buy-and-hold")
        print()

        all_rows[str(window)] = {
            "bars": len(rows),
            "buy_and_hold": bh,
            "mean_reversion": mr,
            "random_timing": controls,
            "random_timing_avg_return_pct": round(avg, 4),
            "random_timing_min_return_pct": worst,
            "random_timing_max_return_pct": best,
        }

    # One file per timeframe: a 4h run must not overwrite the 1h evidence.
    out = Path(f"data/mean_reversion_{tf_minutes}m.json")
    out.write_text(json.dumps(all_rows, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())