from indicators import compute_indicators, rsi, atr, ema_value, returns_pct, range_position


def candles(closes, highs=None, lows=None):
    out = []
    base = 1_700_000_000_000
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    for i, close in enumerate(closes):
        out.append({
            "timestamp": base + i * 3_600_000,
            "open": close,
            "high": highs[i],
            "low": lows[i],
            "close": close,
        })
    return out


def test_ema_of_flat_series_equals_the_level():
    assert ema_value([100.0] * 30, 20) == 100.0


def test_ema_of_rising_series_is_below_last_value():
    values = [float(i) for i in range(1, 40)]
    result = ema_value(values, 20)
    assert result < values[-1]


def test_rsi_is_100_when_every_move_is_up():
    assert rsi([float(i) for i in range(1, 30)]) == 100.0


def test_rsi_is_zero_when_every_move_is_down():
    assert rsi([float(i) for i in range(29, 0, -1)]) == 0.0


def test_rsi_is_neutral_for_flat_market():
    value = rsi([100.0] * 30)
    assert 45.0 <= value <= 55.0


def test_rsi_needs_enough_history():
    assert rsi([100.0, 101.0]) is None


def test_atr_is_positive_for_real_candles():
    # ATR(14) needs 15 candles: the first bar has no previous close.
    closes = [100.0 + (i % 5) * 2 for i in range(20)]
    data = candles(closes)
    value = atr(data, 14)
    assert value is not None and value > 0


def test_atr_is_none_without_enough_candles():
    assert atr(candles([100.0, 101.0] * 5), 14) is None


def test_returns_pct_computes_window_change():
    values = [100.0, 101.0, 103.0, 102.0]
    # window=2 means the start is values[-3] = 101, so 101 -> 102.
    assert round(returns_pct(values, 2), 4) == round((102.0 - 101.0) / 101.0 * 100.0, 4)


def test_returns_pct_needs_longer_history():
    assert returns_pct([100.0, 101.0], 2) is None


def test_returns_pct_window_one_is_last_bar_change():
    values = [100.0, 150.0]
    assert returns_pct(values, 1) == 50.0


def test_range_position_is_zero_at_the_low_and_one_at_the_high():
    low = [100.0] * 10
    assert range_position(low) == 0.0
    high = [100.0] * 9 + [120.0]
    assert range_position(high) == 1.0


def test_range_position_is_halfway_in_the_middle():
    values = [100.0] * 9 + [110.0]
    assert range_position(values) == 1.0


def test_compute_indicators_returns_expected_keys():
    closes = [float(100 + i) for i in range(60)]
    data = candles(closes)
    result = compute_indicators(data)
    for key in ("close", "ema20", "ema50", "rsi14", "atr14", "atr_pct",
                "return_1", "return_4", "return_24", "range_position_24",
                "high_24", "low_24", "closed_candles"):
        assert key in result, key


def test_compute_indicators_handles_short_history():
    result = compute_indicators(candles([100.0, 101.0, 102.0]))
    assert result["close"] == 102.0
    assert result["ema20"] is None
    assert result["rsi14"] is None


def test_indicator_values_are_json_safe():
    closes = [100.0 + (i % 7) for i in range(80)]
    result = compute_indicators(candles(closes))
    import json
    json.dumps(result)  # must not raise