import json

from entry_agent import EntryModeAgent, entry_criteria


def ctx(**over):
    base = {
        "closed_candles": 100, "close": 80_000.0, "ema20": 79_900.0, "ema50": 79_800.0,
        "ema_spread_pct": 0.125, "rsi14": 55.0, "atr14": 400.0, "atr_pct": 0.5,
        "return_1": 0.2, "return_4": 0.8, "return_24": 1.5,
        "high_24": 80_500.0, "low_24": 79_000.0, "range_position_24": 0.6,
        "closes_above_ema20": True, "closes_above_ema50": True,
    }
    base.update(over)
    return base


def test_criteria_are_deterministic_and_boolean():
    c = entry_criteria(ctx())
    assert c["ema_spread_positive"] is True
    assert c["price_above_ema20"] is True
    assert c["rsi_in_band"] is True
    assert c["not_overbought"] is True
    assert c["momentum_positive"] is True


def test_criteria_fail_when_ema_is_bearish():
    c = entry_criteria(ctx(ema_spread_pct=-0.3, closes_above_ema20=False, closes_above_ema50=False))
    assert c["ema_spread_positive"] is False
    assert c["price_above_ema20"] is False


def test_criteria_fail_when_overbought():
    c = entry_criteria(ctx(rsi14=78.0))
    assert c["not_overbought"] is False


def test_criteria_fail_when_rsi_too_low():
    c = entry_criteria(ctx(rsi14=28.0))
    assert c["rsi_in_band"] is False


def test_criteria_fail_when_momentum_negative():
    c = entry_criteria(ctx(return_4=-1.0))
    assert c["momentum_positive"] is False


def test_criteria_tolerate_missing_values():
    c = entry_criteria(ctx(ema_spread_pct=None, rsi14=None, return_4=None))
    assert c["ema_spread_positive"] is False
    assert c["rsi_in_band"] is False


def test_prompt_lists_the_criteria_as_checkable():
    agent = EntryModeAgent(model_id="stub")
    prompt = agent.build_prompt(1, 80_000.0, "hold", ctx())
    assert "entry_criteria" in prompt
    assert "exit_criteria" in prompt
    assert "ema_spread_pct" in prompt
    assert json.dumps(agent.build_criteria(ctx()))[:20] in prompt


def test_agent_forces_hold_when_criteria_not_met():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "buy", "quantity": 0.0002, "reference_price": 80_000.0,
        "confidence": 0.9, "reason_codes": ["yolo"], "signal_id": "s1",
    }))
    out = agent.propose(1, 80_000.0, "hold", ctx(ema_spread_pct=-0.5, rsi14=80.0))
    assert out["action"] == "hold"
    assert out["quantity"] == 0.0
    assert "entry_criteria_not_met" in out["invalid_conditions"]


def test_agent_allows_buy_when_criteria_met():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "buy", "quantity": 0.0001, "reference_price": 80_000.0,
        "confidence": 0.7, "reason_codes": ["trend_up"], "signal_id": "s1",
    }))
    out = agent.propose(1, 80_000.0, "hold", ctx())
    assert out["action"] == "buy"
    assert out["quantity"] == 0.0001
    assert out["invalid_conditions"] == []


def test_agent_allows_exit_action_when_holding():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "sell", "quantity": 0.0, "reference_price": 0.0,
        "confidence": 0.8, "reason_codes": ["exit"], "signal_id": "s1",
    }))
    out = agent.propose(1, 80_000.0, "sell", ctx(ema_spread_pct=-0.4), has_position=True)
    assert out["action"] == "sell"
    assert out["quantity"] == 0.0


def test_agent_rejects_sell_when_not_holding():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "sell", "quantity": 0.0, "reference_price": 0.0,
        "confidence": 0.8, "reason_codes": ["exit"], "signal_id": "s1",
    }))
    out = agent.propose(1, 80_000.0, "sell", ctx(), has_position=False)
    assert out["action"] == "hold"
    assert "sell_without_position" in out["invalid_conditions"]


def test_exit_criteria_detects_bearish_flip():
    agent = EntryModeAgent(model_id="stub")
    e = agent.build_exit_criteria(ctx(ema_spread_pct=-0.5, closes_above_ema50=False))
    assert e["ema_bearish"] is True
    assert agent.should_force_exit(e) is True


def test_exit_criteria_do_not_trigger_in_uptrend():
    agent = EntryModeAgent(model_id="stub")
    e = agent.build_exit_criteria(ctx())
    assert e["ema_bearish"] is False
    assert agent.should_force_exit(e) is False


def test_forced_exit_overrides_hold():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "hold", "quantity": 0.0, "reference_price": 0.0,
        "confidence": 0.3, "reason_codes": ["wait"], "signal_id": "s1",
    }))
    out = agent.propose(
        1, 80_000.0, "sell",
        ctx(ema_spread_pct=-0.5, closes_above_ema50=False),
        has_position=True,
    )
    assert out["action"] == "sell"
    assert "forced_exit_bearish_flip" in out["reason_codes"]


def test_forced_exit_does_not_apply_without_position():
    agent = EntryModeAgent(model_id="stub", complete=lambda p: json.dumps({
        "action": "hold", "quantity": 0.0, "reference_price": 0.0,
        "confidence": 0.3, "reason_codes": ["wait"], "signal_id": "s1",
    }))
    out = agent.propose(1, 80_000.0, "hold", ctx(ema_spread_pct=-0.5), has_position=False)
    assert out["action"] == "hold"


def test_criteria_payload_is_json_serialisable():
    agent = EntryModeAgent(model_id="stub")
    json.dumps(agent.build_criteria(ctx()))
    json.dumps(agent.build_exit_criteria(ctx()))