"""P5.3 paper dry-run disagreement soak; execution refused without explicit ledger."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from agent_proposal import ProposalValidationError, validate_agent_proposal
from audit_store import AuditStore
from baseline import Candle, detect_signal
from paper_loop import PaperLoop, PaperLoopConfig
from risk import RiskDecision, RiskLimits, TradeProposal


class SoakStopped(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SoakRunner:
    candles: Sequence[dict[str, Any]]
    agent_actions: Sequence[str]
    evidence_path: Path
    audit_path: Path
    execute: bool = False
    ledger: Callable[[TradeProposal], object] | None = None
    stale_candle_offset_ms: int = 0
    duplicate_signal_ids: bool = False
    limits: RiskLimits | None = None
    cash: float = 1000.0

    def __post_init__(self) -> None:
        self.evidence_path = Path(self.evidence_path)
        state_path = self.audit_path.with_suffix(".state.json")
        self.audit = AuditStore(self.audit_path, state_path)
        execute = self.execute and self.ledger is not None
        self.paper_loop = PaperLoop(
            self.ledger or (lambda proposal: None),
            self.audit,
            limits=self.limits or RiskLimits(),
            config=PaperLoopConfig(execute=execute),
        )

    def _candles(self, upto: int) -> list[Candle]:
        return [Candle(row["timestamp"], row["open"], row["high"], row["low"], row["close"]) for row in self.candles[:upto]]

    def _payload(self, index: int, action: str, baseline_signal: str) -> dict[str, Any]:
        row = self.candles[index]
        signal_id = "soak-constant-id" if self.duplicate_signal_ids else f"soak-{row['timestamp']}"
        return {
            "schema_version": "p5.v1",
            "signal_id": signal_id,
            "candle_timestamp": int(row["timestamp"]) - self.stale_candle_offset_ms,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": action,
            "quantity": 0.0001 if action == "buy" else 0.0,
            "reference_price": float(row["close"]) if action == "buy" else 0.0,
            "confidence": 0.7,
            "reason_codes": ["soak"],
            "invalid_conditions": [],
            "baseline_signal": baseline_signal,
            "model_id": "deterministic-mock-llm-v1",
        }

    def _record(self, record: dict[str, Any]) -> None:
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def run(self) -> dict[str, Any]:
        if self.execute and self.ledger is None:
            raise SoakStopped("execute_requires_ledger")

        totals: Counter[str] = Counter()
        invalid_reasons: Counter[str] = Counter()
        seen: set[str] = set()
        max_cycles = min(len(self.candles), len(self.agent_actions))

        for index in range(max_cycles):
            totals["cycles"] += 1
            action = self.agent_actions[index]
            candle_timestamp = int(self.candles[index]["timestamp"])
            baseline_signal = detect_signal(self._candles(index + 1), has_position=False)
            payload = self._payload(index, action, baseline_signal if baseline_signal in {"hold", "buy"} else "hold")

            try:
                proposal = validate_agent_proposal(payload, candle_timestamp, frozenset(seen))
            except ProposalValidationError as exc:
                reason = str(exc)
                invalid_reasons[reason] += 1
                totals["invalid"] += 1
                self._record({
                    "cycle": index + 1,
                    "candle_timestamp": candle_timestamp,
                    "baseline_signal": baseline_signal,
                    "agent_action": action,
                    "validation": "invalid",
                    "reason": reason,
                    "executed": False,
                })
                continue

            seen.add(proposal.signal_id)
            relation = "agree" if baseline_signal == proposal.action else "disagree"
            totals[relation] += 1
            totals["valid_proposals"] += 1
            if proposal.action == "buy":
                totals["buy_proposals"] += 1

            if proposal.action == "buy":
                decision = self.paper_loop.process(
                    TradeProposal(proposal.signal_id, "buy", "BTC", proposal.reference_price, proposal.quantity),
                    cash=self.cash,
                    price_age_seconds=0.0,
                    spread_fraction=0.0005,
                )
                outcome = "approved" if decision.allowed else decision.reason
                executed = decision.reason == "approved_executed"
            else:
                self.audit.append_decision(
                    signal_id=proposal.signal_id,
                    proposal={"action": proposal.action, "symbol": proposal.symbol, "price": 0.0, "quantity": 0.0},
                    context={"cash": self.cash, "price_age_seconds": 0.0, "spread_fraction": 0.0005},
                    decision=RiskDecision(False, "hold", 0.0, 0.0),
                )
                outcome = "hold"
                executed = False

            totals["executed"] += 1 if executed else 0
            self._record({
                "cycle": index + 1,
                "candle_timestamp": proposal.candle_timestamp,
                "baseline_signal": baseline_signal,
                "agent_action": proposal.action,
                "validation": "valid",
                "relation": relation,
                "risk_outcome": outcome,
                "executed": executed,
            })

        return {
            "cycles": totals["cycles"],
            "valid_proposals": totals["valid_proposals"],
            "invalid": totals["invalid"],
            "invalid_reasons": dict(sorted(invalid_reasons.items())),
            "agreement": totals["agree"],
            "disagreement": totals["disagree"],
            "buy_proposals": totals["buy_proposals"],
            "executed": totals["executed"],
            "execute": bool(self.execute and self.ledger is not None),
            "stop_reason": "max_cycles",
            "evidence_path": str(self.evidence_path),
            "audit_path": str(self.audit_path),
        }
