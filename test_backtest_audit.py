from backtest import run_backtest
from baseline import BacktestConfig, Candle


def c(i, close, low=None):
    return Candle(i, close, close + 1, low if low is not None else close - 1, close)


def test_metrics_include_expectancy_and_max_losing_streak():
    prices = [120 - i for i in range(50)] + [70 + i * 3 for i in range(17)] + [118 - i * 2 for i in range(20)]
    result = run_backtest([c(i, p) for i, p in enumerate(prices)], BacktestConfig())
    assert "expectancy" in result.metrics
    assert "max_losing_streak" in result.metrics


def test_daily_loss_resets_when_candle_day_changes():
    config = BacktestConfig(max_daily_loss=0.01)
    prices = [120 - i for i in range(50)] + [70 + i * 3 for i in range(17)] + [118 - i * 2 for i in range(20)]
    candles = [c(i * 3_600_000, p) for i, p in enumerate(prices)]
    result = run_backtest(candles, config)
    assert result.metrics["days_seen"] >= 4


def test_configured_ema_periods_are_used():
    prices = [100 + ((i % 6) * 2) for i in range(40)]
    result = run_backtest([c(i, p) for i, p in enumerate(prices)], BacktestConfig(ema_fast=5, ema_slow=10))
    assert result.candles == 40
