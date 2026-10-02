"""Exit-rule variants, measured against the same entry gate and the same capital.

Entry is already known to be unsatisfying on its own. This isolates the exit:
same entry criteria, same 500 USDT position size as buy-and-hold, four different
ways to leave. Whichever one wins or loses is measured, not guessed.

Variants:
    ema          current rule: exit when EMA20 crosses below EMA50
    trailing     exit when price falls a set percentage from the running high
    time_based   exit after a fixed number of bars regardless of price
    momentum     exit when 4h return turns negative while still above EMA20
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from entry_agent import build_exit_criteria
from indicators import compute_indicators
from replay import ReplayConfig, simulate_buy_and_hold
from run_replay import load_candles

VARIANTS = ("ema", "trailing", "time_based", "momentum")

TRAILING_DROP_PCT = 0.03
TIME_BARS = 12
POSITION_VALUE = 500.0
WINDOW = 2000


@dataclass
class ExitSpec:
    """How long to hold and when to leave."""

    kind: str = "ema"
    trailing_drop_pct: float = TRAILING_DROP_PCT
    max_hold_bars: int = TIME_BARS
    stop_loss_pct: float = 0.04


def _peak_since_entry(highs: list[float], entry_index: int, index: int) -> float:
    window = highs[max(entry_index, index - 200): index + 1]
    return max(window) if window else highs[index]


def should_exit(spec: ExitSpec, context: dict[str, Any], close: float, entry_price: float,
               peak: float, bars_held: int) -> tuple[bool, str]:
    if bars_held <= 0:
        return False, "no_position"

    if close < entry_price * (1.0 - spec.stop_loss_pct):
        return True, "stop_loss"

    if spec.kind == "ema":
        return (build_exit_criteria(context, True, entry_price)["ema_bearish"], "ema_bearish")

    if spec.kind == "trailing":
        if peak > 0 and close < peak * (1.0 - spec.trailing_drop_pct):
            return True, f"trailing_drop_{spec.trailing_drop_pct:g}"
        return False, "trailing_hold"

    if spec.kind == "time_based":
        if bars_held >= spec.max_hold_bars:
            return True, f"max_hold_{spec.max_hold_bars}"
        return False, "time_hold"

    if spec.kind == "momentum":
        ret_4 = context.get("return_4")
        above_ema20 = bool(context.get("closes_above_ema20"))
        if isinstance(ret_4, (int, float)) and ret_4 < 0 and not above_ema20:
            return True, "momentum_break"
        return False, "momentum_hold"

    return False, "unknown_variant"


def run_variant(rows: list[dict[str, Any]], spec: ExitSpec, capital: float = 1000.0) -> dict[str, Any]:
    from baseline import Candle, detect_signal
    from entry_agent import entry_criteria

    cfg = ReplayConfig(initial_capital=capital, max_trade_value=POSITION_VALUE, max_exposure=POSITION_VALUE)
    cash = capital
    qty = 0.0
    entry = 0.0
    entry_index = 0
    peak = 0.0
    costs = 0.0
    trades = wins = losses = 0
    curve: list[float] = []
    exits: dict[str, int] = {}

    history: list[Candle] = []
    for index, row in enumerate(rows):
        history.append(Candle(row["timestamp"], row["open"], row["high"], row["low"], row["close"]))
        if len(history) < 100:
            continue
        window_rows = rows[max(0, index - 99): index + 1]
        ctx = compute_indicators(window_rows)
        close = float(row["close"])
        has_position = qty > 0

        if has_position:
            peak = max(peak, float(row["high"]))
            left, why = should_exit(spec, ctx, close, entry, peak, index - entry_index)
            if left:
                fill = cfg.sell_price(close)
                proceeds = qty * fill
                cash += proceeds * (1 - cfg.fee_per_side)
                costs += proceeds * cfg.fee_per_side
                if close > entry:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                exits[why] = exits.get(why, 0) + 1
                qty = 0.0
        elif all(entry_criteria(ctx).values()):
            budget = min(POSITION_VALUE, cash)
            qty = budget / close
            fill = cfg.buy_price(close)
            cash -= qty * fill * (1 + cfg.fee_per_side)
            costs += qty * fill * cfg.fee_per_side
            entry = close
            entry_index = index
            peak = float(row["high"])
            trades += 1

        curve.append(cash + qty * close)

    equity = curve[-1] if curve else capital
    peak_eq = capital
    maxdd = 0.0
    for value in curve:
        peak_eq = max(peak_eq, value)
        if peak_eq:
            maxdd = max(maxdd, (peak_eq - value) / peak_eq)

    return {
        "variant": spec.kind,
        "return_pct": round((equity / capital - 1) * 100, 4),
        "max_drawdown_pct": round(maxdd * 100, 4),
        "round_trips": wins + losses,
        "wins": wins,
        "losses": losses,
        "costs_paid": round(costs, 4),
        "exit_reasons": exits,
    }


def main() -> int:
    windows = [int(x) for x in sys.argv[1:]] or [WINDOW]
    capital = ReplayConfig().initial_capital
    all_results: dict[str, Any] = {}

    for window in windows:
        rows = load_candles(window)
        bh = simulate_buy_and_hold(rows, ReplayConfig())
        print(f"=== window {window}  capital {capital:.0f}  position {POSITION_VALUE:.0f} ===")
        print(f"buy_and_hold {bh['return_pct']:+.3f}%  maxDD {bh['max_drawdown_pct']:.3f}%")
        print(f"{'variant':11s} {'return':>9s} {'maxDD':>8s} {'rt':>4s} {'win':>4s} {'loss':>5s} {'cost':>8s}")
        results = []
        for kind in VARIANTS:
            row = run_variant(rows, ExitSpec(kind=kind), capital)
            results.append(row)
            print(f"{row['variant']:11s} {row['return_pct']:+8.3f}% {row['max_drawdown_pct']:7.3f}% "
                  f"{row['round_trips']:4d} {row['wins']:4d} {row['losses']:5d} {row['costs_paid']:8.3f}")
        print()
        all_results[str(window)] = {"buy_and_hold": bh, "variants": results}

    import json
    from pathlib import Path

    out = Path("data/exit_variants.json")
    out.write_text(json.dumps({"position_value": POSITION_VALUE, "windows": all_results},
                              indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())