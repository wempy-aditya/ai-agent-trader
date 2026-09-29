"""Deterministic baseline versus mock-agent comparison; never executes."""
from __future__ import annotations

from dataclasses import dataclass

from agent_proposal import ProposalValidationError, validate_agent_proposal
from baseline import Candle, detect_signal


@dataclass(frozen=True)
class ComparisonResult:
    baseline_signal: str
    agent_action: str
    relation: str
    validation: str
    reason: str | None
    execute: bool
    signal_id: str


def compare_baseline_with_mock(candles: list[Candle], has_position: bool, mock_action: str) -> ComparisonResult:
    baseline_signal = detect_signal(candles, has_position)
    timestamp = int(candles[-1].timestamp)
    price = candles[-1].close
    payload = {
        "schema_version": "p5.v1",
        "signal_id": f"mock-{timestamp}-{mock_action}",
        "candle_timestamp": timestamp,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": mock_action,
        "quantity": 0.0001 if mock_action == "buy" else 0.0,
        "reference_price": price if mock_action == "buy" else 0.0,
        "confidence": 0.75,
        "reason_codes": ["mock_action"],
        "invalid_conditions": [],
        "baseline_signal": baseline_signal if baseline_signal in {"hold", "buy"} else "hold",
        "model_id": "deterministic-mock-llm-v1",
    }
    try:
        proposal = validate_agent_proposal(payload, timestamp, frozenset())
    except ProposalValidationError as exc:
        return ComparisonResult(baseline_signal, mock_action, "disagree", "invalid", str(exc), False, payload["signal_id"])
    relation = "agree" if baseline_signal == proposal.action else "disagree"
    return ComparisonResult(baseline_signal, proposal.action, relation, "valid", None, False, proposal.signal_id)
