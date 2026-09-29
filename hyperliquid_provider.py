"""Minimal Hyperliquid public candle provider; no credentials required."""
from __future__ import annotations

import json
from typing import Callable
from urllib.request import Request, urlopen


class HyperliquidBTC1hProvider:
    def __init__(self, post_json: Callable[[dict], list] | None = None, url: str = "https://api.hyperliquid.xyz/info"):
        self.post_json = post_json or self._request
        self.url = url

    def recent_closed(self, now_ms: int, count: int = 100) -> list[dict]:
        rows = self.post_json({"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1h", "startTime": now_ms - max(count + 2, 3) * 3_600_000, "endTime": now_ms}})
        closed = [row for row in rows if int(row["T"]) < now_ms]
        closed.sort(key=lambda row: int(row["t"]))
        return [{"timestamp": int(row["t"]), "open": float(row["o"]), "high": float(row["h"]), "low": float(row["l"]), "close": float(row["c"])} for row in closed[-count:]]

    def latest_closed(self, now_ms: int) -> dict:
        closed = self.recent_closed(now_ms, count=3)
        if not closed:
            raise RuntimeError("no_candles")
        return closed[-1]


    def _request(self, body: dict) -> list:
        request = Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=15) as response:
            return json.load(response)
