from audit_store import AuditStore, RuntimeState
from risk import RiskContext, RiskGate, RiskLimits, TradeProposal


def test_restarted_runtime_rejects_previously_seen_signal(tmp_path):
    store = AuditStore(tmp_path / "audit.jsonl", state_path=tmp_path / "state.json")
    store.save_state(RuntimeState(False, 0.0, frozenset({"s-1"})))
    state = store.load_state()
    context = RiskContext(1000.0, 1000.0, state.daily_realized_loss, 0.0, 0.0, 0.0, 0.0005, state.kill_switch, state.seen_signal_ids)
    proposal = TradeProposal("s-1", "buy", "BTC", 50000.0, 0.01)
    assert RiskGate(RiskLimits()).check(proposal, context).reason == "duplicate_signal"
