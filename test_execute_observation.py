from pathlib import Path
from audit_store import AuditStore
from fresh_observation import FreshObservationRunner


def test_execute_cycle_uses_ledger_and_returns_execution(tmp_path):
    class Provider:
        def recent_closed(self, now_ms, count):
            return [{"timestamp": i * 3_600_000, "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i} for i in range(1, 30)]
    calls = []
    runner = FreshObservationRunner(Provider(), tmp_path / "audit.jsonl", tmp_path / "state.json", execute=True, ledger=lambda p: calls.append(p))
    result = runner.run_cycle(now_ms=200_000_000)
    assert result["accepted"] is True
    assert result["executed"] is False
    assert calls == []
