"""Build baseline observations from fully closed 1h candles only."""
from __future__ import annotations

from dataclasses import dataclass

from baseline import BacktestConfig, Candle, calculate_position_size, detect_signal
from risk import TradeProposal


@dataclass(frozen=True)
class SignalObservation:
    signal: str
    candle_timestamp: int | str
    used_candle_count: int
    proposal: TradeProposal | None


def build_observation(candles: list[Candle], now_ms: int, config: BacktestConfig) -> SignalObservation:
    if not candles:
        raise ValueError("at least one candle required")
    closed = [candle for candle in candles if int(candle.timestamp) + 3_600_000 <= now_ms]
    latest = closed[-1] if closed else candles[0]
    signal = detect_signal(closed, has_position=False, fast_period=config.ema_fast, slow_period=config.ema_slow) if len(closed) >= config.ema_slow + 1 else "hold"
    proposal = None
    if signal == "buy":
        quantity = calculate_position_size(latest.close, config)
        proposal = TradeProposal(
            signal_id=f"ema-{latest.timestamp}",
            action="buy",
            symbol="BTC",
            price=latest.close,
            quantity=quantity,
        )
    return SignalObservation(signal, latest.timestamp, len(closed), proposal)
