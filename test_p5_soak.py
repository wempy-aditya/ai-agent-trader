import json

import pytest

from p5_soak import SoakRunner, SoakStopped


def rising_candles(count=60, start=100.0):
    return [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000, "open": start + i, "high": start + i + 1, "low": start + i - 1, "close": start + i}
        for i in range(count)
    ]


def test_agree_hold_cycle_records_without_execution(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["hold"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
    )
    report = runner.run()
    assert report["cycles"] == 1
    assert report["agreement"] == 1
    assert report["disagreement"] == 0
    assert report["invalid"] == 0
    assert report["executed"] == 0
    assert report["stop_reason"] == "max_cycles"
    assert report["execute"] is False


def test_buy_disagreement_is_valid_but_not_executed(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["buy"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
    )
    report = runner.run()
    assert report["disagreement"] == 1
    assert report["valid_proposals"] == 1
    assert report["executed"] == 0
    assert report["buy_proposals"] == 1


def test_invalid_agent_output_is_counted_and_isolated(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["sell", "hold"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
    )
    report = runner.run()
    assert report["cycles"] == 2
    assert report["invalid"] == 1
    assert report["invalid_reasons"] == {"action": 1}
    assert report["executed"] == 0


def test_stale_candle_proposal_is_rejected(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["hold"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
        stale_candle_offset_ms=3_600_000,
    )
    report = runner.run()
    assert report["invalid"] == 1
    assert report["invalid_reasons"] == {"candle_timestamp": 1}


def test_duplicate_signal_id_is_rejected(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["hold", "hold"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
        duplicate_signal_ids=True,
    )
    report = runner.run()
    assert report["invalid"] == 1
    assert report["invalid_reasons"] == {"duplicate_signal_id": 1}


def test_missing_ledger_stops_soak_before_execution(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["buy"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
        execute=True,
    )
    with pytest.raises(SoakStopped):
        runner.run()


def test_evidence_and_audit_files_are_written(tmp_path):
    runner = SoakRunner(
        candles=rising_candles(),
        agent_actions=["hold", "buy"],
        evidence_path=tmp_path / "soak.jsonl",
        audit_path=tmp_path / "soak.audit.jsonl",
    )
    runner.run()
    evidence = [json.loads(line) for line in (tmp_path / "soak.jsonl").read_text().splitlines() if line]
    audit = [json.loads(line) for line in (tmp_path / "soak.audit.jsonl").read_text().splitlines() if line]
    assert len(evidence) == 2
    assert len(audit) == 2
    assert audit[0]["decision"]["reason"] == "hold"
    assert audit[0]["decision"]["allowed"] is False
    assert audit[1]["decision"]["allowed"] is True
    assert audit[1]["decision"]["reason"] == "approved"


def test_report_is_deterministic(tmp_path):
    first = SoakRunner(candles=rising_candles(), agent_actions=["hold", "buy"], evidence_path=tmp_path / "a.jsonl", audit_path=tmp_path / "a.audit.jsonl").run()
    second = SoakRunner(candles=rising_candles(), agent_actions=["hold", "buy"], evidence_path=tmp_path / "b.jsonl", audit_path=tmp_path / "b.audit.jsonl").run()
    keys = ("cycles", "valid_proposals", "invalid", "invalid_reasons", "agreement", "disagreement", "buy_proposals", "executed", "execute", "stop_reason")
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}
    assert (tmp_path / "a.jsonl").read_text() == (tmp_path / "b.jsonl").read_text()
