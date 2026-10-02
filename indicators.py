"""Technical indicators for the agent's market context.

Everything here is deterministic and derived only from already-closed candles.
Nothing in this module can produce an order; it exists so the LLM stops
guessing and starts reading numbers.

Every function returns None rather than guessing when history is too short, so
a missing value is visible to the caller instead of silently becoming zero.
"""
from __future__ import annotations

from typing import Any


def ema_value(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    current = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for value in values[period:]:
        current = (value * alpha) + (current * (1 - alpha))
    return current


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    average_gain = gains / period
    average_loss = losses / period
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def true_ranges(candles: list[dict[str, Any]]) -> list[float]:
    ranges: list[float] = []
    for index, candle in enumerate(candles):
        high = float(candle["high"])
        low = float(candle["low"])
        if index == 0:
            ranges.append(high - low)
            continue
        previous_close = float(candles[index - 1]["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return ranges


def atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges = true_ranges(candles)
    current = sum(ranges[:period]) / period
    for value in ranges[period:]:
        current = ((current * (period - 1)) + value) / period
    return current


def returns_pct(values: list[float], window: int) -> float | None:
    if len(values) < window + 1 or values[-window - 1] == 0:
        return None
    start = values[-window - 1]
    return ((values[-1] - start) / start) * 100.0


def range_position(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    low = min(values)
    high = max(values)
    if high == low:
        return 0.0
    return (values[-1] - low) / (high - low)


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def compute_indicators(candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the market context handed to the LLM. Keys are stable."""
    closes = [float(c["close"]) for c in candles]
    latest = closes[-1] if closes else 0.0
    window24 = closes[-24:]
    atr14 = atr(candles, 14)
    fast = ema_value(closes, 20)
    slow = ema_value(closes, 50)

    if slow and slow != 0 and fast is not None:
        spread_pct: float | None = ((fast - slow) / slow) * 100.0
    else:
        spread_pct = None

    return {
        "closed_candles": len(candles),
        "close": _round(latest),
        "ema20": _round(fast),
        "ema50": _round(slow),
        "ema_spread_pct": _round(spread_pct, 3),
        "rsi14": _round(rsi(closes, 14), 1),
        "atr14": _round(atr14),
        "atr_pct": _round((atr14 / latest) * 100.0, 3) if atr14 and latest else None,
        "return_1": _round(returns_pct(closes, 1), 3),
        "return_4": _round(returns_pct(closes, 4), 3),
        "return_24": _round(returns_pct(closes, 24), 3),
        "high_24": _round(max(window24) if window24 else None),
        "low_24": _round(min(window24) if window24 else None),
        "range_position_24": _round(range_position(window24), 3),
        "closes_above_ema20": None if fast is None else latest > fast,
        "closes_above_ema50": None if slow is None else latest > slow,
    }