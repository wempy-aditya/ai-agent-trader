from replay import ReplayConfig, ReplayResult, replay_candles, simulate_baseline, simulate_buy_and_hold


def make_candles(count=300, start=100.0, drift=0.0):
    out = []
    price = start
    for i in range(count):
        price = price * (1.0 + drift)
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
        })
    return out


def stub_agent(actions):
    """Returns a callable matching the agent's propose() contract."""
    seq = list(actions)

    def propose(candle_timestamp, close, baseline_signal, context=None, equity=1000.0):
        action = seq.pop(0) if seq else "hold"
        return {
            "schema_version": "p5.v1",
            "signal_id": f"stub-{candle_timestamp}",
            "candle_timestamp": candle_timestamp,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": action,
            "quantity": 0.0002 if action == "buy" else 0.0,
            "reference_price": close if action == "buy" else 0.0,
            "confidence": 0.5,
            "reason_codes": ["stub"],
            "invalid_conditions": [],
            "baseline_signal": baseline_signal,
            "model_id": "stub",
        }

    return propose


def test_flat_market_baseline_makes_no_money_and_no_loss():
    candles = make_candles(300, start=100.0)
    result = simulate_baseline(candles, ReplayConfig())
    assert result["trades"] == 0
    assert result["final_equity"] == result["initial_capital"]


def test_flat_market_buy_and_hold_charges_costs_and_ends_near_flat():
    candles = make_candles(300, start=100.0)
    result = simulate_buy_and_hold(candles, ReplayConfig())
    # A perfectly flat market still pays both sides, so equity ends slightly
    # below cash. That cost drag is the point of charging it.
    assert result["trades"] == 1
    assert result["final_equity"] < result["initial_capital"]
    assert result["return_pct"] > -1.0


def test_rising_market_buy_and_hold_profits():
    candles = make_candles(200, start=100.0, drift=0.002)
    result = simulate_buy_and_hold(candles, ReplayConfig())
    assert result["trades"] == 1
    assert result["final_equity"] > result["initial_capital"]


def test_rising_market_buy_and_hold_return_is_under_the_raw_move():
    candles = make_candles(200, start=100.0, drift=0.002)
    result = simulate_buy_and_hold(candles, ReplayConfig())
    raw_move = (candles[-1]["close"] - candles[0]["close"]) / candles[0]["close"]
    assert result["return_pct"] < raw_move * 100.0  # costs are charged


def test_falling_market_buy_and_hold_loses():
    candles = make_candles(200, start=100.0, drift=-0.002)
    result = simulate_buy_and_hold(candles, ReplayConfig())
    assert result["final_equity"] < result["initial_capital"]
    assert result["return_pct"] < 0


def test_replay_with_always_hold_agent_matches_cash():
    candles = make_candles(200, start=100.0, drift=0.001)
    agent = stub_agent(["hold"] * 500)
    result = replay_candles(candles, agent, ReplayConfig())
    assert result["executed"] == 0
    assert result["equity"] == ReplayConfig().initial_capital


def test_replay_with_buy_agent_produces_a_trade():
    candles = make_candles(200, start=100.0, drift=0.001)
    agent = stub_agent(["buy"] * 500)
    result = replay_candles(candles, agent, ReplayConfig())
    assert result["executed"] >= 1
    assert result["equity"] > ReplayConfig().initial_capital


def test_replay_records_agent_and_baseline_disagreement():
    candles = make_candles(200, start=100.0, drift=0.001)
    agent = stub_agent(["buy"] * 500)
    result = replay_candles(candles, agent, ReplayConfig())
    assert result["disagreement"] >= 1


def test_replay_never_exceeds_exposure_cap():
    candles = make_candles(300, start=100.0, drift=0.003)
    agent = stub_agent(["buy"] * 500)
    config = ReplayConfig()
    result = replay_candles(candles, agent, config)
    assert result["max_exposure_used"] <= config.max_exposure * 1.0001


def test_replay_counters_add_up():
    candles = make_candles(200, start=100.0, drift=0.001)
    agent = stub_agent(["hold", "buy", "hold", "buy"] * 100)
    result = replay_candles(candles, agent, ReplayConfig())
    assert result["cycles"] == result["hold"] + result["buy"] + result["invalid"]


def test_replay_result_has_no_credential_fields():
    candles = make_candles(120, start=100.0)
    result = replay_candles(candles, stub_agent(["hold"] * 200), ReplayConfig())
    import json
    blob = json.dumps(result).lower()
    for word in ("api_key", "token", "password", "secret", "bearer"):
        assert word not in blob