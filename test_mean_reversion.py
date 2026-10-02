from mean_reversion import (
    MRConfig,
    mean_reversion_criteria,
    should_exit_mr,
    simulate_mean_reversion,
    simulate_random_timing,
)


def ctx(**over):
    base = {
        "closed_candles": 200, "close": 80_000.0,
        "ema20": 79_900.0, "ema50": 79_800.0, "ema_spread_pct": 0.125,
        "rsi14": 34.0, "atr14": 400.0, "atr_pct": 0.5,
        "return_1": -0.6, "return_4": 0.8, "return_24": -1.5,
        "high_24": 82_000.0, "low_24": 78_000.0, "range_position_24": 0.15,
        "closes_above_ema20": False, "closes_above_ema50": False,
    }
    base.update(over)
    return base


# ---------- entry criteria ----------

def test_criteria_pass_when_oversold_and_below_ema20():
    c = mean_reversion_criteria(ctx())
    assert c["oversold_rsi"] is True
    assert c["below_ema20"] is True
    assert c["near_low_24"] is True
    assert c["falling_short_term"] is True
    assert c["not_panicking"] is True
    assert all(c.values())


def test_criteria_fail_when_rsi_is_neutral():
    c = mean_reversion_criteria(ctx(rsi14=55.0))
    assert c["oversold_rsi"] is False


def test_criteria_fail_when_price_still_above_ema20():
    c = mean_reversion_criteria(ctx(closes_above_ema20=True))
    assert c["below_ema20"] is False


def test_criteria_fail_when_price_is_mid_range():
    c = mean_reversion_criteria(ctx(range_position_24=0.5))
    assert c["near_low_24"] is False


def test_criteria_fail_when_price_is_rising():
    c = mean_reversion_criteria(ctx(return_1=0.9))
    assert c["falling_short_term"] is False


def test_criteria_fail_on_a_crash():
    # A huge drop is not a dip to buy, it is a falling knife.
    c = mean_reversion_criteria(ctx(return_24=-15.0))
    assert c["not_panicking"] is False


def test_criteria_fail_when_at_the_actual_low():
    # Bought at exactly the bottom of the range there is no room to bounce.
    c = mean_reversion_criteria(ctx(range_position_24=0.0))
    assert c["near_low_24"] is False


def test_missing_indicator_counts_as_false():
    c = mean_reversion_criteria(ctx(rsi14=None, return_1=None, range_position_24=None))
    assert c["oversold_rsi"] is False
    assert c["falling_short_term"] is False
    assert c["near_low_24"] is False


# ---------- exit ----------

def test_exit_on_rsi_recovery():
    left, why = should_exit_mr(ctx(rsi14=58.0, closes_above_ema20=True), 80_500.0, 79_000.0, 10)
    assert left is True and why == "rsi_recovered"


def test_hold_while_still_cheap():
    left, why = should_exit_mr(ctx(), 80_000.0, 79_000.0, 10)
    assert left is False and why == "holding"


def test_exit_on_stop_loss():
    left, why = should_exit_mr(ctx(), 76_500.0, 79_000.0, 10)
    assert left is True and why == "stop_loss"


def test_exit_on_max_hold_bars():
    left, why = should_exit_mr(ctx(), 80_000.0, 79_000.0, 40)
    assert left is True and why == "max_hold"


def test_no_exit_without_a_position():
    left, why = should_exit_mr(ctx(), 80_000.0, 79_000.0, 0)
    assert left is False and why == "no_position"


def test_max_hold_comes_after_stop_loss_check():
    # Both true: the stop is the more urgent truth and must win the label.
    left, why = should_exit_mr(ctx(), 70_000.0, 79_000.0, 40)
    assert left is True and why == "stop_loss"


# ---------- simulation ----------

def drift_candles(count=600, start=100.0, drift=0.0006, dip_every=60, dip_size=0.05, seed=3):
    """Trending up with periodic sharp dips: the mean-reversion case."""
    import math
    import random

    rng = random.Random(seed)
    out = []
    price = start
    for i in range(count):
        wobble = 1.0 - dip_size * (0.5 + 0.5 * math.cos(i / dip_every * 2 * math.pi))
        price = max(1.0, price * (1.0 + drift + rng.gauss(0.0, 0.003)) * wobble)
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price, "high": price * 1.004, "low": price * 0.996, "close": price,
        })
    return out


def flat_candles(count=600, start=100.0, seed=5):
    import random

    rng = random.Random(seed)
    out = []
    price = start
    for i in range(count):
        price = max(1.0, price * (1.0 + rng.gauss(0.0, 0.004)))
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price, "high": price * 1.003, "low": price * 0.997, "close": price,
        })
    return out


def test_simulation_never_exceeds_the_position_cap():
    cfg = MRConfig()
    row = simulate_mean_reversion(flat_candles(), cfg)
    assert row["max_exposure_used"] <= cfg.position_value * 1.0001


def test_simulation_reports_costs_and_trades():
    row = simulate_mean_reversion(drift_candles(), MRConfig())
    assert row["costs_paid"] >= 0
    assert row["round_trips"] == row["wins"] + row["losses"]
    assert row["label"] == "mean_reversion"


def test_simulation_on_flat_market_loses_mostly_to_costs():
    row = simulate_mean_reversion(flat_candles(), MRConfig())
    assert row["round_trips"] > 0
    assert row["return_pct"] < 1.0


def test_random_timing_control_trades_the_same_way():
    cfg = MRConfig()
    mr = simulate_mean_reversion(drift_candles(), cfg)
    rnd = simulate_random_timing(drift_candles(), cfg, seed=11)
    # The control must actually trade, otherwise it proves nothing.
    assert rnd["round_trips"] > 0
    assert rnd["label"] == "random_timing"
    assert mr["label"] != rnd["label"]


def test_random_timing_is_deterministic_for_a_seed():
    candles = drift_candles()
    a = simulate_random_timing(candles, MRConfig(), seed=7)
    b = simulate_random_timing(candles, MRConfig(), seed=7)
    assert a == b


def test_random_timing_differs_across_seeds():
    candles = drift_candles()
    a = simulate_random_timing(candles, MRConfig(), seed=1)
    b = simulate_random_timing(candles, MRConfig(), seed=2)
    assert a["return_pct"] != b["return_pct"]


def test_entry_without_exit_never_counts_a_win():
    row = simulate_mean_reversion(flat_candles(), MRConfig(max_hold_bars=10_000))
    # Open positions at the end are not round trips, so they cannot be wins.
    assert row["wins"] <= row["round_trips"]