"""Fresh closed-candle polling boundary. No scheduler and no execution."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable


@dataclass(frozen=True)
class PollResult:
    accepted: bool
    reason: str
    candle: dict | None


class CandlePoller:
    def __init__(self, fetch_latest: Callable[[], dict], interval_ms: int = 3_600_000):
        self.fetch_latest = fetch_latest
        self.interval_ms = interval_ms
        self.last_candle_timestamp: int | None = None

    def poll(self, now_ms: int) -> PollResult:
        raw = self.fetch_latest()
        try:
            timestamp = int(raw["timestamp"])
            values = [float(raw[key]) for key in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError):
            return PollResult(False, "invalid_candle", None)
        if not all(isfinite(value) and value > 0 for value in values):
            return PollResult(False, "invalid_candle", None)
        if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            return PollResult(False, "invalid_candle", None)
        if timestamp + self.interval_ms > now_ms:
            return PollResult(False, "unfinished_candle", None)
        if self.last_candle_timestamp == timestamp:
            return PollResult(False, "duplicate_candle", None)
        candle = {"timestamp": timestamp, "open": values[0], "high": values[1], "low": values[2], "close": values[3]}
        self.last_candle_timestamp = timestamp
        return PollResult(True, "accepted", candle)
