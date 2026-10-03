"""Keep the equity curve moving while the trading loop is busy or asleep.

The trading loop only samples equity once per cycle, and a cycle can take a
minute or more when a model is answering. On its own that leaves the chart
looking frozen most of the time, which is exactly the "is it even running?"
feeling this project kept hitting.

The sampler is read-only. It reads the ledger and appends equity points, and it
never touches positions, orders, or the audit trail.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from dashboard import MIN_EQUITY_INTERVAL_S, DashboardState


class EquitySampler:
    def __init__(self, state_path: str | Path, snapshot: Callable[[], dict[str, Any]],
                 interval_seconds: float = MIN_EQUITY_INTERVAL_S,
                 initial_capital: float = 1000.0) -> None:
        self.state_path = Path(state_path)
        self.snapshot = snapshot
        self.interval_seconds = interval_seconds
        self.initial_capital = initial_capital
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors = 0
        # None means healthy. A string means the last tick failed and why.
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="equity-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sample_once(self) -> bool:
        """Take one reading. Returns False on a bad snapshot or a busy file.

        Failures are recorded in `last_error` so a caller can surface them.
        Swallowing them silently is what made a dead sampler look like a
        healthy system with a frozen chart.
        """
        try:
            ledger = self.snapshot()
        except Exception as exc:
            # A ledger hiccup must not kill the sampler; the trading loop
            # reports its own errors and the next tick will usually succeed.
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        if not isinstance(ledger, dict):
            self.errors += 1
            self.last_error = f"snapshot is {type(ledger).__name__}, expected dict"
            return False
        # fetch_snapshot returns 'mark'; a plain ledger read returns
        # 'mark_price'. Accept either so the sampler works with both sources.
        if "mark_price" not in ledger and "mark" in ledger:
            ledger = {**ledger, "mark_price": ledger["mark"]}
        if ledger.get("cash") is None or ledger.get("mark_exposure") is None:
            # No ledger attached (a dry run). Nothing to chart, and that is
            # not an error worth counting.
            self.last_error = None
            return False
        try:
            state = DashboardState(self.state_path, initial_capital=self.initial_capital)
            stored = state.record_equity(ledger)
            self.last_error = None
            return stored
        except (OSError, ValueError) as exc:
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.sample_once()


def run_sampler_forever(state_path: str | Path, snapshot: Callable[[], dict[str, Any]],
                        interval_seconds: float = MIN_EQUITY_INTERVAL_S) -> None:
    sampler = EquitySampler(state_path, snapshot, interval_seconds)
    sampler.start()
    while True:
        time.sleep(3600)