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


class EntryStub:
    """Entry-aware stub: buys only when the entry criteria are all true."""

    model_id = "entry-stub"

    def available(self):
        return True

    def build_criteria(self, context):
        from entry_agent import entry_criteria

        return entry_criteria(context)

    def build_exit_criteria(self, context, has_position=False, entry_price=None):
        from entry_agent import build_exit_criteria

        return build_exit_criteria(context, has_position, entry_price)

    def propose(self, candle_timestamp, close, baseline_signal, context=None, equity=1000.0, has_position=False, entry_price=None):
        from entry_agent import entry_criteria

        criteria = entry_criteria(context)
        if has_position:
            action = "sell"
        elif all(criteria.values()):
            action = "buy"
        else:
            action = "hold"
        return {
            "schema_version": "p5.v1", "signal_id": f"e-{candle_timestamp}",
            "candle_timestamp": candle_timestamp, "symbol": "BTC", "timeframe": "1h",
            "action": action, "quantity": 0.0002 if action == "buy" else 0.0,
            "reference_price": close if action == "buy" else 0.0,
            "confidence": 0.6, "reason_codes": ["stub"], "invalid_conditions": [],
            "baseline_signal": baseline_signal, "model_id": self.model_id,
        }


def wavy_candles(count=500, start=100.0, drift=0.0004, vol=0.004, seed=7):
    """Deterministic random walk with realistic bar-to-bar noise.

    A pure sine wave is not usable here: it pins RSI at its extremes, so the
    entry criteria can never all hold. Real BTC bars wander, which is what makes
    RSI sit in the mid band often enough to trade.
    """
    import random

    rng = random.Random(seed)
    out = []
    price = start
    for i in range(count):
        price = max(1.0, price * (1.0 + drift + rng.gauss(0.0, vol)))
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price,
            "high": price * 1.004,
            "low": price * 0.996,
            "close": price,
        })
    return out


def test_entry_aware_replay_can_buy_and_sell_a_round_trip():
    candles = wavy_candles(500)
    result = replay_candles(candles, EntryStub(), ReplayConfig())
    assert result["trades"] >= 2  # at least one round trip
    assert result["wins"] + result["losses"] >= 1


def test_entry_aware_replay_passes_position_state_to_the_agent():
    seen = []

    class Recorder(EntryStub):
        def propose(self, candle_timestamp, close, baseline_signal, context=None, equity=1000.0, has_position=False, entry_price=None):
            seen.append(has_position)
            return super().propose(candle_timestamp, close, baseline_signal, context, equity, has_position, entry_price)

    replay_candles(wavy_candles(500), Recorder(), ReplayConfig())
    assert True in seen  # it did open a position at some point


def test_entry_aware_replay_never_holds_two_positions():
    candles = wavy_candles(500)
    result = replay_candles(candles, EntryStub(), ReplayConfig())
    assert result["max_exposure_used"] <= ReplayConfig().max_exposure * 1.0001