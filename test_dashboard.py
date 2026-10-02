from dashboard import DashboardState


def test_state_starts_fresh_when_reset(tmp_path):
    path = tmp_path / "state.json"
    first = DashboardState(path)
    first.update(model="old-model")
    first.add_cycle({"cycle": 1, "agent_action": "hold"})

    second = DashboardState(path, reset=True)
    assert second.data["model"] is None
    assert second.data["history"] == []
    assert second.data["cycles"] == 0


def test_state_keeps_history_without_reset(tmp_path):
    path = tmp_path / "state.json"
    DashboardState(path).update(model="m")
    loaded = DashboardState(path)
    assert loaded.data["model"] == "m"


def test_cycles_and_counters_increment(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    state.add_cycle({"cycle": 1, "agent_action": "hold"})
    state.add_cycle({"cycle": 2, "agent_action": "buy"})
    assert state.data["cycles"] == 2
    assert state.data["last_cycle"]["cycle"] == 2
    assert len(state.data["history"]) == 2


def test_history_is_capped(tmp_path):
    state = DashboardState(tmp_path / "s.json")
    for index in range(80):
        state.add_cycle({"cycle": index})
    assert len(state.data["history"]) == 50
    assert state.data["last_cycle"]["cycle"] == 79