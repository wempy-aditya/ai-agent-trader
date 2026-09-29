"""Strict P5 agent proposal boundary; never executes orders."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, FrozenSet


EXPECTED_KEYS = frozenset({
    "schema_version", "signal_id", "candle_timestamp", "symbol", "timeframe",
    "action", "quantity", "reference_price", "confidence", "reason_codes",
    "invalid_conditions", "baseline_signal", "model_id",
})


class ProposalValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AgentProposal:
    schema_version: str
    signal_id: str
    candle_timestamp: int
    symbol: str
    timeframe: str
    action: str
    quantity: float
    reference_price: float
    confidence: float
    reason_codes: tuple[str, ...]
    invalid_conditions: tuple[str, ...]
    baseline_signal: str
    model_id: str


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ProposalValidationError(f"invalid_{field}")
    return float(value)


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ProposalValidationError(f"invalid_{field}")
    return tuple(value)


def validate_agent_proposal(payload: dict[str, Any], latest_candle_timestamp: int, seen_signal_ids: FrozenSet[str]) -> AgentProposal:
    if not isinstance(payload, dict) or frozenset(payload) != EXPECTED_KEYS:
        raise ProposalValidationError("exact_keys")
    if payload["schema_version"] != "p5.v1":
        raise ProposalValidationError("schema_version")
    if not isinstance(payload["signal_id"], str) or not payload["signal_id"]:
        raise ProposalValidationError("signal_id")
    if payload["signal_id"] in seen_signal_ids:
        raise ProposalValidationError("duplicate_signal_id")
    if isinstance(payload["candle_timestamp"], bool) or not isinstance(payload["candle_timestamp"], int) or payload["candle_timestamp"] != latest_candle_timestamp:
        raise ProposalValidationError("candle_timestamp")
    if payload["symbol"] != "BTC":
        raise ProposalValidationError("symbol")
    if payload["timeframe"] != "1h":
        raise ProposalValidationError("timeframe")
    if payload["action"] not in {"hold", "buy"}:
        raise ProposalValidationError("action")
    if payload["baseline_signal"] not in {"hold", "buy"}:
        raise ProposalValidationError("baseline_signal")
    quantity = _finite_number(payload["quantity"], "quantity")
    reference_price = _finite_number(payload["reference_price"], "reference_price")
    confidence = _finite_number(payload["confidence"], "confidence")
    if not 0.0 <= confidence <= 1.0:
        raise ProposalValidationError("confidence")
    if payload["action"] == "buy" and (quantity <= 0 or reference_price <= 0):
        raise ProposalValidationError("buy_fields")
    if payload["action"] == "hold" and (quantity != 0.0 or reference_price != 0.0):
        raise ProposalValidationError("hold_fields")
    reason_codes = _string_list(payload["reason_codes"], "reason_codes")
    invalid_conditions = _string_list(payload["invalid_conditions"], "invalid_conditions")
    if not isinstance(payload["model_id"], str) or not payload["model_id"]:
        raise ProposalValidationError("model_id")
    return AgentProposal(payload["schema_version"], payload["signal_id"], payload["candle_timestamp"], payload["symbol"], payload["timeframe"], payload["action"], quantity, reference_price, confidence, reason_codes, invalid_conditions, payload["baseline_signal"], payload["model_id"])
