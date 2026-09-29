#!/usr/bin/env python3
"""Run BTC 1h baseline backtest on pinned local dataset."""
from __future__ import annotations

import json
from pathlib import Path

from backtest import run_backtest
from baseline import BacktestConfig, Candle

DATA = Path(__file__).parent / "data" / "btc_1h_last365d.json"


def main() -> None:
    rows = json.loads(DATA.read_text())
    candles = [Candle(row["timestamp"], row["open"], row["high"], row["low"], row["close"]) for row in rows]
    split = int(len(candles) * 0.7)
    for name, subset in (("in_sample_70pct", candles[:split]), ("out_of_sample_30pct", candles[split:]), ("full", candles)):
        result = run_backtest(subset, BacktestConfig())
        print(json.dumps({"dataset": name, "result": result.__dict__}, sort_keys=True))


if __name__ == "__main__":
    main()
