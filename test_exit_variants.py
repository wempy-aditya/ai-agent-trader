from exit_variants import (
    ExitSpec,
    should_exit,
    run_variant,
    TRAILING_DROP_PCT,
    VARIANTS,
)


def ctx(**over):
    base = {
        "ema_spread_pct": 0.2, "rsi14": 55.0, "return_4": 1.0,
        "closes_above_ema20": True, "closes_above_ema50": True,
    }
    base.update(over)
    return base


def test_no_exit_without_a_position():
    for kind in VARIANTS:
        left, why = should_exit(ExitSpec(kind=kind), ctx(), 100.0, 100.0, 100.0, 0)
        assert left is False
        assert why == "no_position"


def test_stop_loss_fires_in_every_variant():
    for kind in VARIANTS:
        spec = ExitSpec(kind=kind, stop_loss_pct=0.04)
        left, why = should_exit(spec, ctx(), 95.0, 100.0, 100.0, 5)
        assert left is True and why == "stop_loss"


def test_ema_variant_exits_on_bearish_flip():
    left, why = should_exit(ExitSpec(kind="ema"), ctx(ema_spread_pct=-0.3, closes_above_ema50=False), 100.0, 100.0, 100.0, 5)
    assert left is True and why == "ema_bearish"


def test_ema_variant_holds_in_uptrend():
    left, why = should_exit(ExitSpec(kind="ema"), ctx(), 100.0, 100.0, 100.0, 5)
    assert left is False and why == "ema_bearish"


def test_trailing_variant_exits_after_a_peak_drop():
    spec = ExitSpec(kind="trailing", trailing_drop_pct=0.03)
    left, why = should_exit(spec, ctx(), 96.0, 100.0, 100.0, 5)
    assert left is True and why == "trailing_drop_0.03"


def test_trailing_variant_holds_inside_the_band():
    spec = ExitSpec(kind="trailing", trailing_drop_pct=0.03)
    left, why = should_exit(spec, ctx(), 98.0, 100.0, 100.0, 5)
    assert left is False and why == "trailing_hold"


def test_trailing_rises_with_the_peak():
    spec = ExitSpec(kind="trailing", trailing_drop_pct=0.03)
    # Price fell 4% from entry but is only 2% below the running high.
    left, _ = should_exit(spec, ctx(), 96.0, 100.0, 98.0, 5)
    assert left is False


def test_time_variant_exits_after_max_hold_bars():
    spec = ExitSpec(kind="time_based", max_hold_bars=12)
    left, why = should_exit(spec, ctx(), 100.0, 100.0, 100.0, 12)
    assert left is True and why == "max_hold_12"


def test_time_variant_holds_before_the_limit():
    spec = ExitSpec(kind="time_based", max_hold_bars=12)
    left, why = should_exit(spec, ctx(), 100.0, 100.0, 100.0, 11)
    assert left is False and why == "time_hold"


def test_momentum_variant_exits_when_return_flips_and_price_loses_ema20():
    left, why = should_exit(ExitSpec(kind="momentum"), ctx(return_4=-0.5, closes_above_ema20=False), 100.0, 100.0, 100.0, 5)
    assert left is True and why == "momentum_break"


def test_momentum_variant_holds_when_price_stays_above_ema20():
    left, why = should_exit(ExitSpec(kind="momentum"), ctx(return_4=-0.5), 100.0, 100.0, 100.0, 5)
    assert left is False and why == "momentum_hold"


def test_momentum_variant_holds_when_return_is_positive():
    left, why = should_exit(ExitSpec(kind="momentum"), ctx(return_4=0.5, closes_above_ema20=False), 100.0, 100.0, 100.0, 5)
    assert left is False


def test_momentum_variant_tolerates_a_missing_return():
    left, why = should_exit(ExitSpec(kind="momentum"), ctx(return_4=None, closes_above_ema20=False), 100.0, 100.0, 100.0, 5)
    assert left is False


def test_unknown_variant_never_exits():
    left, why = should_exit(ExitSpec(kind="nonsense"), ctx(), 100.0, 100.0, 100.0, 5)
    assert left is False and why == "unknown_variant"


def test_every_variant_has_a_distinct_reason_label():
    reasons = set()
    for kind in VARIANTS:
        _, why = should_exit(ExitSpec(kind=kind, stop_loss_pct=0.0, trailing_drop_pct=0.0, max_hold_bars=0), ctx(), 100.0, 100.0, 100.0, 5)
        reasons.add(why)
    assert len(reasons) == len(VARIANTS)


def test_run_variant_never_exceeds_the_position_cap():
    rows = [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
        for i in range(120)
    ]
    row = run_variant(rows, ExitSpec(kind="ema"), capital=1000.0)
    assert row["return_pct"] == 0.0


def test_run_variant_records_exit_reasons():
    rows = [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
        for i in range(120)
    ]
    row = run_variant(rows, ExitSpec(kind="time_based", max_hold_bars=1), capital=1000.0)
    assert isinstance(row["exit_reasons"], dict)