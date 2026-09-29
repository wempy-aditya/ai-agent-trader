"""Bounded paper observation runner. Disabled by default; no scheduling here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from audit_store import AuditStore


@dataclass(frozen=True)
class ObservationConfig:
    max_cycles: int = 1
    execute: bool = False


@dataclass(frozen=True)
class ObservationResult:
    cycles: int
    executed: int
    stop_reason: str


class ObservationRunner:
    def __init__(self, candles: list, audit: AuditStore, config: ObservationConfig | None = None, cycle: Callable[[object, bool], bool] | None = None):
        self.candles = candles
        self.audit = audit
        self.config = config or ObservationConfig()
        self.cycle = cycle

    def run(self) -> ObservationResult:
        if self.config.max_cycles < 1:
            return ObservationResult(0, 0, "invalid_max_cycles")
        if self.audit.load_state().kill_switch:
            return ObservationResult(0, 0, "kill_switch")
        cycles = 0
        executed = 0
        for index in range(self.config.max_cycles):
            if self.audit.load_state().kill_switch:
                return ObservationResult(cycles, executed, "kill_switch")
            candle = self.candles[index % len(self.candles)] if self.candles else None
            did_execute = bool(self.cycle(candle, self.config.execute)) if self.cycle else False
            cycles += 1
            executed += int(did_execute)
        return ObservationResult(cycles, executed, "max_cycles")
