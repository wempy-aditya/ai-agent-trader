from fresh_polling import CandlePoller, PollResult


def test_poller_accepts_only_new_closed_candle():
    responses = [
        {"timestamp": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"timestamp": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"timestamp": 4600, "open": 1.5, "high": 2.5, "low": 1, "close": 2},
    ]
    poller = CandlePoller(lambda: responses.pop(0), interval_ms=3600)
    first = poller.poll(now_ms=5000)
    duplicate = poller.poll(now_ms=5000)
    new = poller.poll(now_ms=9000)
    assert first.accepted is True
    assert duplicate.accepted is False
    assert duplicate.reason == "duplicate_candle"
    assert new.accepted is True
    assert poller.last_candle_timestamp == 4600


def test_poller_rejects_unfinished_candle():
    poller = CandlePoller(lambda: {"timestamp": 4600, "open": 1, "high": 2, "low": 0.5, "close": 2}, interval_ms=3600)
    result = poller.poll(now_ms=5000)
    assert result == PollResult(False, "unfinished_candle", None)


def test_poller_rejects_invalid_candle():
    poller = CandlePoller(lambda: {"timestamp": 1000, "open": 1, "high": 2, "low": 0, "close": 0}, interval_ms=3600)
    result = poller.poll(now_ms=5000)
    assert result.reason == "invalid_candle"
