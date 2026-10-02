"""Aggregate 1h candles into a higher timeframe.

The point is to test whether the 1h strategy failed because of the timeframe,
not because of the entry or exit rules. Resampling keeps the rule code identical
so the only variable that changes is bar size.

Leakage rule: a 4h bar is built only from hours that closed before its own
timestamp. The incomplete trailing group is dropped rather than padded, because
a partial bar would let the last hour leak into a "closed" 4h bar.
"""
from __future__ import annotations

from typing import Any

TF_MINUTES = {"1h": 60, "4h": 240, "12h": 720, "1d": 1440}

HOUR_MS = 3_600_000


def resample(candles: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Aggregate 1h candles into `minutes` bars. Only whole groups are kept."""
    if minutes not in set(TF_MINUTES.values()):
        raise ValueError(f"unsupported timeframe minutes: {minutes}")

    rows = sorted(candles, key=lambda c: c["timestamp"])
    if not rows:
        return []
    if minutes == 60:
        return [dict(row, timeframe_minutes=60) for row in rows]

    span = minutes * 60 * 1000
    per_group = minutes // 60
    base = rows[0]["timestamp"]
    out: list[dict[str, Any]] = []
    group: list[dict[str, Any]] = []
    key: int | None = None

    for row in rows:
        bucket = (row["timestamp"] - base) // span
        if key is None:
            key = bucket
        if bucket != key:
            if len(group) == per_group and key is not None:
                out.append(_merge(group, key, minutes))
            group = []
            key = bucket
        group.append(row)

    # A complete trailing group is a closed bar and must be kept. An
    # incomplete one is dropped: a partial bar is not a closed bar.
    if len(group) == per_group and key is not None:
        out.append(_merge(group, key, minutes))
    return out


def _merge(group: list[dict[str, Any]], key: int, minutes: int) -> dict[str, Any]:
    return {
        "timestamp": group[0]["timestamp"],
        "open": group[0]["open"],
        "high": max(r["high"] for r in group),
        "low": min(r["low"] for r in group),
        "close": group[-1]["close"],
        "timeframe_minutes": minutes,
        "source_count": len(group),
    }