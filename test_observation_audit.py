from audit_store import AuditStore
from paper_loop import PaperLoop
from risk import RiskDecision
from signal_observation import SignalObservation


def test_hold_observation_is_audited_without_risk_or_ledger(tmp_path):
    audit = AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json")
    called = []
    loop = PaperLoop(lambda proposal: called.append(proposal), audit)
    observation = SignalObservation("hold", 123, 60, None)
    result = loop.process_observation(observation, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    assert result == RiskDecision(False, "hold", 0.0, 0.0)
    assert called == []
    record = audit.read_records()[-1]
    assert record["signal"] == "hold"


def test_buy_observation_dry_run_creates_audit_without_ledger(tmp_path):
    audit = AuditStore(tmp_path / "audit.jsonl", tmp_path / "state.json")
    called = []
    loop = PaperLoop(lambda proposal: called.append(proposal), audit)
    from risk import TradeProposal
    observation = SignalObservation("buy", 123, 60, TradeProposal("sig-1", "buy", "BTC", 50000.0, 0.0001))
    result = loop.process_observation(observation, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    assert result.reason == "approved_dry_run"
    assert called == []
    assert audit.read_records()[-1]["decision"]["reason"] == "approved"
