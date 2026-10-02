"""One cycle: provider -> baseline -> local LLM -> validator -> risk -> paper ledger."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_proposal import ProposalValidationError, validate_agent_proposal
from audit_store import AuditStore
from baseline import Candle, detect_signal
from fresh_polling import CandlePoller
from indicators import compute_indicators
from paper_loop import PaperLoop, PaperLoopConfig
from risk import RiskDecision, RiskLimits, TradeProposal


@dataclass
class AgentCycleResult:
    accepted: bool
    reason: str
    candle_timestamp: int = 0
    close: float = 0.0
    baseline_signal: str = "hold"
    agent_action: str = "hold"
    agent_confidence: float = 0.0
    agent_reason_codes: tuple[str, ...] = ()
    agent_invalid_conditions: tuple[str, ...] = ()
    agent_signal_id: str = ""
    validation: str = "skipped"
    relation: str = "unknown"
    risk_reason: str = ""
    executed: bool = False
    exposure_after: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "candle_timestamp": self.candle_timestamp,
            "close": self.close,
            "baseline_signal": self.baseline_signal,
            "agent_action": self.agent_action,
            "agent_confidence": self.agent_confidence,
            "agent_reason_codes": list(self.agent_reason_codes),
            "agent_invalid_conditions": list(self.agent_invalid_conditions),
            "agent_signal_id": self.agent_signal_id,
            "validation": self.validation,
            "relation": self.relation,
            "risk_reason": self.risk_reason,
            "executed": self.executed,
            "exposure_after": self.exposure_after,
        }


class AgentTradingLoop:
    def __init__(
        self,
        provider: Any,
        agent: Any,
        audit_path: str | Path,
        state_path: str | Path,
        evidence_path: str | Path,
        ledger: Callable[[TradeProposal], object] | None = None,
        execute: bool = False,
        limits: RiskLimits | None = None,
    ):
        self.provider = provider
        self.agent = agent
        self.execute_requested = bool(execute)
        self.execute = bool(execute and ledger is not None)
        self.ledger = ledger
        self.evidence_path = Path(evidence_path)
        self.audit = AuditStore(audit_path, state_path)
        self.paper_loop = PaperLoop(
            ledger or (lambda proposal: None),
            self.audit,
            limits=limits or RiskLimits(),
            config=PaperLoopConfig(execute=self.execute),
        )
        self._now_ms = 0
        self.poller = CandlePoller(self._fetch_latest)

    def _fetch_latest(self) -> dict:
        return self.provider.recent_closed(self._now_ms, count=100)[-1]

    def _record(self, payload: dict[str, Any]) -> None:
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def run_cycle(self, now_ms: int, cash: float, current_exposure: float, open_position_quantity: float) -> AgentCycleResult:
        self._now_ms = now_ms
        if self.execute_requested and self.ledger is None:
            return AgentCycleResult(False, "execute_requires_ledger")

        polled = self.poller.poll(now_ms)
        if not polled.accepted:
            return AgentCycleResult(False, polled.reason)
        candle = polled.candle
        rows = self.provider.recent_closed(now_ms, count=100)
        history_rows = [r for r in rows if r["timestamp"] <= candle["timestamp"]]
        history = [Candle(r["timestamp"], r["open"], r["high"], r["low"], r["close"]) for r in history_rows]
        baseline_signal = detect_signal(history, has_position=open_position_quantity > 0)
        # Give the LLM real numbers. Without these it guesses and flags
        # missing_indicator_data, which measures our input, not its skill.
        context = compute_indicators(history_rows)

        raw = self.agent.propose(
            candle_timestamp=int(candle["timestamp"]),
            close=float(candle["close"]),
            baseline_signal=baseline_signal,
            context=context,
            equity=cash,
        )

        state = self.audit.load_state()
        try:
            proposal = validate_agent_proposal(raw, int(candle["timestamp"]), frozenset(state.seen_signal_ids))
        except ProposalValidationError as exc:
            result = AgentCycleResult(
                accepted=True,
                reason="invalid_proposal",
                candle_timestamp=int(candle["timestamp"]),
                close=float(candle["close"]),
                baseline_signal=baseline_signal,
                agent_action=str(raw.get("action", "unknown")),
                agent_confidence=float(raw.get("confidence") or 0.0),
                agent_reason_codes=tuple(raw.get("reason_codes") or ()),
                agent_invalid_conditions=tuple(raw.get("invalid_conditions") or ()),
                agent_signal_id=str(raw.get("signal_id", "")),
                validation="invalid",
                relation="unknown",
            )
            self._record(result.as_dict())
            return result

        relation = "agree" if baseline_signal == proposal.action else "disagree"
        if proposal.action == "hold":
            self.audit.append_decision(
                signal_id=proposal.signal_id,
                proposal={"action": proposal.action, "symbol": proposal.symbol, "price": 0.0, "quantity": 0.0},
                context={"cash": cash, "price_age_seconds": 0.0, "spread_fraction": 0.0005, "relation": relation, "source": "local_llm"},
                decision=RiskDecision(False, "hold", 0.0, 0.0),
            )
            result = AgentCycleResult(
                accepted=True,
                reason="hold",
                candle_timestamp=proposal.candle_timestamp,
                close=float(candle["close"]),
                baseline_signal=baseline_signal,
                agent_action="hold",
                agent_confidence=proposal.confidence,
                agent_reason_codes=proposal.reason_codes,
                agent_invalid_conditions=proposal.invalid_conditions,
                agent_signal_id=proposal.signal_id,
                validation="valid",
                relation=relation,
                risk_reason="hold",
                exposure_after=current_exposure,
            )
            self._record(result.as_dict())
            return result

        decision = self.paper_loop.process(
            TradeProposal(proposal.signal_id, "buy", "BTC", proposal.reference_price, proposal.quantity),
            cash=cash,
            price_age_seconds=0.0,
            spread_fraction=0.0005,
            current_exposure=current_exposure,
            open_position_quantity=open_position_quantity,
        )
        result = AgentCycleResult(
            accepted=True,
            reason=decision.reason,
            candle_timestamp=proposal.candle_timestamp,
            close=float(candle["close"]),
            baseline_signal=baseline_signal,
            agent_action="buy",
            agent_confidence=proposal.confidence,
            agent_reason_codes=proposal.reason_codes,
            agent_invalid_conditions=proposal.invalid_conditions,
            agent_signal_id=proposal.signal_id,
            validation="valid",
            relation=relation,
            risk_reason=decision.reason,
            executed=decision.reason == "approved_executed",
            exposure_after=decision.resulting_exposure,
        )
        self._record(result.as_dict())
        return result
