from hyperliquid_provider import HyperliquidBTC1hProvider


def test_provider_returns_latest_closed_candle_and_drops_unfinished():
    payload = [
        {"t": 1700000000000, "T": 1700003599999, "s": "BTC", "i": "1h", "o": "1", "c": "1.5", "h": "2", "l": "0.5", "v": "10", "n": 1},
        {"t": 1700003600000, "T": 1700007199999, "s": "BTC", "i": "1h", "o": "1.5", "c": "2", "h": "2.5", "l": "1", "v": "10", "n": 1},
    ]
    provider = HyperliquidBTC1hProvider(post_json=lambda body: payload)
    result = provider.latest_closed(now_ms=1700003600000 + 1)
    assert result["timestamp"] == 1700000000000
    assert result["close"] == 1.5


def test_provider_rejects_empty_response():
    provider = HyperliquidBTC1hProvider(post_json=lambda body: [])
    try:
        provider.latest_closed(now_ms=1700000000000)
    except RuntimeError as exc:
        assert str(exc) == "no_candles"
    else:
        raise AssertionError("expected no_candles")
