from baseline import BacktestConfig, Candle
from signal_observation import build_observation


def test_observation_uses_only_closed_candles_and_emits_hold_or_proposal():
    candles = [Candle(i * 3_600_000, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(60)]
    result = build_observation(candles, now_ms=60 * 3_600_000, config=BacktestConfig())
    assert result.signal in {"buy", "hold"}
    assert result.candle_timestamp == candles[-1].timestamp
    assert result.used_candle_count == 60


def test_observation_does_not_emit_buy_without_crossover():
    candles = [Candle(i * 3_600_000, 100, 101, 99, 100) for i in range(60)]
    result = build_observation(candles, now_ms=60 * 3_600_000, config=BacktestConfig())
    assert result.signal == "hold"
    assert result.proposal is None
