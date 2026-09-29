import json

from audit_store import AuditStore, RuntimeState
from risk import RiskDecision


def test_appends_structured_decision_record(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl")
    decision = RiskDecision(True, "approved", 500.0, 500.0)
    record = store.append_decision(
        signal_id="s-1",
        proposal={"action": "buy", "symbol": "BTC", "price": 50000.0, "quantity": 0.01},
        context={"cash": 1000.0},
        decision=decision,
        timestamp="2026-09-18T20:00:00+07:00",
    )
    assert record["signal_id"] == "s-1"
    assert record["decision"]["reason"] == "approved"
    assert json.loads((tmp_path / "audit.jsonl").read_text())["signal_id"] == "s-1"


def test_runtime_state_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    first = AuditStore(path.with_name("audit.jsonl"), state_path=path)
    first.save_state(RuntimeState(kill_switch=True, daily_realized_loss=30.0, seen_signal_ids=frozenset({"s-1"})))

    restarted = AuditStore(path.with_name("audit.jsonl"), state_path=path)
    state = restarted.load_state()
    assert state.kill_switch is True
    assert state.daily_realized_loss == 30.0
    assert state.seen_signal_ids == frozenset({"s-1"})


def test_state_write_is_replaced_atomically(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl", state_path=tmp_path / "state.json")
    store.save_state(RuntimeState(kill_switch=False, daily_realized_loss=0.0, seen_signal_ids=frozenset()))
    assert not list(tmp_path.glob("state.json.tmp-*"))
