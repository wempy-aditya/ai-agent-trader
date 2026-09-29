from dataclasses import replace

from risk import RiskContext, RiskGate, RiskLimits, TradeProposal


def ctx(**kwargs):
    base = RiskContext(
        equity=1000.0,
        cash=1000.0,
        daily_realized_loss=0.0,
        current_exposure=0.0,
        open_position_quantity=0.0,
        price_age_seconds=0.0,
        spread_fraction=0.0005,
        kill_switch=False,
        seen_signal_ids=frozenset(),
    )
    return replace(base, **kwargs)


def buy(**kwargs):
    base = TradeProposal(signal_id="s-1", action="buy", symbol="BTC", price=50000.0, quantity=0.01)
    return replace(base, **kwargs)


def test_allows_valid_buy():
    decision = RiskGate(RiskLimits()).check(buy(), ctx())
    assert decision.allowed is True
    assert decision.reason == "approved"


def test_rejects_trade_value_over_limit():
    decision = RiskGate(RiskLimits(max_trade_value=400.0)).check(buy(), ctx())
    assert decision.allowed is False
    assert decision.reason == "max_trade_value"


def test_rejects_exposure_over_limit():
    decision = RiskGate(RiskLimits(max_trade_value=1000.0, max_exposure=500.0)).check(buy(quantity=0.011), ctx())
    assert decision.allowed is False
    assert decision.reason == "max_exposure"


def test_rejects_after_daily_loss_limit():
    decision = RiskGate(RiskLimits(max_daily_loss=30.0)).check(buy(), ctx(daily_realized_loss=30.0))
    assert decision.allowed is False
    assert decision.reason == "max_daily_loss"


def test_rejects_stale_price_and_wide_spread():
    gate = RiskGate(RiskLimits(max_price_age_seconds=60.0, max_spread_fraction=0.001))
    assert gate.check(buy(), ctx(price_age_seconds=61.0)).reason == "stale_price"
    assert gate.check(buy(), ctx(spread_fraction=0.0011)).reason == "spread_too_high"


def test_rejects_duplicate_and_kill_switch():
    gate = RiskGate(RiskLimits())
    assert gate.check(buy(), ctx(seen_signal_ids=frozenset({"s-1"}))).reason == "duplicate_signal"
    assert gate.check(buy(), ctx(kill_switch=True)).reason == "kill_switch"


def test_rejects_short_and_invalid_action():
    gate = RiskGate(RiskLimits())
    assert gate.check(buy(action="sell"), ctx()).reason == "short_or_sell_disabled"
    assert gate.check(buy(action="hold"), ctx()).reason == "unsupported_action"
