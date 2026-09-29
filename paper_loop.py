"""Controlled baseline -> risk gate -> local paper-ledger boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from audit_store import AuditStore, RuntimeState
from risk import RiskContext, RiskDecision, RiskGate, RiskLimits, TradeProposal


@dataclass(frozen=True)
class PaperLoopConfig:
    execute: bool = False


class PaperLoop:
    def __init__(self, ledger: Callable[[TradeProposal], object], audit: AuditStore, limits: RiskLimits | None = None, config: PaperLoopConfig | None = None):
        self.ledger = ledger
        self.audit = audit
        self.gate = RiskGate(limits or RiskLimits())
        self.config = config or PaperLoopConfig()

    def process_observation(self, observation, cash: float, price_age_seconds: float, spread_fraction: float, current_exposure: float = 0.0, open_position_quantity: float = 0.0) -> RiskDecision:
        if observation.signal == "hold" or observation.proposal is None:
            decision = RiskDecision(False, "hold", 0.0, 0.0)
            self.audit.append_observation(observation, decision)
            return decision
        return self.process(observation.proposal, cash, price_age_seconds, spread_fraction, current_exposure=current_exposure, open_position_quantity=open_position_quantity)

    def process(self, proposal: TradeProposal, cash: float, price_age_seconds: float, spread_fraction: float, current_exposure: float = 0.0, open_position_quantity: float = 0.0) -> RiskDecision:
        state = self.audit.load_state()
        context = RiskContext(equity=cash, cash=cash, daily_realized_loss=state.daily_realized_loss, current_exposure=current_exposure, open_position_quantity=open_position_quantity, price_age_seconds=price_age_seconds, spread_fraction=spread_fraction, kill_switch=state.kill_switch, seen_signal_ids=state.seen_signal_ids)
        decision = self.gate.check(proposal, context)
        self.audit.append_decision(signal_id=proposal.signal_id, proposal={"action": proposal.action, "symbol": proposal.symbol, "price": proposal.price, "quantity": proposal.quantity}, context={"cash": cash, "price_age_seconds": price_age_seconds, "spread_fraction": spread_fraction}, decision=decision)
        if not decision.allowed:
            return decision
        self.audit.save_state(RuntimeState(state.kill_switch, state.daily_realized_loss, state.seen_signal_ids | {proposal.signal_id}))
        if not self.config.execute:
            return RiskDecision(True, "approved_dry_run", decision.trade_value, decision.resulting_exposure)
        self.ledger(proposal)
        return RiskDecision(True, "approved_executed", decision.trade_value, decision.resulting_exposure)
