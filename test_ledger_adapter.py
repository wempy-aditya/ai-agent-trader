from ledger_adapter import LocalPaperLedger
from risk import TradeProposal


def test_ledger_adapter_builds_paper_signal_payload():
    adapter = LocalPaperLedger(base_url="http://127.0.0.1:8000", token="redacted")
    proposal = TradeProposal("s-1", "buy", "BTC", 50000.0, 0.01)
    request = adapter.build_request(proposal)
    assert request["path"] == "/api/signals/realtime"
    assert request["payload"]["market"] == "crypto"
    assert request["payload"]["action"] == "buy"
    assert request["payload"]["executed_at"] == "now"
    assert request["payload"]["content"] == "Hermes P4.1 signal s-1"


def test_ledger_adapter_rejects_non_btc_buy_before_http():
    adapter = LocalPaperLedger(base_url="http://127.0.0.1:8000", token="redacted")
    proposal = TradeProposal("s-2", "sell", "BTC", 50000.0, 0.01)
    try:
        adapter.build_request(proposal)
    except ValueError as exc:
        assert str(exc) == "local paper adapter accepts BTC buy only"
    else:
        raise AssertionError("expected ValueError")
