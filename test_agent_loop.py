from pathlib import Path

from agent_loop import AgentCycleResult, AgentTradingLoop


def candles(count=120, start=100.0):
    return [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000, "open": start + i, "high": start + i + 2, "low": start + i - 2, "close": start + i + 1}
        for i in range(count)
    ]


def make_loop(tmp_path, llm_raw, ledger=None, **kwargs):
    class Provider:
        def recent_closed(self, now_ms, count=100):
            return candles(count)

    class Agent:
        def propose(self, candle_timestamp, close, baseline_signal, context=None, equity=1000.0):
            return llm_raw

        def available(self):
            return True

    return AgentTradingLoop(
        provider=Provider(),
        agent=Agent(),
        audit_path=Path(tmp_path / "agent.audit.jsonl"),
        state_path=Path(tmp_path / "agent.state.json"),
        evidence_path=Path(tmp_path / "agent.jsonl"),
        ledger=ledger,
        **kwargs,
    )


def test_hold_cycle_never_executes(tmp_path):
    from llm_agent import LocalLLMAgent

    hold = LocalLLMAgent(model="stub", complete=lambda p, o: '{"action": "hold", "confidence": 0.3, "reason_codes": ["flat"]}')
    loop = AgentTradingLoop(
        provider=type("P", (), {"recent_closed": lambda self, now_ms, count=100: candles(count)})(),
        agent=hold,
        audit_path=Path(tmp_path / "a.audit.jsonl"),
        state_path=Path(tmp_path / "a.state.json"),
        evidence_path=Path(tmp_path / "a.jsonl"),
    )
    result = loop.run_cycle(now_ms=1_700_000_000_000 + 200 * 3_600_000, cash=1000.0, current_exposure=0.0, open_position_quantity=0.0)
    assert result.accepted is True
    assert result.agent_action == "hold"
    assert result.executed is False
    assert result.relation in {"agree", "disagree"}


def test_buy_cycle_with_ledger_executes_once(tmp_path):
    calls = []

    def ledger(proposal):
        calls.append(proposal)

    from llm_agent import LocalLLMAgent
    import json

    buy_raw = json.dumps({
        "schema_version": "p5.v1",
        "signal_id": "llm-buy-1",
        "candle_timestamp": 1_700_000_000_000 + 119 * 3_600_000,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "buy",
        "quantity": 0.00005,
        "reference_price": 80_000.0,
        "confidence": 0.6,
        "reason_codes": ["ema_cross"],
        "invalid_conditions": [],
        "baseline_signal": "buy",
        "model_id": "stub",
    })
    agent = LocalLLMAgent(model="stub", complete=lambda p, o: buy_raw)
    loop = AgentTradingLoop(
        provider=type("P", (), {"recent_closed": lambda self, now_ms, count=100: candles(count)})(),
        agent=agent,
        audit_path=Path(tmp_path / "b.audit.jsonl"),
        state_path=Path(tmp_path / "b.state.json"),
        evidence_path=Path(tmp_path / "b.jsonl"),
        ledger=ledger,
        execute=True,
    )
    result = loop.run_cycle(now_ms=1_700_000_000_000 + 200 * 3_600_000, cash=1000.0, current_exposure=0.0, open_position_quantity=0.0)
    assert result.executed is True
    assert len(calls) == 1
    assert calls[0].action == "buy"


def test_duplicate_candle_is_skipped(tmp_path):
    from llm_agent import LocalLLMAgent

    agent = LocalLLMAgent(model="stub", complete=lambda p, o: '{"action": "hold"}')
    loop = AgentTradingLoop(
        provider=type("P", (), {"recent_closed": lambda self, now_ms, count=100: candles(count)})(),
        agent=agent,
        audit_path=Path(tmp_path / "c.audit.jsonl"),
        state_path=Path(tmp_path / "c.state.json"),
        evidence_path=Path(tmp_path / "c.jsonl"),
    )
    now = 1_700_000_000_000 + 200 * 3_600_000
    first = loop.run_cycle(now_ms=now, cash=1000.0, current_exposure=0.0, open_position_quantity=0.0)
    second = loop.run_cycle(now_ms=now, cash=1000.0, current_exposure=0.0, open_position_quantity=0.0)
    assert first.accepted is True
    assert second.accepted is False
    assert second.reason == "duplicate_candle"


def test_execute_without_ledger_is_refused(tmp_path):
    from llm_agent import LocalLLMAgent

    agent = LocalLLMAgent(model="stub", complete=lambda p, o: '{"action": "hold"}')
    loop = AgentTradingLoop(
        provider=type("P", (), {"recent_closed": lambda self, now_ms, count=100: candles(count)})(),
        agent=agent,
        audit_path=Path(tmp_path / "d.audit.jsonl"),
        state_path=Path(tmp_path / "d.state.json"),
        evidence_path=Path(tmp_path / "d.jsonl"),
        execute=True,
    )
    result = loop.run_cycle(now_ms=1_700_000_000_000 + 200 * 3_600_000, cash=1000.0, current_exposure=0.0, open_position_quantity=0.0)
    assert result.accepted is False
    assert result.reason == "execute_requires_ledger"
