import json

from remote_llm import (
    RemoteLLMConfig,
    RemoteLLMError,
    build_chat_request,
    build_systemone_request,
    extract_chat_text,
    normalize_base_url,
    parse_remote_proposal,
    remote_complete,
)


def test_normalize_base_url_strips_trailing_and_v1():
    assert normalize_base_url("https://api.x.dev/v1/") == "https://api.x.dev"
    assert normalize_base_url("https://api.x.dev") == "https://api.x.dev"


def test_chat_request_is_strict_json():
    cfg = RemoteLLMConfig(dialect="openai", base_url="https://api.x.dev", api_key="k", model="m")
    body = build_chat_request("sys", "user", cfg)
    assert body["model"] == "m"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "user"
    assert "temperature" in body


def test_systemone_request_has_state_questions_model():
    cfg = RemoteLLMConfig(dialect="systemone", base_url="https://api.typesafe.ai", api_key="k", model="jev-latest")
    body = build_systemone_request("state-blob", {"action": {"type": "choice", "instructions": "buy or hold"}}, cfg)
    assert body["model"] == "jev-latest"
    assert body["state"] == "state-blob"
    assert body["questions"]["action"]["type"] == "choice"


def test_extract_chat_text_handles_string_and_parts():
    assert extract_chat_text({"choices": [{"message": {"content": "hi"}}]}) == "hi"
    assert extract_chat_text({"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}) == "ab"
    assert extract_chat_text({}) == ""


def test_systemone_answer_becomes_proposal():
    answers = {"action": {"choice": "buy", "confidence": 0.7}, "confidence": {"noul": 0.62}}
    payload = parse_remote_proposal(answers, dialect="systemone", candle_timestamp=42, close=80_000.0, baseline_signal="buy", model_id="m")
    assert payload["action"] == "buy"
    assert payload["candle_timestamp"] == 42
    assert payload["symbol"] == "BTC"
    assert 0.0 <= payload["confidence"] <= 1.0
    assert payload["quantity"] > 0
    assert payload["reference_price"] > 0


def test_systemone_hold_answer_forces_zero_order_fields():
    answers = {"action": {"choice": "hold", "confidence": 0.4}}
    payload = parse_remote_proposal(answers, dialect="systemone", candle_timestamp=42, close=80_000.0, baseline_signal="hold", model_id="m")
    assert payload["action"] == "hold"
    assert payload["quantity"] == 0.0
    assert payload["reference_price"] == 0.0


def test_systemone_unknown_choice_degrades_to_hold():
    answers = {"action": {"choice": "sell_everything"}}
    payload = parse_remote_proposal(answers, dialect="systemone", candle_timestamp=42, close=80_000.0, baseline_signal="hold", model_id="m")
    assert payload["action"] == "hold"
    assert any("action_not_allowed" in c for c in payload["invalid_conditions"])


def test_notional_cap_downgrades_oversized_buy():
    answers = {"action": {"choice": "buy", "confidence": 0.9}}
    payload = parse_remote_proposal(answers, dialect="systemone", candle_timestamp=42, close=80_000.0, baseline_signal="buy", model_id="m", equity=500.0, quantity=0.01)
    assert payload["action"] == "hold"
    assert "buy_notional_capped" in payload["invalid_conditions"]


def test_remote_complete_rejects_plain_http_remote_host():
    cfg = RemoteLLMConfig(dialect="openai", base_url="http://evil.example", api_key="k", model="m")
    try:
        remote_complete(cfg, "prompt", dialect="openai")
    except RemoteLLMError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("expected RemoteLLMError")


def test_remote_complete_never_leaks_api_key_in_error():
    cfg = RemoteLLMConfig(dialect="openai", base_url="https://127.0.0.1:1/v1", api_key="SUPERSECRET", model="m", timeout=1.0)
    try:
        remote_complete(cfg, "prompt", dialect="openai")
    except RemoteLLMError as exc:
        assert "SUPERSECRET" not in str(exc)
    else:
        raise AssertionError("expected RemoteLLMError")


def test_chat_json_hostile_reply_is_neutralised_and_recorded():
    from remote_llm import parse_chat_json_proposal

    raw = json.dumps({
        "schema_version": "p5.v1", "signal_id": "evil", "candle_timestamp": 999,
        "symbol": "ETH", "timeframe": "4h", "action": "sell", "quantity": 5.0,
        "reference_price": 1.0, "confidence": 42.0, "reason_codes": ["liquidation"],
        "invalid_conditions": [], "baseline_signal": "buy", "model_id": "mock",
    })
    payload = parse_chat_json_proposal(raw, candle_timestamp=42, close=80_000.0, baseline_signal="buy", model_id="mock", equity=1000.0)
    assert payload["action"] == "hold"
    assert payload["quantity"] == 0.0
    assert payload["reference_price"] == 0.0
    assert payload["symbol"] == "BTC"
    assert payload["timeframe"] == "1h"
    assert payload["candle_timestamp"] == 42
    assert payload["confidence"] == 1.0
    assert "action_not_allowed" in payload["invalid_conditions"]


def test_chat_json_prose_answer_degrades_to_hold():
    from remote_llm import parse_chat_json_proposal

    payload = parse_chat_json_proposal(
        "Sure! The market looks bullish, you should buy now.",
        candle_timestamp=42, close=80_000.0, baseline_signal="hold", model_id="mock",
    )
    assert payload["action"] == "hold"
    assert payload["invalid_conditions"] == ["llm_output_unparseable"]


def test_chat_json_oversized_quantity_is_capped_but_still_tradeable():
    from remote_llm import parse_chat_json_proposal

    raw = json.dumps({"action": "buy", "quantity": 0.05, "reference_price": 80_000.0, "confidence": 0.9, "reason_codes": ["yolo"]})
    payload = parse_chat_json_proposal(raw, candle_timestamp=42, close=80_000.0, baseline_signal="buy", model_id="mock", equity=1000.0)
    # 0.05 BTC is far beyond the cap, but the capped 0.0002 BTC is 16 USDT,
    # which is still inside the 2% (20 USDT) notional limit.
    assert payload["quantity"] == 0.0002
    assert payload["action"] == "buy"
    assert "buy_quantity_capped" in payload["invalid_conditions"]


def test_chat_json_notional_cap_forces_hold_on_small_equity():
    from remote_llm import parse_chat_json_proposal

    raw = json.dumps({"action": "buy", "quantity": 0.0001, "reference_price": 80_000.0, "confidence": 0.9, "reason_codes": ["yolo"]})
    # 0.0001 BTC at 80,000 is 8 USDT, above a 2% cap on 100 USDT equity.
    payload = parse_chat_json_proposal(raw, candle_timestamp=42, close=80_000.0, baseline_signal="buy", model_id="mock", equity=100.0)
    assert payload["action"] == "hold"
    assert "buy_notional_capped" in payload["invalid_conditions"]


def test_config_loader_reads_mode_600_file(tmp_path):
    from remote_llm import load_remote_config

    path = tmp_path / "llm.json"
    path.write_text(json.dumps({"dialect": "openai", "base_url": "https://api.x.dev", "api_key": "abc", "model": "gpt-x"}))
    path.chmod(0o600)
    cfg = load_remote_config(path)
    assert cfg.dialect == "openai"
    assert cfg.model == "gpt-x"


def test_config_loader_rejects_broad_permissions(tmp_path):
    from remote_llm import load_remote_config

    path = tmp_path / "llm.json"
    path.write_text(json.dumps({"dialect": "openai", "base_url": "https://api.x.dev", "api_key": "abc", "model": "gpt-x"}))
    path.chmod(0o644)
    try:
        load_remote_config(path)
    except RemoteLLMError as exc:
        assert "600" in str(exc)
    else:
        raise AssertionError("expected RemoteLLMError")
