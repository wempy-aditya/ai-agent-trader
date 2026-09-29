from backtest import BacktestResult, run_backtest
from baseline import BacktestConfig, Candle


def candle(i, close):
    return Candle(timestamp=i, open=close, high=close + 1, low=close - 1, close=close)


def test_backtest_returns_metrics_and_trades():
    prices = [120 - i for i in range(50)] + [70 + i * 3 for i in range(17)]
    prices += [118 - i * 2 for i in range(20)]
    result = run_backtest([candle(i, p) for i, p in enumerate(prices)], BacktestConfig())
    assert isinstance(result, BacktestResult)
    assert result.candles == len(prices)
    assert result.trades >= 1
    assert "return_pct" in result.metrics


def test_backtest_is_deterministic():
    prices = [100 + ((i % 8) * 2) for i in range(80)]
    candles = [candle(i, p) for i, p in enumerate(prices)]
    assert run_backtest(candles, BacktestConfig()) == run_backtest(candles, BacktestConfig())
