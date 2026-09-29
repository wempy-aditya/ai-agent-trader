from fresh_observation import FreshObservationRunner
from hyperliquid_provider import HyperliquidBTC1hProvider


def test_runner_uses_new_candle_and_builds_observation(tmp_path):
    class Provider:
        def recent_closed(self, now_ms, count):
            return [{"timestamp": i * 3_600_000, "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i} for i in range(1, 30)]
    runner = FreshObservationRunner(Provider(), tmp_path / "audit.jsonl", tmp_path / "state.json")
    result = runner.run_cycle(now_ms=200_000_000)
    assert result["accepted"] is True
    assert result["signal"] in {"hold", "buy"}
    assert result["executed"] is False


def test_runner_skips_duplicate_timestamp(tmp_path):
    class Provider:
        def recent_closed(self, now_ms, count):
            return [{"timestamp": i * 3_600_000, "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i} for i in range(1, 30)]
    runner = FreshObservationRunner(Provider(), tmp_path / "audit.jsonl", tmp_path / "state.json")
    first = runner.run_cycle(now_ms=200_000_000)
    duplicate = runner.run_cycle(now_ms=200_000_000)
    assert first["accepted"] is True
    assert duplicate["accepted"] is False
    assert duplicate["reason"] == "duplicate_candle"
