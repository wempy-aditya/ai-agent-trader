from baseline import Candle
from p5_comparison import compare_baseline_with_mock


def candles():
    return [Candle(i, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i) for i in range(60)]


def test_both_hold_agree_without_execution():
    result = compare_baseline_with_mock(candles(), has_position=False, mock_action="hold")
    assert result.baseline_signal == "hold"
    assert result.agent_action == "hold"
    assert result.relation == "agree"
    assert result.execute is False


def test_mock_buy_against_baseline_hold_is_disagreement_and_valid():
    result = compare_baseline_with_mock(candles(), has_position=False, mock_action="buy")
    assert result.baseline_signal == "hold"
    assert result.agent_action == "buy"
    assert result.relation == "disagree"
    assert result.validation == "valid"
    assert result.execute is False


def test_invalid_sell_is_rejected_before_risk_or_execution():
    result = compare_baseline_with_mock(candles(), has_position=True, mock_action="sell")
    assert result.baseline_signal == "hold"
    assert result.validation == "invalid"
    assert result.reason == "action"
    assert result.execute is False


def test_comparison_is_deterministic():
    first = compare_baseline_with_mock(candles(), False, "buy")
    second = compare_baseline_with_mock(candles(), False, "buy")
    assert first == second
