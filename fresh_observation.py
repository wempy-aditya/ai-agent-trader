"""One-cycle fresh market observation chain; execute remains disabled."""
from __future__ import annotations

from pathlib import Path

from audit_store import AuditStore
from baseline import BacktestConfig, Candle
from fresh_polling import CandlePoller
from paper_loop import PaperLoop, PaperLoopConfig
from signal_observation import build_observation


class FreshObservationRunner:
    def __init__(self, provider, audit_path: str | Path, state_path: str | Path, execute: bool = False, ledger=None):
        self.provider = provider
        self.audit = AuditStore(audit_path, state_path)
        self.config = BacktestConfig()
        self.execute = execute
        self.ledger = ledger
        self.paper_loop = PaperLoop(ledger or (lambda proposal: (_ for _ in ()).throw(RuntimeError("execute_disabled"))), self.audit, config=PaperLoopConfig(execute=execute and ledger is not None))
        self.poller = CandlePoller(self._fetch_latest)
        self._now_ms = 0

    def _fetch_latest(self) -> dict:
        return self.provider.recent_closed(self._now_ms, count=100)[-1]

    def run_cycle(self, now_ms: int, cash: float = 1000.0, current_exposure: float = 0.0, open_position_quantity: float = 0.0) -> dict:
        self._now_ms = now_ms
        polled = self.poller.poll(now_ms)
        if not polled.accepted:
            return {"accepted": False, "reason": polled.reason, "executed": False}
        if self.execute and self.ledger is None:
            return {"accepted": False, "reason": "execute_requires_ledger", "executed": False}
        rows = self.provider.recent_closed(now_ms, count=100)
        candles = [Candle(r["timestamp"], r["open"], r["high"], r["low"], r["close"]) for r in rows if r["timestamp"] <= polled.candle["timestamp"]]
        observation = build_observation(candles, now_ms, self.config)
        decision = self.paper_loop.process_observation(observation, cash=cash, price_age_seconds=0.0, spread_fraction=0.0005, current_exposure=current_exposure, open_position_quantity=open_position_quantity)
        return {"accepted": True, "candle_timestamp": observation.candle_timestamp, "signal": observation.signal, "decision": decision.reason, "executed": decision.reason == "approved_executed"}
