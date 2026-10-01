"""Read-only paper dashboard state. No order endpoint, no credentials."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_HISTORY = 50


class DashboardState:
    def __init__(self, state_path: str | Path):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {
            "status": "starting",
            "model": None,
            "execute": False,
            "live_trading": "DISABLED",
            "cycles": 0,
            "accepted": 0,
            "executed": 0,
            "invalid": 0,
            "cash": None,
            "positions": [],
            "mark_price": None,
            "mark_exposure": None,
            "max_exposure": 500.0,
            "last_cycle": None,
            "history": [],
            "errors": [],
        }
        if self.state_path.exists():
            try:
                stored = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self.data.update(stored)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_path)

    def update(self, **fields: Any) -> None:
        self.data.update(fields)
        self.save()

    def set_ledger(self, cash: float | None, positions: list[dict], mark_price: float | None, mark_exposure: float | None) -> None:
        self.update(cash=cash, positions=positions, mark_price=mark_price, mark_exposure=mark_exposure)

    def add_cycle(self, cycle: dict[str, Any]) -> None:
        history = self.data.get("history", [])
        history.append(cycle)
        self.data["history"] = history[-MAX_HISTORY:]
        self.data["last_cycle"] = cycle
        self.data["cycles"] = int(self.data.get("cycles", 0)) + 1
        if cycle.get("accepted"):
            self.data["accepted"] = int(self.data.get("accepted", 0)) + 1
        if cycle.get("executed"):
            self.data["executed"] = int(self.data.get("executed", 0)) + 1
        if cycle.get("validation") == "invalid":
            self.data["invalid"] = int(self.data.get("invalid", 0)) + 1
        self.save()

    def add_error(self, message: str) -> None:
        errors = self.data.get("errors", [])
        errors.append(message)
        self.data["errors"] = errors[-20:]
        self.save()
