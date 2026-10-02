"""Test the regime hypothesis on real bars before building a filter on it.

Claim under test: mean reversion wins in sideways markets and loses in trends.

If that is false the filter is dead and no amount of parameter tuning will
help. The script buckets every entry the mean-reversion gate produced by the
regime that was live at the time, then reports forward return per bucket. The
filter's value is the difference between those buckets, and the benchmark is
whether buying and holding the same bars beats it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from indicators import compute_indicators
from mean_reversion import MRConfig, mean_reversion_criteria
from regime import RegimeConfig, adx, classify
from run_replay import load_candles
from timeframe import TF_MINUTES, resample

FORWARD_BARS = 12


def main() -> int:
    windows = [int(x) for x in sys.argv[1:] if not x.startswith("-")] or [5000]
    tf_arg = next((x for x in sys.argv[1:] if x.startswith("--timeframe=")), None)
    tf_minutes = TF_MINUTES[(tf_arg or "--timeframe=1h").split("=", 1)[1]]
    mr = MRConfig()
    rg = RegimeConfig()
    report: dict[str, object] = {"timeframe_minutes": tf_minutes, "forward_bars": FORWARD_BARS}

    for window in windows:
        rows = resample(load_candles(window), tf_minutes)
        buckets: dict[str, list[float]] = {"trend": [], "sideways": [], "unknown": []}
        regime_counts: dict[str, int] = {"trend": 0, "sideways": 0, "unknown": 0}
        total = 0.0

        for i in range(max(mr.warmup, rg.warmup), len(rows) - FORWARD_BARS):
            ctx = compute_indicators(rows[max(0, i - mr.lookback + 1): i + 1])
            if not all(mean_reversion_criteria(ctx).values()):
                continue
            total += 1

            adx_value = adx(rows[max(0, i - rg.lookback + 1): i + 1], rg.adx_period)
            label = classify({"adx14": adx_value}, rg)
            regime_counts[label] = regime_counts.get(label, 0) + 1

            entry = rows[i]["close"]
            forward = rows[i + FORWARD_BARS]["close"]
            buckets[label].append((forward / entry - 1) * 100)

        print(f"=== window {window}  tf {tf_minutes}m  {len(rows)} bars  "
              f"forward {FORWARD_BARS} bars ===")
        print(f"MR gate fired {total} times; regime split: "
              f"trend {regime_counts['trend']}  sideways {regime_counts['sideways']}  "
              f"unknown {regime_counts['unknown']}")
        print(f"{'regime':10s} {'entries':>8s} {'avg fwd':>9s} {'median':>9s} {'best':>8s} {'worst':>8s}")

        summary: dict[str, object] = {"regime_counts": regime_counts, "total_entries": total}
        for label in ("sideways", "trend", "unknown"):
            values = sorted(buckets[label])
            if not values:
                print(f"{label:10s} {0:8d}        (no entries)")
                summary[label] = None
                continue
            n = len(values)
            median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
            avg = sum(values) / n
            print(f"{label:10s} {n:8d} {avg:+8.3f}% {median:+8.3f}% {values[-1]:+7.2f}% {values[0]:+7.2f}%")
            summary[label] = {
                "entries": n, "avg_forward_pct": round(avg, 4),
                "median_forward_pct": round(median, 4),
                "min_forward_pct": round(values[0], 4), "max_forward_pct": round(values[-1], 4),
            }

        side = summary.get("sideways")
        trend = summary.get("trend")
        if isinstance(side, dict) and isinstance(trend, dict):
            gap = side["avg_forward_pct"] - trend["avg_forward_pct"]
            print(f"\nsideways minus trend: {gap:+.3f}pp average forward return")
            print("hypothesis supported" if gap > 0 else "HYPOTHESIS FALSIFIED")
            summary["sideways_minus_trend_pp"] = round(gap, 4)
            summary["hypothesis_supported"] = gap > 0
        print()
        report[str(window)] = summary

    out = Path(f"data/regime_study_{tf_minutes}m.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())