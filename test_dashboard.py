from dashboard import MAX_EQUITY_POINTS, MAX_HISTORY, DashboardState


def test_state_starts_fresh_when_reset(tmp_path):
    path = tmp_path / "state.json"
    first = DashboardState(path)
    first.update(model="a", cycles=7)
    second = DashboardState(path, reset=True)
    assert second.data["cycles"] == 0
    assert second.data["model"] is None


def test_state_keeps_history_when_not_reset(tmp_path):
    path = tmp_path / "state.json"
    first = DashboardState(path)
    first.update(model="a")
    second = DashboardState(path)
    assert second.data["model"] == "a"


def test_add_cycle_counts_and_keeps_last_cycle(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.add_cycle({"accepted": True, "executed": False, "validation": "valid"})
    state.add_cycle({"accepted": False, "executed": True, "validation": "invalid"})
    assert state.data["cycles"] == 2
    assert state.data["accepted"] == 1
    assert state.data["executed"] == 1
    assert state.data["invalid"] == 1
    assert state.data["last_cycle"]["validation"] == "invalid"


def test_history_is_capped(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    for _ in range(MAX_HISTORY + 25):
        state.add_cycle({"accepted": True})
    assert len(state.data["history"]) == MAX_HISTORY


def test_equity_point_records_cash_plus_exposure(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.record_equity({"cash": 900.0, "mark_price": 80_000.0, "mark_exposure": 100.0})
    assert state.data["equity"] == 1000.0


def test_equity_curve_starts_with_initial_capital(tmp_path):
    state = DashboardState(tmp_path / "s.json", initial_capital=1000.0)
    state.record_equity({"cash": 1000.0, "mark_price": 80_000.0, "mark_exposure": 0.0})
    assert state.data["equity_curve"][0]["equity"] == 1000.0


def test_equity_curve_is_capped(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    # force=True because the loop below fires far faster than the 30s floor.
    for i in range(MAX_EQUITY_POINTS + 40):
        state.record_equity({"cash": 1000.0 + i, "mark_price": 80_000.0, "mark_exposure": 0.0}, force=True)
    assert len(state.data["equity_curve"]) == MAX_EQUITY_POINTS


def test_return_and_pnl_are_reported_beside_the_curve(tmp_path):
    state = DashboardState(tmp_path / "s.json", initial_capital=1000.0)
    state.record_equity({"cash": 950.0, "mark_price": 80_000.0, "mark_exposure": 100.0})
    state.record_equity({"cash": 950.0, "mark_price": 81_000.0, "mark_exposure": 100.0})
    assert state.data["pnl_usdt"] == 50.0
    assert state.data["return_pct"] == 5.0


def test_equity_is_none_until_the_first_reading(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    assert state.data["equity"] is None
    assert state.data["pnl_usdt"] is None


def test_curve_points_carry_the_mark_price_for_charting(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.record_equity({"cash": 1000.0, "mark_price": 77_777.0, "mark_exposure": 0.0})
    assert state.data["equity_curve"][0]["mark_price"] == 77_777.0


def test_equity_point_carries_a_timestamp_for_the_x_axis(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": 0.0, "at_ms": 1_700_000_000_000})
    assert state.data["equity_curve"][0]["at_ms"] == 1_700_000_000_000


def test_close_readings_do_not_flood_the_curve(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    base = 1_700_000_000_000
    assert state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": 0.0, "at_ms": base})
    # Ten seconds later is inside the floor, so it must not be stored.
    assert not state.record_equity({"cash": 1000.0, "mark_price": 2.0, "mark_exposure": 0.0, "at_ms": base + 10_000})
    assert len(state.data["equity_curve"]) == 1


def test_a_later_reading_is_stored(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    base = 1_700_000_000_000
    state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": 0.0, "at_ms": base})
    assert state.record_equity({"cash": 1000.0, "mark_price": 2.0, "mark_exposure": 0.0, "at_ms": base + 60_000})
    assert len(state.data["equity_curve"]) == 2


def test_force_bypasses_the_floor(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    base = 1_700_000_000_000
    state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": 0.0, "at_ms": base})
    assert state.record_equity({"cash": 1000.0, "mark_price": 2.0, "mark_exposure": 0.0, "at_ms": base}, force=True)
    assert len(state.data["equity_curve"]) == 2


def test_a_skipped_reading_still_refreshes_the_headline_figures(tmp_path):
    state = DashboardState(tmp_path / "s.json", initial_capital=1000.0)
    base = 1_700_000_000_000
    state.record_equity({"cash": 1000.0, "mark_price": 80_000.0, "mark_exposure": 0.0, "at_ms": base})
    state.record_equity({"cash": 940.0, "mark_price": 80_000.0, "mark_exposure": 0.0, "at_ms": base + 1_000})
    # Cash moved even though the curve point was throttled.
    assert state.data["cash"] == 940.0
    assert state.data["equity"] == 940.0


def test_missing_exposure_is_not_charted(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    assert state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": None}) is False
    assert state.data["equity_curve"] == []


# The sampler thread and the trading loop hold separate DashboardState objects
# for the same file. Before the lock existed the slower writer silently
# reverted the faster one's fields, which froze the equity curve on screen.


def test_a_second_writer_does_not_revert_the_first(tmp_path):
    path = tmp_path / "s.json"
    loop_state = DashboardState(path)
    loop_state.update(status="running", cycles=5)
    sampler_state = DashboardState(path)  # stale copy held by the sampler
    sampler_state.update(cash=999.0)
    assert DashboardState(path).data["cycles"] == 5


def test_both_writers_survive_each_other(tmp_path):
    path = tmp_path / "s.json"
    a = DashboardState(path)
    a.update(status="running", cycles=3)
    b = DashboardState(path)
    b.update(equity=1010.0, pnl_usdt=10.0)
    final = DashboardState(path).data
    assert final["cycles"] == 3
    assert final["equity"] == 1010.0


def test_concurrent_writers_do_not_corrupt_the_file(tmp_path):
    import json
    import threading
    path = tmp_path / "s.json"
    DashboardState(path).update(status="running")

    def hammer(tag: str):
        state = DashboardState(path)
        for i in range(40):
            state.update(**{tag: i})

    threads = [threading.Thread(target=hammer, args=(t,))
               for t in ("cycles", "equity", "cash")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = DashboardState(path).data
    assert final["status"] == "running"
    assert isinstance(final["equity"], (int, float))


def test_the_curve_is_not_lost_to_a_concurrent_cycle_write(tmp_path):
    import json
    path = tmp_path / "s.json"
    state = DashboardState(path)
    base = 1_700_000_000_000
    state.record_equity({"cash": 1000.0, "mark_price": 80_000.0, "mark_exposure": 0.0, "at_ms": base})
    # The trading loop writes a cycle while the sampler holds its own state.
    DashboardState(path).add_cycle({"accepted": True, "executed": False, "validation": "valid"})
    fresh = DashboardState(path)
    assert len(fresh.data["equity_curve"]) == 1
    assert fresh.data["cycles"] == 1


def test_no_stray_temp_or_lock_files_are_left_behind(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.update(status="ok")
    state.record_equity({"cash": 1000.0, "mark_price": 1.0, "mark_exposure": 0.0})
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["s.json", "s.json.lock"]
