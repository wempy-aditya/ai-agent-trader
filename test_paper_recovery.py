from audit_store import AuditStore
from paper_loop import PaperLoop, PaperLoopConfig
from risk import RiskContext, RiskGate, RiskLimits, TradeProposal


def test_restart_after_dry_run_rejects_same_signal(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    state_path = tmp_path / "state.json"
    proposal = TradeProposal("s-restart", "buy", "BTC", 50000.0, 0.01)
    first = PaperLoop(lambda _: None, AuditStore(audit_path, state_path), config=PaperLoopConfig(execute=False))
    assert first.process(proposal, 1000.0, 0.0, 0.0005).reason == "approved_dry_run"
    restarted = PaperLoop(lambda _: None, AuditStore(audit_path, state_path), config=PaperLoopConfig(execute=False))
    assert restarted.process(proposal, 1000.0, 0.0, 0.0005).reason == "duplicate_signal"
