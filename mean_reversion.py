"""Mean reversion: buy weakness, sell strength. The mirror image of trend following.

Everything tested so far entered on strength. That is one bet, not a strategy
family: if the market ran up over the sample, buying strength looks good for
reasons that have nothing to do with the rules. This module tests the opposite
bet on the same data with the same costs.

A random-timing control sits next to it deliberately. Without it, "buy the dip"
losing money proves nothing, because a market that trended up punishes any
strategy that sits in cash. The control trades at random times with the same
size and the same costs, so the comparison isolates the rule from the drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from entry_agent import _flag, _num
from indicators import compute_indicators
from replay import ReplayConfig


@dataclass(frozen=True)
class MRConfig:
    initial_capital: float = 1_000.0
    position_value: float = 500.0
    fee_per_side: float = 0.001
    slippage_per_side: float = 0.0005
    rsi_oversold: float = 38.0
    rsi_recovered: float = 55.0
    near_low_max: float = 0.35
    max_panic_drop_pct: float = -10.0
    stop_loss_pct: float = 0.03
    max_hold_bars: int = 24
    warmup: int = 100
    lookback: int = 100

    def buy_price(self, price: float) -> float:
        return price * (1.0 + self.slippage_per_side)

    def sell_price(self, price: float) -> float:
        return price * (1.0 - self.slippage_per_side)


def mean_reversion_criteria(context: dict[str, Any] | None) -> dict[str, bool]:
    """Entry gate. Every rule must hold. A missing indicator counts as false."""
    cfg = MRConfig()
    ctx = context or {}
    rsi14 = _num(ctx.get("rsi14"))
    drop_1 = _num(ctx.get("return_1"))
    drop_24 = _num(ctx.get("return_24"))
    range_pos = _num(ctx.get("range_position_24"))

    return {
        "oversold_rsi": rsi14 is not None and rsi14 <= cfg.rsi_oversold,
        "below_ema20": not _flag(ctx.get("closes_above_ema20")),
        "near_low_24": range_pos is not None and 0.0 < range_pos <= cfg.near_low_max,
        "falling_short_term": drop_1 is not None and drop_1 < 0,
        "not_panicking": drop_24 is not None and drop_24 > cfg.max_panic_drop_pct,
    }


def should_exit_mr(context: dict[str, Any] | None, close: float, entry_price: float,
                   bars_held: int, config: MRConfig | None = None) -> tuple[bool, str]:
    cfg = config or MRConfig()
    if bars_held <= 0:
        return False, "no_position"

    if entry_price > 0 and close < entry_price * (1.0 - cfg.stop_loss_pct):
        return True, "stop_loss"

    ctx = context or {}
    rsi14 = _num(ctx.get("rsi14"))
    if rsi14 is not None and rsi14 >= cfg.rsi_recovered and _flag(ctx.get("closes_above_ema20")):
        return True, "rsi_recovered"

    if bars_held >= cfg.max_hold_bars:
        return True, "max_hold"

    return False, "holding"


def _simulate(rows: list[dict[str, Any]], config: MRConfig, label: str,
              entry, exit_fn, on_open=None) -> dict[str, Any]:
    cash = config.initial_capital
    qty = 0.0
    entry_price = 0.0
    bars_held = 0
    costs = 0.0
    wins = losses = entries = 0
    peak_exposure = 0.0
    curve: list[float] = []
    exit_reasons: dict[str, int] = {}

    for index, row in enumerate(rows):
        if index < config.warmup:
            curve.append(cash)
            continue

        close = float(row["close"])
        window = rows[max(0, index - config.lookback + 1): index + 1]
        ctx = compute_indicators(window)

        if qty > 0:
            bars_held += 1
            left, why = exit_fn(ctx, close, entry_price, bars_held)
            if left:
                fill = config.sell_price(close)
                proceeds = qty * fill
                cash += proceeds * (1 - config.fee_per_side)
                costs += proceeds * config.fee_per_side
                if close > entry_price:
                    wins += 1
                else:
                    losses += 1
                exit_reasons[why] = exit_reasons.get(why, 0) + 1
                qty = 0.0
                bars_held = 0
        elif entry(ctx, index):
            budget = min(config.position_value, cash)
            if budget > 0:
                # Size from the fill price, not the raw close, so slippage
                # cannot push the position past the exposure cap.
                fill = config.buy_price(close)
                qty = budget / fill
                cash -= qty * fill * (1 + config.fee_per_side)
                costs += qty * fill * config.fee_per_side
                entry_price = close
                bars_held = 0
                entries += 1
                peak_exposure = max(peak_exposure, qty * fill)
                if on_open:
                    on_open(index, close)

        curve.append(cash + qty * close)

    equity = curve[-1] if curve else config.initial_capital
    peak = config.initial_capital
    maxdd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak:
            maxdd = max(maxdd, (peak - value) / peak)

    return {
        "label": label,
        "initial_capital": config.initial_capital,
        "final_equity": round(equity, 4),
        "return_pct": round((equity / config.initial_capital - 1) * 100, 4),
        "max_drawdown_pct": round(maxdd * 100, 4),
        "entries": entries,
        "round_trips": wins + losses,
        "wins": wins,
        "losses": losses,
        "open_at_end": round(qty, 8),
        "max_exposure_used": round(peak_exposure, 4),
        "costs_paid": round(costs, 4),
        "exit_reasons": exit_reasons,
    }


def simulate_mean_reversion(rows: list[dict[str, Any]], config: MRConfig | None = None) -> dict[str, Any]:
    cfg = config or MRConfig()

    def entry(ctx: dict[str, Any], index: int) -> bool:
        return all(mean_reversion_criteria(ctx).values())

    def exit_fn(ctx, close, entry_price, bars_held):
        return should_exit_mr(ctx, close, entry_price, bars_held, cfg)

    return _simulate(rows, cfg, "mean_reversion", entry, exit_fn)


def simulate_random_timing(rows: list[dict[str, Any]], config: MRConfig | None = None,
                           seed: int = 0) -> dict[str, Any]:
    """Control: enter at random, exit on the same rule. Same size, same costs."""
    import random

    cfg = config or MRConfig()
    rng = random.Random(seed)
    schedule = {rng.randrange(cfg.warmup, len(rows)) for _ in range(max(1, len(rows) // 40))}

    def entry(ctx: dict[str, Any], index: int) -> bool:
        return index in schedule

    def exit_fn(ctx, close, entry_price, bars_held):
        return should_exit_mr(ctx, close, entry_price, bars_held, cfg)

    return _simulate(rows, cfg, "random_timing", entry, exit_fn)