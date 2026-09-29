from audit_store import AuditStore
from paper_loop import PaperLoop, PaperLoopConfig
from risk import RiskContext, RiskLimits, TradeProposal


def test_rejected_proposal_never_reaches_ledger(tmp_path):
    calls = []
    loop = PaperLoop(
        ledger=lambda proposal: calls.append(proposal),
        audit=AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json"),
        limits=RiskLimits(max_trade_value=100.0),
        config=PaperLoopConfig(execute=False),
    )
    proposal = TradeProposal("s-1", "buy", "BTC", 50000.0, 0.01)
    result = loop.process(proposal, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    assert result.reason == "max_trade_value"
    assert calls == []


def test_approved_dry_run_audits_without_ledger_call(tmp_path):
    calls = []
    loop = PaperLoop(
        ledger=lambda proposal: calls.append(proposal),
        audit=AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json"),
        config=PaperLoopConfig(execute=False),
    )
    proposal = TradeProposal("s-2", "buy", "BTC", 50000.0, 0.01)
    result = loop.process(proposal, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    assert result.allowed is True
    assert result.reason == "approved_dry_run"
    assert calls == []


def test_approved_execute_calls_ledger_once(tmp_path):
    calls = []
    loop = PaperLoop(
        ledger=lambda proposal: calls.append(proposal),
        audit=AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json"),
        config=PaperLoopConfig(execute=True),
    )
    proposal = TradeProposal("s-3", "buy", "BTC", 50000.0, 0.01)
    result = loop.process(proposal, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    assert result.allowed is True
    assert result.reason == "approved_executed"
    assert calls == [proposal]
