"""Classify each bar as trending or sideways, then check the hypothesis.

The claim under test is specific and falsifiable: mean reversion should win
during sideways markets and lose during trends. If the data says otherwise the
regime filter is dead and parameter tuning is pointless, so this module measures
the hypothesis before anything is built on top of it.

Classification uses only closed bars at or before the current one, so the
regime label available at decision time is never the label that includes the
future.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from indicators import compute_indicators


@dataclass(frozen=True)
class RegimeConfig:
    adx_period: int = 14
    trend_adx_min: float = 22.0
    sideways_adx_max: float = 22.0
    lookback: int = 100
    warmup: int = 120


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def directional_movement(prev_high: float, prev_low: float,
                         high: float, low: float) -> tuple[float, float]:
    up = high - prev_high
    down = prev_low - low
    if up > down and up > 0:
        return up, 0.0
    if down > up and down > 0:
        return 0.0, down
    return 0.0, 0.0


def adx(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    """Wilder ADX. None when there is not enough history to be meaningful."""
    if len(rows) < period * 2 + 2:
        return None

    trs: list[float] = []
    plus: list[float] = []
    minus: list[float] = []
    for prev, cur in zip(rows, rows[1:]):
        trs.append(true_range(prev["close"], cur["high"], cur["low"]))
        up, down = directional_movement(prev["high"], prev["low"], cur["high"], cur["low"])
        plus.append(up)
        minus.append(down)

    smooth_tr = sum(trs[:period])
    smooth_plus = sum(plus[:period])
    smooth_minus = sum(minus[:period])

    dx_values: list[float] = []
    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - smooth_tr / period + trs[i]
        smooth_plus = smooth_plus - smooth_plus / period + plus[i]
        smooth_minus = smooth_minus - smooth_minus / period + minus[i]
        if smooth_tr <= 0:
            continue
        plus_di = 100.0 * smooth_plus / smooth_tr
        minus_di = 100.0 * smooth_minus / smooth_tr
        total = plus_di + minus_di
        if total <= 0:
            continue
        dx_values.append(100.0 * abs(plus_di - minus_di) / total)

    if len(dx_values) < period:
        return None
    return sum(dx_values[-period:]) / period


def classify(context: dict[str, Any] | None, config: RegimeConfig | None = None) -> str:
    """Return 'trend', 'sideways' or 'unknown'. Unknown is never tradable."""
    cfg = config or RegimeConfig()
    adx14 = context.get("adx14") if context else None
    if not isinstance(adx14, (int, float)):
        return "unknown"
    if adx14 >= cfg.trend_adx_min:
        return "trend"
    if adx14 <= cfg.sideways_adx_max:
        return "sideways"
    return "unknown"


def regime_series(rows: list[dict[str, Any]], config: RegimeConfig | None = None) -> list[str]:
    """Regime label per bar, computed from closed bars only."""
    cfg = config or RegimeConfig()
    labels: list[str] = ["unknown"] * len(rows)
    for i in range(len(rows)):
        if i < cfg.warmup:
            continue
        window = rows[max(0, i - cfg.lookback + 1): i + 1]
        value = adx(window, cfg.adx_period)
        if value is None:
            continue
        labels[i] = classify({"adx14": value}, cfg)
    return labels


def efficiency_ratio(closes: list[float], period: int = 20) -> float | None:
    """Kaufman efficiency ratio: net move over total path travelled.

    1.0 means a straight line (pure trend), near 0 means it went nowhere.
    Independent of ADX, so it cross-checks the classifier instead of
    restating it.
    """
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1):]
    path = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    if path <= 0:
        return None
    return abs(window[-1] - window[0]) / path