from dataclasses import asdict

from risk import RiskContext, RiskGate, RiskLimits, TradeProposal


def test_decision_is_serializable_audit_record():
    proposal = TradeProposal("s-42", "buy", "BTC", 50000.0, 0.01)
    context = RiskContext(1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0, 0.0005, False, frozenset())
    decision = RiskGate(RiskLimits()).check(proposal, context)
    record = asdict(decision)
    assert record == {
        "allowed": True,
        "reason": "approved",
        "trade_value": 500.0,
        "resulting_exposure": 500.0,
    }
