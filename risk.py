"""Long-only BTC spot risk gate. No broker or live execution here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_trade_value: float = 500.0
    max_exposure: float = 500.0
    max_daily_loss: float = 30.0
    max_price_age_seconds: float = 300.0
    max_spread_fraction: float = 0.002


@dataclass(frozen=True)
class TradeProposal:
    signal_id: str
    action: str
    symbol: str
    price: float
    quantity: float


@dataclass(frozen=True)
class RiskContext:
    equity: float
    cash: float
    daily_realized_loss: float
    current_exposure: float
    open_position_quantity: float
    price_age_seconds: float
    spread_fraction: float
    kill_switch: bool
    seen_signal_ids: frozenset[str]


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    trade_value: float
    resulting_exposure: float


class RiskGate:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check(self, proposal: TradeProposal, context: RiskContext) -> RiskDecision:
        trade_value = proposal.price * proposal.quantity
        resulting_exposure = context.current_exposure + trade_value

        def reject(reason: str) -> RiskDecision:
            return RiskDecision(False, reason, trade_value, resulting_exposure)

        if context.kill_switch:
            return reject("kill_switch")
        if proposal.signal_id in context.seen_signal_ids:
            return reject("duplicate_signal")
        if proposal.action != "buy":
            return reject("short_or_sell_disabled" if proposal.action == "sell" else "unsupported_action")
        if proposal.symbol != "BTC":
            return reject("symbol_not_allowed")
        if proposal.price <= 0 or proposal.quantity <= 0:
            return reject("invalid_quantity_or_price")
        if context.price_age_seconds > self.limits.max_price_age_seconds:
            return reject("stale_price")
        if context.spread_fraction > self.limits.max_spread_fraction:
            return reject("spread_too_high")
        if context.daily_realized_loss >= self.limits.max_daily_loss:
            return reject("max_daily_loss")
        if trade_value > self.limits.max_trade_value:
            return reject("max_trade_value")
        if resulting_exposure > self.limits.max_exposure:
            return reject("max_exposure")
        if trade_value > context.cash:
            return reject("insufficient_cash")
        return RiskDecision(True, "approved", trade_value, resulting_exposure)
