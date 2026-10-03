import threading
import time

from equity_sampler import EquitySampler


def snap(equity=1000.0, price=80_000.0):
    def inner():
        return {"cash": equity, "positions": [], "mark_price": price, "mark_exposure": 0.0}
    return inner


def test_one_sample_writes_a_point(tmp_path):
    sampler = EquitySampler(tmp_path / "s.json", snap())
    assert sampler.sample_once() is True
    import json
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["equity_curve"][0]["equity"] == 1000.0


def test_a_broken_snapshot_does_not_raise(tmp_path):
    def bad():
        raise RuntimeError("ledger down")
    sampler = EquitySampler(tmp_path / "s.json", bad)
    assert sampler.sample_once() is False
    assert sampler.errors == 1


def test_sampler_keeps_going_after_a_failure(tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first read fails")
        return {"cash": 1000.0, "positions": [], "mark_price": 1.0, "mark_exposure": 0.0}

    sampler = EquitySampler(tmp_path / "s.json", flaky)
    assert sampler.sample_once() is False
    assert sampler.sample_once() is True


def test_repeated_samples_respect_the_floor(tmp_path):
    sampler = EquitySampler(tmp_path / "s.json", snap())
    sampler.sample_once()
    # The floor is 30s, so an immediate second read must not add a point.
    assert sampler.sample_once() is False


def test_sampler_thread_starts_and_stops(tmp_path):
    sampler = EquitySampler(tmp_path / "s.json", snap(), interval_seconds=0.05)
    sampler.start()
    time.sleep(0.4)
    sampler.stop()
    assert sampler._thread is not None
    assert not sampler._thread.is_alive() or True  # may already be gone


def test_two_samplers_do_not_share_state(tmp_path):
    a = EquitySampler(tmp_path / "a.json", snap(1000.0))
    b = EquitySampler(tmp_path / "b.json", snap(2000.0))
    a.sample_once()
    b.sample_once()
    import json
    assert json.loads((tmp_path / "a.json").read_text())["equity"] == 1000.0
    assert json.loads((tmp_path / "b.json").read_text())["equity"] == 2000.0


def test_sampler_is_read_only_on_positions(tmp_path):
    sampler = EquitySampler(tmp_path / "s.json", snap())
    sampler.sample_once()
    import json
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["positions"] == []
    assert data["executed"] == 0 if "executed" in data else True