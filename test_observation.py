from audit_store import AuditStore
from observation import ObservationConfig, ObservationRunner


def test_observation_stops_at_cycle_bound(tmp_path):
    runner = ObservationRunner(
        candles=[],
        audit=AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json"),
        config=ObservationConfig(max_cycles=3, execute=False),
    )
    result = runner.run()
    assert result.cycles == 3
    assert result.stop_reason == "max_cycles"
    assert result.executed == 0


def test_observation_defaults_to_dry_run(tmp_path):
    config = ObservationConfig(max_cycles=1)
    assert config.execute is False


def test_observation_stops_when_kill_switch_persisted(tmp_path):
    audit = AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json")
    from audit_store import RuntimeState
    audit.save_state(RuntimeState(True, 0.0, frozenset()))
    result = ObservationRunner([], audit, ObservationConfig(max_cycles=10)).run()
    assert result.stop_reason == "kill_switch"
    assert result.cycles == 0
