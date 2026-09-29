"""Append-only risk audit and durable runtime state for local paper mode."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from risk import RiskDecision


@dataclass(frozen=True)
class RuntimeState:
    kill_switch: bool
    daily_realized_loss: float
    seen_signal_ids: frozenset[str]


class AuditStore:
    def __init__(self, audit_path: str | Path, state_path: str | Path | None = None):
        self.audit_path = Path(audit_path)
        self.state_path = Path(state_path) if state_path else self.audit_path.with_suffix(".state.json")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def append_decision(
        self,
        signal_id: str,
        proposal: dict[str, Any],
        context: dict[str, Any],
        decision: RiskDecision,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "signal_id": signal_id,
            "proposal": proposal,
            "context": context,
            "decision": asdict(decision),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def append_observation(self, observation: Any, decision: RiskDecision) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal_id": f"observation-{observation.candle_timestamp}",
            "signal": observation.signal,
            "candle_timestamp": observation.candle_timestamp,
            "used_candle_count": observation.used_candle_count,
            "proposal": None,
            "decision": asdict(decision),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def read_records(self) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def save_state(self, state: RuntimeState) -> None:
        payload = {
            "kill_switch": state.kill_switch,
            "daily_realized_loss": state.daily_realized_loss,
            "seen_signal_ids": sorted(state.seen_signal_ids),
        }
        fd, temp_name = tempfile.mkstemp(prefix=self.state_path.name + ".tmp-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load_state(self) -> RuntimeState:
        if not self.state_path.exists():
            return RuntimeState(False, 0.0, frozenset())
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return RuntimeState(
            kill_switch=bool(payload["kill_switch"]),
            daily_realized_loss=float(payload["daily_realized_loss"]),
            seen_signal_ids=frozenset(payload["seen_signal_ids"]),
        )
