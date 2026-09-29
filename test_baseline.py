from baseline import (
    BacktestConfig,
    Candle,
    calculate_position_size,
    detect_signal,
    estimate_round_trip_cost,
)


def test_ema_crossover_generates_buy_on_closed_candle():
    closes = [120 - i for i in range(50)] + [70 + i * 3 for i in range(17)]
    candles = [
        Candle(timestamp=i, open=close, high=close + 1, low=close - 1, close=close)
        for i, close in enumerate(closes)
    ]
    assert detect_signal(candles, has_position=False) == "buy"


def test_position_size_uses_risk_budget_and_exposure_cap():
    config = BacktestConfig()
    assert calculate_position_size(entry_price=50_000, config=config) == 0.01


def test_round_trip_cost_includes_fee_slippage_and_spread():
    config = BacktestConfig()
    cost = estimate_round_trip_cost(trade_value=500, config=config)
    assert cost == 1.75


def test_existing_position_does_not_generate_new_buy():
    candles = [
        Candle(timestamp=i, open=100, high=101, low=99, close=100)
        for i in range(60)
    ]
    assert detect_signal(candles, has_position=True) == "hold"
