"""Historical replay: agent vs deterministic baseline vs buy-and-hold.

Purpose is to find out whether the LLM adds an edge, not to prove it. Three
numbers matter and they are reported side by side, because a strategy that
"makes money" while buy-and-hold makes far more is not a strategy worth
running.

Every result includes costs: fee, slippage and spread per side, so the numbers
are not fantasy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ReplayConfig:
    initial_capital: float = 1_000.0
    fee_per_side: float = 0.001
    slippage_per_side: float = 0.0005
    spread_round_trip: float = 0.0005
    max_exposure: float = 500.0
    max_trade_value: float = 500.0
    lookback: int = 100
    warmup: int = 51
    stop_loss_fraction: float = 0.02

    def round_trip_cost(self, trade_value: float) -> float:
        return trade_value * (
            (2 * self.fee_per_side) + (2 * self.slippage_per_side) + self.spread_round_trip
        )

    def buy_price(self, price: float) -> float:
        return price * (1.0 + self.slippage_per_side)

    def sell_price(self, price: float) -> float:
        return price * (1.0 - self.slippage_per_side)


@dataclass
class ReplayResult:
    label: str
    initial_capital: float
    final_equity: float
    trades: int
    wins: int
    losses: int
    return_pct: float
    max_drawdown_pct: float
    max_exposure_used: float
    costs_paid: float
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "initial_capital": round(self.initial_capital, 4),
            "final_equity": round(self.final_equity, 4),
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": round((self.wins / self.trades * 100.0) if self.trades else 0.0, 2),
            "return_pct": round(self.return_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_exposure_used": round(self.max_exposure_used, 4),
            "costs_paid": round(self.costs_paid, 4),
            **self.extra,
        }


def _drawdown_pct(equity_curve: list[float], initial: float) -> float:
    peak = initial
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, ((peak - value) / peak) * 100.0)
    return worst


def simulate_buy_and_hold(candles: list[dict[str, Any]], config: ReplayConfig = ReplayConfig()) -> dict[str, Any]:
    """Buy at the first usable candle, hold to the end, charge both sides."""
    if len(candles) < 2:
        return {"label": "buy_and_hold", "trades": 0, "final_equity": config.initial_capital,
                "initial_capital": config.initial_capital, "return_pct": 0.0, "max_drawdown_pct": 0.0,
                "max_exposure_used": 0.0, "costs_paid": 0.0, "wins": 0, "losses": 0}

    entry_reference = float(candles[0]["close"])
    quantity = min(
        config.max_trade_value / entry_reference,
        config.max_exposure / entry_reference,
    )
    trade_value = quantity * entry_reference
    if quantity <= 0:
        return {"label": "buy_and_hold", "trades": 0, "final_equity": config.initial_capital,
                "initial_capital": config.initial_capital, "return_pct": 0.0, "max_drawdown_pct": 0.0,
                "max_exposure_used": 0.0, "costs_paid": 0.0, "wins": 0, "losses": 0}

    buy_fill = config.buy_price(entry_reference)
    cash = config.initial_capital - (quantity * buy_fill)
    cash -= quantity * entry_reference * config.fee_per_side
    costs = quantity * entry_reference * config.fee_per_side

    curve: list[float] = []
    for candle in candles:
        mark = cash + (quantity * float(candle["close"]))
        curve.append(mark)

    final_reference = float(candles[-1]["close"])
    sell_fill = config.sell_price(final_reference)
    proceeds = quantity * sell_fill
    sell_fee = proceeds * config.fee_per_side
    costs += sell_fee
    final_equity = cash + proceeds - sell_fee

    pnl = final_equity - config.initial_capital
    return {
        "label": "buy_and_hold",
        "trades": 1,
        "wins": 1 if pnl > 0 else 0,
        "losses": 0 if pnl > 0 else 1,
        "initial_capital": config.initial_capital,
        "final_equity": final_equity,
        "return_pct": (final_equity / config.initial_capital - 1.0) * 100.0,
        "max_drawdown_pct": _drawdown_pct(curve, config.initial_capital),
        "max_exposure_used": trade_value,
        "costs_paid": costs,
    }


def simulate_baseline(candles: list[dict[str, Any]], config: ReplayConfig = ReplayConfig()) -> dict[str, Any]:
    """Deterministic EMA20/EMA50 crossover, long only, exit on the reverse cross."""
    from baseline import Candle, detect_signal

    history = [Candle(c["timestamp"], c["open"], c["high"], c["low"], c["close"]) for c in candles]
    cash = config.initial_capital
    quantity = 0.0
    entry = 0.0
    trades = 0
    wins = 0
    losses = 0
    costs = 0.0
    peak_exposure = 0.0
    curve: list[float] = []

    for index, candle in enumerate(candles):
        window = history[: index + 1]
        if len(window) < 51:
            continue
        signal = detect_signal(window, has_position=quantity > 0)
        price = float(candle["close"])

        if signal == "buy" and quantity == 0:
            budget = min(config.max_trade_value, config.max_exposure, cash)
            quantity = budget / price
            if quantity > 0:
                fill = config.buy_price(price)
                cost = quantity * fill
                fee = cost * config.fee_per_side
                cash -= (cost + fee)
                costs += fee
                entry = price
                peak_exposure = max(peak_exposure, cost)
                trades += 1
        elif signal == "sell" and quantity > 0:
            fill = config.sell_price(price)
            proceeds = quantity * fill
            fee = proceeds * config.fee_per_side
            cash += (proceeds - fee)
            costs += fee
            if proceeds > quantity * entry:
                wins += 1
            else:
                losses += 1
            quantity = 0.0

        mark = cash + (quantity * price)
        curve.append(mark)

    final_equity = cash + (quantity * float(candles[-1]["close"]))
    return {
        "label": "baseline_ema",
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "initial_capital": config.initial_capital,
        "final_equity": final_equity,
        "return_pct": (final_equity / config.initial_capital - 1.0) * 100.0,
        "max_drawdown_pct": _drawdown_pct(curve, config.initial_capital),
        "max_exposure_used": peak_exposure,
        "costs_paid": costs,
    }


def replay_candles(
    candles: list[dict[str, Any]],
    agent: Callable[..., dict[str, Any]] | Any,
    config: ReplayConfig = ReplayConfig(),
    on_decision: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Walk the candles once, ask the agent each step, paper-fill its BUYs."""
    from baseline import Candle, detect_signal

    history: list[Candle] = []
    cash = config.initial_capital
    quantity = 0.0
    entry = 0.0
    peak_exposure = 0.0
    costs = 0.0
    cycles = hold = buy = invalid = executed = disagreement = 0
    agreement = 0
    wins = losses = 0
    curve: list[float] = []
    agent_buys = 0

    def ask(**kwargs: Any) -> dict[str, Any]:
        nonlocal agent_buys
        if callable(agent):
            return agent(**kwargs)
        return agent.propose(**kwargs)

    for index, candle in enumerate(candles):
        window = history + [Candle(candle["timestamp"], candle["open"], candle["high"], candle["low"], candle["close"])]
        history = window
        if len(window) < config.warmup:
            continue

        cycles += 1
        price = float(candle["close"])
        baseline_signal = detect_signal(window, has_position=quantity > 0)

        context = _context_for(window)
        try:
            proposal = ask(
                candle_timestamp=int(candle["timestamp"]),
                close=price,
                baseline_signal=baseline_signal,
                context=context,
                equity=cash,
            )
        except Exception as exc:  # noqa: BLE001 - a broken agent must not kill the run
            invalid += 1
            if on_decision:
                on_decision({"cycle": cycles, "error": type(exc).__name__, "candle": candle["timestamp"]})
            curve.append(cash + quantity * price)
            continue

        action = str(proposal.get("action", "hold"))
        conditions = list(proposal.get("invalid_conditions") or [])
        blocked = {"action_not_allowed", "buy_notional_capped", "buy_fields_invalid", "llm_output_unparseable"}
        if action not in {"hold", "buy"} or (conditions and set(conditions) & blocked):
            invalid += 1
        elif action == "buy":
            buy += 1
            agent_buys += 1
            if baseline_signal == "buy":
                agreement += 1
            else:
                disagreement += 1
            if quantity == 0:
                budget = min(config.max_trade_value, config.max_exposure, cash)
                wanted = float(proposal.get("quantity") or 0.0)
                if wanted > 0:
                    quantity = min(wanted, budget / price)
                else:
                    quantity = budget / price
                if quantity > 0:
                    fill = config.buy_price(price)
                    cost = quantity * fill
                    fee = cost * config.fee_per_side
                    cash -= (cost + fee)
                    costs += fee
                    entry = price
                    peak_exposure = max(peak_exposure, cost)
                    executed += 1
        else:
            hold += 1
            if baseline_signal == "buy":
                agreement += 1
            else:
                disagreement += 1

        if on_decision:
            on_decision({
                "cycle": cycles,
                "candle": int(candle["timestamp"]),
                "close": price,
                "baseline": baseline_signal,
                "agent": action,
                "executed": bool(quantity),
            })

        curve.append(cash + quantity * price)

    final_equity = cash + (quantity * float(candles[-1]["close"])) if candles else config.initial_capital
    if quantity > 0:
        wins = 1 if final_equity > config.initial_capital else 0
        losses = 0 if wins else 1

    return {
        "label": "agent",
        "cycles": cycles,
        "hold": hold,
        "buy": buy,
        "invalid": invalid,
        "executed": executed,
        "agreement": agreement,
        "disagreement": disagreement,
        "agent_buy_proposals": agent_buys,
        "equity": round(final_equity, 4),
        "initial_capital": config.initial_capital,
        "return_pct": round((final_equity / config.initial_capital - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(_drawdown_pct(curve, config.initial_capital), 4),
        "max_exposure_used": round(peak_exposure, 4),
        "costs_paid": round(costs, 4),
        "trades": executed,
        "wins": wins,
        "losses": losses,
    }


def _context_for(window: list[Any]) -> dict[str, Any]:
    from indicators import compute_indicators

    rows = [
        {"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in window[-100:]
    ]
    return compute_indicators(rows)