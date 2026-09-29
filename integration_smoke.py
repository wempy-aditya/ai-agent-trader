import tempfile
from pathlib import Path

from audit_store import AuditStore
from paper_loop import PaperLoop, PaperLoopConfig
from risk import TradeProposal


with tempfile.TemporaryDirectory() as directory:
    delivered = []
    store = AuditStore(Path(directory) / "audit.jsonl", Path(directory) / "state.json")
    loop = PaperLoop(delivered.append, store, config=PaperLoopConfig(execute=True))
    proposal = TradeProposal("smoke-1", "buy", "BTC", 50000.0, 0.01)
    decision = loop.process(proposal, cash=1000.0, price_age_seconds=0.0, spread_fraction=0.0005)
    print({"decision": decision.reason, "delivered_count": len(delivered), "signal_id": delivered[0].signal_id})
