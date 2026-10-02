"""Walk-forward sweep: tune on train, judge only on unseen bars.

In-sample results are worthless for a decision like this. Any parameter set can
look good on the bars it was chosen from, so the only number that counts is the
return of the parameters chosen on the first half, measured on the second half
which no tuning step ever touched.

The split is chronological, never random: shuffling bars would let the model see
its own future through neighbouring rows.
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

# Coarse on purpose. A fine grid would multiply the selection noise, and the
# point here is to learn whether a stable optimum exists at all, not to shave
# the last few basis points off a curve that is flat anyway.
RSI_OVERSOLD = (30.0, 34.0, 38.0, 42.0)
NEAR_LOW = (0.20, 0.28, 0.35, 0.45)
MAX_HOLD = (12, 24, 48)
SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)


def _evaluate(rows: list[dict[str, Any]], config: MRConfig) -> dict[str, Any]:
    """One configuration, measured the same way as every other one."""
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
        "random_avg_return_pct": round(random_avg, 4),
        "edge_over_random_pp": round(strategy["return_pct"] - random_avg, 4),
    }


def sweep(rows: list[dict[str, Any]], base: MRConfig) -> list[dict[str, Any]]:
    """Every parameter combination, scored on the rows given."""
    results: list[dict[str, Any]] = []
    for rsi in RSI_OVERSOLD:
        for near in NEAR_LOW:
            for hold in MAX_HOLD:
                cfg = replace(base, rsi_oversold=rsi, near_low_max=near, max_hold_bars=hold)
                row = _evaluate(rows, cfg)
                row.update({"rsi_oversold": rsi, "near_low_max": near, "max_hold_bars": hold})
                results.append(row)
    return results


def best_by(results: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Winner on a single metric. Ties break on drawdown, then on fewer trades."""
    return sorted(results, key=lambda r: (-r[key], r["max_drawdown_pct"], r["entries"]))[0]


def params_of(row: dict[str, Any]) -> MRConfig:
    return MRConfig(
        rsi_oversold=row["rsi_oversold"],
        near_low_max=row["near_low_max"],
        max_hold_bars=row["max_hold_bars"],
    )


def main() -> int:
    windows = [int(x) for x in sys.argv[1:] if not x.startswith("-")] or [5000]
    tf_arg = next((x for x in sys.argv[1:] if x.startswith("--timeframe=")), None)
    tf_minutes = TF_MINUTES[(tf_arg or "--timeframe=1h").split("=", 1)[1]]
    base = MRConfig()
    report: dict[str, object] = {"timeframe_minutes": tf_minutes, "split": "chronological 60/40",
                                 "grid": len(RSI_OVERSOLD) * len(NEAR_LOW) * len(MAX_HOLD)}

    for window in windows:
        rows = resample(load_candles(window), tf_minutes)
        if len(rows) < base.warmup + 200:
            print(f"=== window {window}: only {len(rows)} bars, skipping ===")
            continue

        cut = int(len(rows) * 0.6)
        train, test = rows[:cut], rows[cut:]

        train_rows = sweep(train, base)
        train_best = best_by(train_rows, "return_pct")
        test_of_best = _evaluate(test, params_of(train_best))

        # Control on the same unseen bars: the default parameters, never tuned.
        test_default = _evaluate(test, base)
        # And the oracle: the best possible parameters on the test set, which
        # tuning must not be allowed to use. It measures the size of the
        # selection effect, not a strategy anyone could have picked.
        test_oracle = best_by(sweep(test, base), "return_pct")
        test_bh = simulate_buy_and_hold(test, ReplayConfig())

        print(f"=== window {window}  tf {tf_minutes}m  {len(rows)} bars  "
              f"train {len(train)} / test {len(test)} ===")
        print(f"grid searched: {len(train_rows)} combinations on train only")
        print()
        print("train winner:")
        print(f"  RSI<={train_best['rsi_oversold']:.0f}  range<={train_best['near_low_max']:.2f}  "
              f"hold {train_best['max_hold_bars']}  ->  train {train_best['return_pct']:+.3f}%")
        print()
        print("on the unseen half (this is the only result that counts):")
        rows_out = [
            ("tuned on train", test_of_best),
            ("default params", test_default),
            ("oracle on test", test_oracle),
        ]
        print(f"{'config':18s} {'return':>9s} {'maxDD':>8s} {'entries':>8s} {'wins':>5s} {'vs random':>11s}")
        for name, row in rows_out:
            print(f"{name:18s} {row['return_pct']:+8.3f}% {row['max_drawdown_pct']:7.3f}% "
                  f"{row['entries']:8d} {row['wins']:5d} {row['edge_over_random_pp']:+10.3f}pp")
        print(f"{'buy_and_hold':18s} {test_bh['return_pct']:+8.3f}% "
              f"{test_bh['max_drawdown_pct']:7.3f}%")
        print()

        tuned = test_of_best["return_pct"]
        default = test_default["return_pct"]
        oracle = test_oracle["return_pct"]
        bh = test_bh["return_pct"]
        selection_gap = oracle - tuned
        print(f"tuned beats default on unseen data: {tuned > default}")
        print(f"tuned beats buy-and-hold on unseen data: {tuned > bh}")
        print(f"oracle would have returned {oracle:+.3f}%, so tuning gave up "
              f"{selection_gap:+.3f}pp against perfect hindsight")
        print()

        report[str(window)] = {
            "bars_total": len(rows), "bars_train": len(train), "bars_test": len(test),
            "train_winner": train_best,
            "test_tuned": test_of_best,
            "test_default": test_default,
            "test_oracle": test_oracle,
            "test_buy_and_hold": {"return_pct": test_bh["return_pct"],
                                  "max_drawdown_pct": test_bh["max_drawdown_pct"]},
            "tuned_beats_default": tuned > default,
            "tuned_beats_buy_and_hold": tuned > bh,
            "selection_gap_pp": round(selection_gap, 4),
            "verdict": "edge survives" if tuned > bh and tuned > default else "no edge",
        }

    out = Path(f"data/walk_forward_{tf_minutes}m.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())