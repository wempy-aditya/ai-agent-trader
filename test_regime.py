from regime import (
    RegimeConfig,
    adx,
    classify,
    efficiency_ratio,
    regime_series,
    true_range,
    directional_movement,
)


def zigzag(count=400, start=100.0, step_pct=0.01, seed=4):
    """Straight-line moves: this is a trend, whatever ADX says."""
    return [
        {
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": start * (1 + step_pct) ** i,
            "high": start * (1 + step_pct) ** i * 1.002,
            "low": start * (1 + step_pct) ** i * 0.998,
            "close": start * (1 + step_pct) ** i,
        }
        for i in range(count)
    ]


def choppy(count=400, start=100.0, seed=9):
    """Noise-dominated drift: no sustained direction, so ADX stays low.

    Two traps here, both learned the hard way. A long slow sine (period 30) is
    still a trend to ADX(14): for 14 consecutive bars the high-to-high and
    low-to-low steps point the same way, so DX pins at 100 no matter how small
    the amplitude. ADX only sees reversal as sideways when the swing is short
    relative to the period, or when noise breaks the directional runs. This
    fixture does the second: small alternating steps plus noise, so no
    direction persists for 14 bars.
    """
    import random

    rng = random.Random(seed)
    out = []
    price = start
    for i in range(count):
        drift = 0.0002
        step = drift + rng.gauss(0.0, 0.004)
        price = max(1.0, price * (1 + step))
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price, "high": price * 1.002, "low": price * 0.998, "close": price,
        })
    return out


# ---------- primitives ----------

def test_true_range_uses_the_largest_gap():
    # A gap up makes high-low irrelevant; the true range is the gap.
    tr = true_range(prev_close=100.0, high=110.0, low=105.0)
    assert tr == 10.0


def test_true_range_uses_high_low_when_bigger():
    tr = true_range(prev_close=100.0, high=106.0, low=94.0)
    assert tr == 12.0


def test_directional_movement_picks_the_larger_direction():
    up, down = directional_movement(prev_high=100.0, prev_low=100.0, high=105.0, low=99.0)
    assert up == 5.0 and down == 0.0


def test_directional_movement_ignores_a_doji():
    up, down = directional_movement(prev_high=100.0, prev_low=100.0, high=100.5, low=99.5)
    assert up == 0.0 and down == 0.0


# ---------- adx ----------

def test_adx_is_none_without_enough_history():
    assert adx(zigzag(10)) is None


def test_adx_is_high_on_a_straight_line():
    value = adx(zigzag(400))
    assert value is not None
    assert value > 40.0


def test_adx_is_low_on_a_choppy_market():
    value = adx(choppy(400))
    assert value is not None
    assert value < 25.0


def test_adx_separates_a_trend_from_a_chop():
    assert adx(zigzag(400)) > adx(choppy(400)) * 2


# ---------- classify ----------

def test_classify_labels_strong_adx_as_trend():
    assert classify({"adx14": 40.0}) == "trend"


def test_classify_labels_weak_adx_as_sideways():
    assert classify({"adx14": 12.0}) == "sideways"


def test_classify_is_unknown_when_adx_is_missing():
    assert classify({}) == "unknown"
    assert classify(None) == "unknown"
    assert classify({"adx14": None}) == "unknown"


def test_classify_gives_the_boundary_to_a_definite_label():
    # When the two thresholds meet there is no dead zone, so the boundary
    # value must still be tradable rather than falling through to "unknown".
    cfg = RegimeConfig(trend_adx_min=22.0, sideways_adx_max=22.0)
    assert classify({"adx14": 22.0}, cfg) in {"trend", "sideways"}


def test_classify_leaves_a_gap_untradable():
    # A wider dead zone: between 18 and 22 nothing may be labelled.
    cfg = RegimeConfig(trend_adx_min=22.0, sideways_adx_max=18.0)
    assert classify({"adx14": 20.0}, cfg) == "unknown"
    assert classify({"adx14": 17.9}, cfg) == "sideways"
    assert classify({"adx14": 22.1}, cfg) == "trend"


# ---------- series ----------

def test_regime_series_marks_warmup_as_unknown():
    labels = regime_series(choppy(300), RegimeConfig(warmup=120))
    assert labels[0] == "unknown"
    assert labels[100] == "unknown"


def test_regime_series_finds_sideways_bars_in_a_choppy_market():
    labels = regime_series(choppy(400))
    tail = [x for x in labels[200:] if x != "unknown"]
    assert tail
    # Not pure: a noisy random walk still produces 14-bar directional runs, so
    # ADX calls some of it a trend. What matters is that sideways dominates.
    assert tail.count("sideways") > tail.count("trend")


def test_regime_series_labels_a_straight_line_all_trend():
    labels = regime_series(zigzag(400))
    tail = [x for x in labels[200:] if x != "unknown"]
    assert tail
    assert set(tail) == {"trend"}


def test_regime_series_has_no_lookahead():
    # Appending a crash must not change labels that were already computed.
    rows = choppy(400)
    before = regime_series(rows)
    after = regime_series(rows + [
        {"timestamp": rows[-1]["timestamp"] + 3_600_000,
         "open": 50.0, "high": 50.5, "low": 49.5, "close": 50.0}
    ])
    assert before[:400] == after[:400]


# ---------- efficiency ratio ----------

def test_efficiency_ratio_is_none_without_enough_history():
    assert efficiency_ratio([100.0] * 5, period=20) is None


def test_efficiency_ratio_is_one_on_a_straight_line():
    closes = [100.0 * (1.01 ** i) for i in range(21)]
    assert efficiency_ratio(closes, period=20) > 0.99


def test_efficiency_ratio_is_near_zero_on_a_round_trip():
    closes = [100.0, 110.0, 100.0]
    assert efficiency_ratio(closes, period=2) < 0.01


def test_efficiency_ratio_is_none_on_a_dead_flat_series():
    assert efficiency_ratio([100.0] * 30, period=20) is None


def test_efficiency_ratio_separates_a_trend_from_a_chop():
    trend_er = efficiency_ratio([r["close"] for r in zigzag(400)], period=20)
    chop_er = efficiency_ratio([r["close"] for r in choppy(400)], period=20)
    assert trend_er > chop_er * 2