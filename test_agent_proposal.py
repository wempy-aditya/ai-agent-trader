import pytest

from agent_proposal import ProposalValidationError, validate_agent_proposal


def valid(**overrides):
    payload = {
        "schema_version": "p5.v1",
        "signal_id": "sig-1",
        "candle_timestamp": 1000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "buy",
        "quantity": 0.0001,
        "reference_price": 50000.0,
        "confidence": 0.8,
        "reason_codes": ["ema_cross"],
        "invalid_conditions": [],
        "baseline_signal": "buy",
        "model_id": "mock-llm-v1",
    }
    payload.update(overrides)
    return payload


def test_valid_buy_normalizes_to_typed_proposal():
    result = validate_agent_proposal(valid(), latest_candle_timestamp=1000, seen_signal_ids=frozenset())
    assert result.action == "buy"
    assert result.quantity == 0.0001


def test_hold_allows_zero_order_fields():
    result = validate_agent_proposal(valid(action="hold", quantity=0.0, reference_price=0.0, baseline_signal="hold"), 1000, frozenset())
    assert result.action == "hold"


@pytest.mark.parametrize("field,value", [("schema_version", "p5.v0"), ("symbol", "ETH"), ("timeframe", "4h"), ("action", "sell"), ("baseline_signal", "sell")])
def test_rejects_wrong_enums(field, value):
    with pytest.raises(ProposalValidationError):
        validate_agent_proposal(valid(**{field: value}), 1000, frozenset())


def test_rejects_stale_timestamp_and_duplicate_id():
    with pytest.raises(ProposalValidationError, match="candle_timestamp"):
        validate_agent_proposal(valid(candle_timestamp=999), 1000, frozenset())
    with pytest.raises(ProposalValidationError, match="duplicate_signal_id"):
        validate_agent_proposal(valid(), 1000, frozenset({"sig-1"}))


def test_rejects_invalid_buy_fields_and_confidence():
    with pytest.raises(ProposalValidationError):
        validate_agent_proposal(valid(quantity=0), 1000, frozenset())
    with pytest.raises(ProposalValidationError):
        validate_agent_proposal(valid(reference_price=-1), 1000, frozenset())
    with pytest.raises(ProposalValidationError):
        validate_agent_proposal(valid(confidence=1.1), 1000, frozenset())


def test_rejects_extra_or_missing_keys():
    payload = valid(extra="nope")
    with pytest.raises(ProposalValidationError, match="exact_keys"):
        validate_agent_proposal(payload, 1000, frozenset())
    payload = valid()
    del payload["model_id"]
    with pytest.raises(ProposalValidationError, match="exact_keys"):
        validate_agent_proposal(payload, 1000, frozenset())
