"""Read-only paper dashboard state. No order endpoint, no credentials.

The state file is the single source of truth for the dashboard and is written
by the trading loop, read by the HTTP server. It is deliberately read-only on
the serving side: the browser can look, never act.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MAX_HISTORY = 50
# One equity point per cycle would grow without bound in an always-on run.
# 500 points is still a readable chart and keeps the state file small.
MAX_EQUITY_POINTS = 500
# Floor between equity readings. The trading loop can be slow while a model
# answers, and a chart needs points in between those moments or it looks frozen.
MIN_EQUITY_INTERVAL_S = 30.0


def _now_ms() -> int:
    return int(time.time() * 1000)


class DashboardState:
    def __init__(self, state_path: str | Path, reset: bool = False,
                 initial_capital: float = 1000.0) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_capital = initial_capital
        self.data: dict[str, Any] = {
            "status": "starting",
            "model": None,
            "execute": False,
            "live_trading": "DISABLED",
            "cycles": 0,
            "accepted": 0,
            "executed": 0,
            "invalid": 0,
            "initial_capital": initial_capital,
            "cash": None,
            "equity": None,
            "pnl_usdt": None,
            "return_pct": None,
            "peak_equity": None,
            "positions": [],
            "mark_price": None,
            "mark_exposure": None,
            "max_exposure": 500.0,
            "last_cycle": None,
            "history": [],
            "equity_curve": [],
            # When this run began. The supervisor reads it to tell a crash loop
            # apart from a process that stayed up for a full cycle.
            "started_at_ms": None,
            "errors": [],
        }
        if self.state_path.exists() and not reset:
            try:
                stored = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self.data.update(stored)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        tmp = self.state_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.state_path)

    @contextmanager
    def _locked(self):
        """Serialise read-modify-write against other writers.

        The sampler thread and the trading loop both own a DashboardState for
        the same file. Without a lock the slower writer silently reverts the
        faster one's fields, and a shared temp filename lets one writer
        clobber the other's half-written file. Under the lock the file on disk
        is authoritative for everything the caller is not explicitly changing.
        """
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(str(self.state_path) + ".lock", "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            stored = self._read_disk()
            if stored is not None:
                self.data = stored
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _read_disk(self) -> dict[str, Any] | None:
        try:
            stored = json.loads(self.state_path.read_text(encoding="utf-8"))
            return stored if isinstance(stored, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def update(self, **fields: Any) -> None:
        with self._locked():
            self.data.update(fields)
            self.save()

    def set_ledger(self, cash: float | None, positions: list[dict], mark_price: float | None, mark_exposure: float | None) -> None:
        self.update(cash=cash, positions=positions, mark_price=mark_price, mark_exposure=mark_exposure)

    def record_equity(self, ledger: dict[str, Any], force: bool = False) -> bool:
        """Append one point to the equity curve and refresh the P/L figures.

        Equity is cash plus the marked value of open positions, so a position
        that is up shows a gain even before it is sold. Reporting cash alone
        would make every open trade look like a loss.

        Returns True when a point was stored. Readings closer together than
        MIN_EQUITY_INTERVAL_S are skipped unless forced, which lets a sampler
        fill in the curve between slow trading cycles without flooding it. A
        skipped reading still updates the headline equity and P/L: only the
        chart point is throttled, never the current numbers.
        """
        cash = ledger.get("cash")
        exposure = ledger.get("mark_exposure")
        if not isinstance(cash, (int, float)) or not isinstance(exposure, (int, float)):
            self.set_ledger(cash, ledger.get("positions", []),
                            ledger.get("mark_price"), ledger.get("mark_exposure"))
            return False

        now_ms = ledger.get("at_ms") or _now_ms()
        equity = float(cash) + float(exposure)

        with self._locked():
            curve = list(self.data.get("equity_curve", []))
            if not force and curve:
                last_at = curve[-1].get("at_ms")
                if isinstance(last_at, int) and (now_ms - last_at) < MIN_EQUITY_INTERVAL_S * 1000:
                    self._write_headlines(ledger, equity, curve)
                    return False

            curve.append({
                "equity": round(equity, 4),
                "cash": round(float(cash), 4),
                "mark_price": ledger.get("mark_price"),
                "at_ms": now_ms,
            })
            self._write_headlines(ledger, equity, curve[-MAX_EQUITY_POINTS:])
            return True

    def _write_headlines(self, ledger: dict[str, Any], equity: float,
                         curve: list[dict[str, Any]]) -> None:
        """Write current equity, P/L and drawdown, optionally without a new point."""
        cash = ledger.get("cash")
        exposure = ledger.get("mark_exposure")
        # Peak is measured across the chart plus the live reading, so a gain
        # that has not been charted yet still raises the high-water mark.
        peak = max([p["equity"] for p in curve if isinstance(p.get("equity"), (int, float))]
                   + [equity, self.initial_capital])

        # Baseline is the first equity reading of this session, not the nominal
        # capital. A ledger can already hold a position from an earlier test
        # run, and measuring against 1,000.00 would report that old position's
        # gain as this agent's profit. Both numbers stay visible so neither is
        # mistaken for the other.
        baseline = self.data.get("baseline_equity")
        if not isinstance(baseline, (int, float)):
            baseline = equity
            self.data["baseline_equity"] = round(equity, 4)
            self.data["baseline_at_ms"] = ledger.get("at_ms")

        # Write via self.data directly. Calling self.update() here would re-enter
        # the lock and re-read the file, discarding the baseline set above.
        self.data.update({
            "cash": round(float(cash), 4) if isinstance(cash, (int, float)) else None,
            "positions": ledger.get("positions", []),
            "mark_price": ledger.get("mark_price"),
            "mark_exposure": round(float(exposure), 4) if isinstance(exposure, (int, float)) else None,
            "equity": round(equity, 4),
            "pnl_usdt": round(equity - baseline, 4),
            "return_pct": round((equity / baseline - 1) * 100, 4) if baseline else 0.0,
            "total_pnl_usdt": round(equity - self.initial_capital, 4),
            "peak_equity": round(peak, 4),
            "max_drawdown_pct": round(max(0.0, (peak - equity) / peak * 100), 4) if peak else 0.0,
            "equity_curve": curve,
        })
        self.save()

    def add_cycle(self, cycle: dict[str, Any]) -> None:
        with self._locked():
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
        with self._locked():
            errors = self.data.get("errors", [])
            errors.append(message)
            self.data["errors"] = errors[-20:]
            self.save()
