from timeframe import resample, TF_MINUTES


def hourly(count=48, start=1_700_000_000_000, price=100.0):
    return [
        {
            "timestamp": start + i * 3_600_000,
            "open": price + i,
            "high": price + i + 2.0,
            "low": price + i - 2.0,
            "close": price + i + 1.0,
        }
        for i in range(count)
    ]


def test_resample_4h_gives_twelve_bars_from_forty_eight_hours():
    bars = resample(hourly(48), 240)
    assert len(bars) == 12


def test_resample_4h_open_is_first_hour_open():
    src = hourly(4, price=100.0)
    out = resample(src, 240)
    assert out[0]["open"] == 100.0


def test_resample_4h_close_is_last_hour_close():
    src = hourly(4, price=100.0)
    out = resample(src, 240)
    assert out[0]["close"] == 104.0


def test_resample_4h_high_is_the_maximum_of_the_group():
    src = hourly(4, price=100.0)
    out = resample(src, 240)
    assert out[0]["high"] == 105.0  # hour 3 high = 100 + 3 + 2


def test_resample_4h_low_is_the_minimum_of_the_group():
    src = hourly(4, price=100.0)
    out = resample(src, 240)
    assert out[0]["low"] == 98.0  # hour 0 low = 100 - 2


def test_resample_4h_timestamp_is_the_first_hour_timestamp():
    src = hourly(12, start=1_700_000_000_000)
    out = resample(src, 240)
    assert out[0]["timestamp"] == 1_700_000_000_000
    assert out[1]["timestamp"] == 1_700_000_000_000 + 4 * 3_600_000


def test_resample_drops_incomplete_trailing_group():
    src = hourly(46)  # 11 full groups of 4 hours, 2 hours left over
    out = resample(src, 240)
    assert len(out) == 11


def test_resample_keeps_only_whole_groups_without_lookahead():
    # A 4h bar built from hours 0-3 must not see hour 4.
    src = hourly(12, price=100.0)
    out = resample(src, 240)
    assert len(out) == 3
    assert out[0]["open"] == 100.0 and out[0]["close"] == 104.0
    assert out[1]["open"] == 104.0  # hour 4 open, not hour 0
    assert out[1]["close"] == 108.0  # hour 7 close


def test_resample_1h_returns_input_unchanged():
    src = hourly(10)
    out = resample(src, 60)
    assert [r["timestamp"] for r in out] == [r["timestamp"] for r in src]
    assert [r["close"] for r in out] == [r["close"] for r in src]


def test_resample_rejects_unsupported_timeframes():
    for minutes in (0, -60, 7, 90):
        try:
            resample(hourly(10), minutes)
        except ValueError as exc:
            assert "timeframe" in str(exc).lower()
        else:
            raise AssertionError(f"expected ValueError for {minutes}")


def test_resample_sorts_unordered_input_first():
    src = hourly(12)
    shuffled = [src[3], src[0], src[1], src[2], src[7], src[4], src[5], src[6],
                src[11], src[8], src[9], src[10]]
    out = resample(shuffled, 240)
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 104.0
    assert out[1]["open"] == 104.0


def test_resample_empty_input_returns_empty():
    assert resample([], 240) == []


def test_tf_minutes_is_recorded_on_every_bar():
    out = resample(hourly(12), 240)
    assert all(bar["timeframe_minutes"] == 240 for bar in out)
    assert TF_MINUTES["4h"] == 240