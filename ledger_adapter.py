"""Paper-only adapter for AI-Trader local realtime signal endpoint."""
from __future__ import annotations

import json
from urllib.request import Request, urlopen

from risk import TradeProposal


class LocalPaperLedger:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0):
        if not base_url.startswith("http://127.0.0.1:"):
            raise ValueError("local paper adapter requires 127.0.0.1")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def build_request(self, proposal: TradeProposal) -> dict:
        if proposal.action != "buy" or proposal.symbol != "BTC":
            raise ValueError("local paper adapter accepts BTC buy only")
        return {
            "path": "/api/signals/realtime",
            "payload": {
                "market": "crypto",
                "action": "buy",
                "symbol": "BTC",
                "price": proposal.price,
                "quantity": proposal.quantity,
                "content": f"Hermes P4.1 signal {proposal.signal_id}",
                "executed_at": "now",
            },
        }

    def execute(self, proposal: TradeProposal) -> dict:
        request_data = self.build_request(proposal)
        request = Request(
            self.base_url + request_data["path"],
            data=json.dumps(request_data["payload"]).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)
