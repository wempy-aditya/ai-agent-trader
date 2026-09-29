#!/usr/bin/env python3
"""Download pinned public Hyperliquid BTC 1h candles with metadata."""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://api.hyperliquid.xyz/info"
OUT = Path(__file__).parent / "data" / "btc_1h_last365d.json"
START = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp() * 1000)
END = int(datetime.now(timezone.utc).timestamp() * 1000)


def fetch(start: int, end: int) -> list[dict]:
    payload = {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1h", "startTime": start, "endTime": end}}
    request = urllib.request.Request(BASE_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    if not isinstance(result, list):
        raise RuntimeError(f"unexpected response: {result!r}")
    return result


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    candles = []
    chunk = 30 * 24 * 60 * 60 * 1000
    cursor = START
    while cursor < END:
        chunk_end = min(cursor + chunk, END)
        candles.extend(fetch(cursor, chunk_end))
        cursor = chunk_end
        time.sleep(0.1)
    normalized = [
        {"timestamp": int(row["t"]), "open": float(row["o"]), "high": float(row["h"]), "low": float(row["l"]), "close": float(row["c"]), "volume": float(row["v"])}
        for row in candles
    ]
    normalized = list({row["timestamp"]: row for row in normalized}.values())
    normalized.sort(key=lambda row: row["timestamp"])
    OUT.write_text(json.dumps(normalized, indent=2) + "\n")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    metadata = {
        "source": BASE_URL,
        "provider": "Hyperliquid public info API",
        "request": {"coin": "BTC", "interval": "1h", "startTime": START, "endTime": END},
        "date_range_utc": [datetime.fromtimestamp(START / 1000, timezone.utc).isoformat(), datetime.fromtimestamp(END / 1000, timezone.utc).isoformat()],
        "rows": len(normalized),
        "sha256": digest,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT.with_suffix(".metadata.json")).write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
