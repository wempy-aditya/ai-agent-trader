"""Small deterministic backtest harness for the BTC 1h baseline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from baseline import BacktestConfig, Candle, calculate_position_size, detect_signal, estimate_round_trip_cost


@dataclass(frozen=True)
class BacktestResult:
    candles: int
    trades: int
    wins: int
    losses: int
    final_equity: float
    metrics: dict[str, float]


def _day(timestamp: int | str) -> str:
    value = float(timestamp)
    if value > 10_000_000_000:
        value /= 1000
    return datetime.fromtimestamp(value, timezone.utc).date().isoformat()


def run_backtest(candles: list[Candle], config: BacktestConfig) -> BacktestResult:
    if not candles:
        return BacktestResult(0, 0, 0, 0, config.initial_capital, {"return_pct": 0.0, "realized_pnl": 0.0, "win_rate_pct": 0.0, "max_drawdown_pct": 0.0, "expectancy": 0.0, "max_losing_streak": 0.0, "days_seen": 0.0})

    cash = config.initial_capital
    quantity = 0.0
    entry = 0.0
    realized = 0.0
    trade_pnls: list[float] = []
    trades = wins = losses = 0
    peak = equity = cash
    max_drawdown = 0.0
    daily_loss = 0.0
    current_day = _day(candles[0].timestamp)
    days_seen = {current_day}
    losing_streak = max_losing_streak = 0

    for index in range(config.ema_slow, len(candles) - 1):
        window = candles[: index + 1]
        current = candles[index]
        next_open = candles[index + 1].open
        day = _day(current.timestamp)
        days_seen.add(day)
        if day != current_day:
            current_day = day
            daily_loss = 0.0
        signal = detect_signal(window, has_position=quantity > 0, fast_period=config.ema_fast, slow_period=config.ema_slow)
        if quantity > 0:
            stop = entry * (1 - config.stop_loss_fraction)
            if current.low <= stop or signal == "sell":
                exit_price = stop if current.low <= stop else next_open
                value = quantity * exit_price
                cost = estimate_round_trip_cost(value, config) / 2
                pnl = (exit_price - entry) * quantity - cost
                cash += value - cost
                realized += pnl
                trade_pnls.append(pnl)
                trades += 1
                wins += int(pnl > 0)
                losses += int(pnl <= 0)
                if pnl <= 0:
                    losing_streak += 1
                    max_losing_streak = max(max_losing_streak, losing_streak)
                    daily_loss += -pnl
                else:
                    losing_streak = 0
                quantity = 0.0
                entry = 0.0
        elif daily_loss < config.max_daily_loss and signal == "buy":
            quantity = calculate_position_size(next_open, config)
            value = quantity * next_open
            cost = estimate_round_trip_cost(value, config) / 2
            if value + cost <= cash and value <= (config.max_exposure + 1e-9):
                cash -= value + cost
                entry = next_open
            else:
                quantity = 0.0

        equity = cash + (quantity * current.close)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)

    if quantity > 0:
        exit_price = candles[-1].close
        value = quantity * exit_price
        cost = estimate_round_trip_cost(value, config) / 2
        pnl = (exit_price - entry) * quantity - cost
        cash += value - cost
        realized += pnl
        trade_pnls.append(pnl)
        trades += 1
        wins += int(pnl > 0)
        losses += int(pnl <= 0)
        if pnl <= 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)

    final_equity = cash
    return BacktestResult(
        candles=len(candles), trades=trades, wins=wins, losses=losses,
        final_equity=round(final_equity, 8),
        metrics={
            "return_pct": round((final_equity / config.initial_capital - 1) * 100, 8),
            "realized_pnl": round(realized, 8),
            "win_rate_pct": round((wins / trades * 100) if trades else 0.0, 8),
            "max_drawdown_pct": round(max_drawdown * 100, 8),
            "expectancy": round(sum(trade_pnls) / trades if trades else 0.0, 8),
            "max_losing_streak": float(max_losing_streak),
            "days_seen": float(len(days_seen)),
        },
    )
