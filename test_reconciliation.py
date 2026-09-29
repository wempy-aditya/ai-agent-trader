from audit_store import AuditStore
from paper_loop import PaperLoop
from risk import TradeProposal


def test_paper_loop_uses_reconciled_exposure(tmp_path):
    loop = PaperLoop(lambda proposal: None, AuditStore(tmp_path / "audit.jsonl"))
    proposal = TradeProposal("new", "buy", "BTC", 50000.0, 0.0001)
    decision = loop.process(proposal, cash=1000.0, current_exposure=817.92, price_age_seconds=0.0, spread_fraction=0.0005)
    assert decision.allowed is False
    assert decision.reason == "max_exposure"
