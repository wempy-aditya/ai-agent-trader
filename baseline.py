"""Deterministic BTC 1h EMA baseline for paper/backtest experiments."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candle:
    timestamp: int | str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 1_000.0
    risk_fraction: float = 0.01
    max_daily_loss: float = 30.0
    max_exposure: float = 500.0
    stop_loss_fraction: float = 0.02
    fee_per_side: float = 0.001
    slippage_per_side: float = 0.0005
    spread_round_trip: float = 0.0005
    ema_fast: int = 20
    ema_slow: int = 50


def ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(values[:period]) / period)
    alpha = 2 / (period + 1)
    for value in values[period:]:
        result.append((value * alpha) + (result[-1] * (1 - alpha)))
    return result


def detect_signal(candles: list[Candle], has_position: bool, fast_period: int = 20, slow_period: int = 50) -> str:
    if len(candles) < slow_period + 1:
        return "hold"
    closes = [c.close for c in candles]
    fast = ema(closes, fast_period)
    slow = ema(closes, slow_period)
    previous_fast, current_fast = fast[-2], fast[-1]
    previous_slow, current_slow = slow[-2], slow[-1]
    if None in (previous_fast, current_fast, previous_slow, current_slow):
        return "hold"
    if has_position and current_fast < current_slow:
        return "sell"
    if not has_position and previous_fast <= previous_slow and current_fast > current_slow:
        return "buy"
    return "hold"


def calculate_position_size(entry_price: float, config: BacktestConfig = BacktestConfig()) -> float:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    risk_budget = config.initial_capital * config.risk_fraction
    stop_distance = entry_price * config.stop_loss_fraction
    raw_quantity = risk_budget / stop_distance
    exposure_quantity = config.max_exposure / entry_price
    return min(raw_quantity, exposure_quantity)


def estimate_round_trip_cost(trade_value: float, config: BacktestConfig = BacktestConfig()) -> float:
    if trade_value < 0:
        raise ValueError("trade_value must not be negative")
    return trade_value * (
        (2 * config.fee_per_side)
        + (2 * config.slippage_per_side)
        + config.spread_round_trip
    )
