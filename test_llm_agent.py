import json

from llm_agent import LocalLLMAgent, extract_json_object


def test_extract_json_object_reads_plain_json():
    assert extract_json_object('{"action": "hold"}') == {"action": "hold"}


def test_extract_json_object_reads_fenced_block():
    text = '```json\n{"action": "buy", "confidence": 0.6}\n```'
    assert extract_json_object(text) == {"action": "buy", "confidence": 0.6}


def test_extract_json_object_reads_surrounded_prose():
    text = 'Here is my analysis.\n{"action": "hold", "reason_codes": ["flat"]}\nHope this helps.'
    assert extract_json_object(text) == {"action": "hold", "reason_codes": ["flat"]}


def test_extract_json_object_returns_none_for_prose_only():
    assert extract_json_object("I think we should wait for confirmation.") is None


def test_agent_prompts_for_exact_schema_keys():
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: "unused")
    keys = sorted(agent.build_schema_hint())
    assert keys == [
        "action",
        "baseline_signal",
        "candle_timestamp",
        "confidence",
        "invalid_conditions",
        "model_id",
        "quantity",
        "reason_codes",
        "reference_price",
        "schema_version",
        "signal_id",
        "symbol",
        "timeframe",
    ]


def test_agent_builds_hold_payload_from_invalid_output():
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: "no json here")
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="hold")
    assert payload["action"] == "hold"
    assert payload["quantity"] == 0.0
    assert payload["reference_price"] == 0.0
    assert payload["schema_version"] == "p5.v1"
    assert payload["symbol"] == "BTC"
    assert payload["timeframe"] == "1h"
    assert payload["candle_timestamp"] == 1_700_000_000_000
    assert "invalid_conditions" in payload
    assert payload["model_id"] == "stub"


def test_agent_keeps_valid_model_output():
    raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-1",
        "candle_timestamp": 1_700_000_000_000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "hold",
        "quantity": 0.0,
        "reference_price": 0.0,
        "confidence": 0.4,
        "reason_codes": ["ema_flat"],
        "invalid_conditions": [],
        "baseline_signal": "hold",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: raw)
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="hold")
    assert payload["signal_id"] == "llm-1"
    assert payload["confidence"] == 0.4


def test_agent_rejects_bad_identity_and_order_fields_from_model():
    raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-2",
        "candle_timestamp": 111,
        "symbol": "ETH",
        "timeframe": "4h",
        "action": "buy",
        "quantity": -5,
        "reference_price": -1,
        "confidence": 9.0,
        "reason_codes": ["momentum"],
        "invalid_conditions": [],
        "baseline_signal": "buy",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: raw)
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="hold")
    assert payload["symbol"] == "BTC"
    assert payload["timeframe"] == "1h"
    assert payload["candle_timestamp"] == 1_700_000_000_000
    assert 0.0 <= payload["confidence"] <= 1.0
    assert "buy_fields_invalid" in payload["invalid_conditions"]
    assert payload["action"] == "hold"
    assert payload["quantity"] == 0.0
    assert payload["reference_price"] == 0.0


def test_agent_caps_buy_notional_at_two_percent_of_equity():
    raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-big",
        "candle_timestamp": 1_700_000_000_000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "buy",
        "quantity": 0.01,
        "reference_price": 80_000.0,
        "confidence": 0.9,
        "reason_codes": ["momentum"],
        "invalid_conditions": [],
        "baseline_signal": "buy",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: raw)
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="buy", equity=500.0)
    assert "buy_notional_capped" in payload["invalid_conditions"]
    assert payload["action"] == "hold"


def test_agent_keeps_reasonable_buy_intact():
    raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-ok",
        "candle_timestamp": 1_700_000_000_000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "buy",
        "quantity": 0.00005,
        "reference_price": 80_000.0,
        "confidence": 0.55,
        "reason_codes": ["ema_cross_up"],
        "invalid_conditions": [],
        "baseline_signal": "buy",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: raw)
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="buy", equity=1000.0)
    assert payload["action"] == "buy"
    assert payload["quantity"] == 0.00005
    assert payload["reference_price"] == 80_000.0
    assert payload["invalid_conditions"] == []


def test_agent_forces_hold_to_have_zero_order_fields():
    raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-3",
        "candle_timestamp": 1_700_000_000_000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "hold",
        "quantity": 0.5,
        "reference_price": 80_000.0,
        "confidence": 0.5,
        "reason_codes": ["x"],
        "invalid_conditions": [],
        "baseline_signal": "hold",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: raw)
    payload = agent.propose(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="hold")
    assert payload["quantity"] == 0.0
    assert payload["reference_price"] == 0.0


def test_agent_prompt_mentions_risk_limits_and_no_live_trading():
    agent = LocalLLMAgent(model="stub", complete=lambda prompt, options: "")
    prompt = agent.build_prompt(candle_timestamp=1_700_000_000_000, close=80_000.0, baseline_signal="hold", context={"ema_fast": 80_100.0, "ema_slow": 79_900.0, "change_pct": 0.4})
    assert "BTC" in prompt
    assert "1h" in prompt
    assert "p5.v1" in prompt
    assert "hold" in prompt
    assert "buy" in prompt
    assert "80" in prompt
