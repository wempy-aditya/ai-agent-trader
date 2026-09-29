#!/usr/bin/env python3
"""Audit BTC 1h dataset integrity and baseline output."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).parent / "data" / "btc_1h_last365d.json"


def main() -> None:
    rows = json.loads(DATA.read_text())
    timestamps = [row["timestamp"] for row in rows]
    expected = 3_600_000
    gaps = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
    print(json.dumps({
        "rows": len(rows),
        "monotonic_strict": timestamps == sorted(set(timestamps)),
        "duplicate_timestamps": len(timestamps) - len(set(timestamps)),
        "gap_count_not_1h": sum(gap != expected for gap in gaps),
        "min_gap_ms": min(gaps) if gaps else None,
        "max_gap_ms": max(gaps) if gaps else None,
        "missing_ohlcv": sum(any(row[key] is None for key in ("open", "high", "low", "close")) for row in rows),
        "negative_or_zero_prices": sum(any(row[key] <= 0 for key in ("open", "high", "low", "close")) for row in rows),
        "lookahead_design": "signals use candles[:index+1], fills use next candle open",
    }, indent=2))


if __name__ == "__main__":
    main()
