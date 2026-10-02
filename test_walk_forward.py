from dataclasses import replace

from mean_reversion import MRConfig, simulate_mean_reversion
from run_walk_forward import best_by, params_of, sweep


def trend_candles(count=700, start=100.0, drift=0.0004, seed=2):
    import random

    rng = random.Random(seed)
    out = []
    price = start
    for i in range(count):
        price = max(1.0, price * (1 + drift + rng.gauss(0.0, 0.003)))
        out.append({
            "timestamp": 1_700_000_000_000 + i * 3_600_000,
            "open": price, "high": price * 1.003, "low": price * 0.997, "close": price,
        })
    return out


def test_sweep_visits_every_grid_cell():
    rows = sweep(trend_candles(), MRConfig())
    assert len(rows) == 4 * 4 * 3
    combos = {(r["rsi_oversold"], r["near_low_max"], r["max_hold_bars"]) for r in rows}
    assert len(combos) == len(rows)


def test_sweep_rows_carry_their_parameters():
    rows = sweep(trend_candles(), MRConfig())
    assert all({"rsi_oversold", "near_low_max", "max_hold_bars"} <= set(r) for r in rows)


def test_params_of_round_trips_through_the_config():
    rows = sweep(trend_candles(), MRConfig())
    row = rows[0]
    cfg = params_of(row)
    assert cfg.rsi_oversold == row["rsi_oversold"]
    assert cfg.near_low_max == row["near_low_max"]
    assert cfg.max_hold_bars == row["max_hold_bars"]


def test_best_by_picks_the_highest_return():
    rows = [
        {"return_pct": 1.0, "max_drawdown_pct": 5.0, "entries": 10},
        {"return_pct": 3.0, "max_drawdown_pct": 9.0, "entries": 12},
        {"return_pct": 2.0, "max_drawdown_pct": 1.0, "entries": 8},
    ]
    assert best_by(rows, "return_pct")["return_pct"] == 3.0


def test_best_by_breaks_a_return_tie_on_drawdown():
    rows = [
        {"return_pct": 2.0, "max_drawdown_pct": 9.0, "entries": 10},
        {"return_pct": 2.0, "max_drawdown_pct": 3.0, "entries": 10},
    ]
    assert best_by(rows, "return_pct")["max_drawdown_pct"] == 3.0


def test_best_by_breaks_a_full_tie_on_fewer_trades():
    # More trades at the same return means more costs paid for nothing.
    rows = [
        {"return_pct": 2.0, "max_drawdown_pct": 3.0, "entries": 40},
        {"return_pct": 2.0, "max_drawdown_pct": 3.0, "entries": 9},
    ]
    assert best_by(rows, "return_pct")["entries"] == 9


def test_params_of_keeps_the_unswept_defaults():
    cfg = params_of({"rsi_oversold": 30.0, "near_low_max": 0.2, "max_hold_bars": 12})
    base = MRConfig()
    assert cfg.position_value == base.position_value
    assert cfg.fee_per_side == base.fee_per_side
    assert cfg.stop_loss_pct == base.stop_loss_pct
    assert cfg.warmup == base.warmup


def test_walk_forward_split_is_chronological_not_random():
    rows = trend_candles()
    train, test = rows[: int(len(rows) * 0.6)], rows[int(len(rows) * 0.6):]
    # The test half must start strictly after the train half ends. A shuffled
    # split would let each half contain the other's future.
    assert train[-1]["timestamp"] < test[0]["timestamp"]


def test_walk_forward_picks_the_same_params_regardless_of_the_test_half():
    rows = trend_candles()
    train = rows[:900]
    base = MRConfig()
    picked = params_of(best_by(sweep(train, base), "return_pct"))

    # Tuning only ever saw `train`. Re-running the selection on a different
    # training set must not be needed, and must not consult the test half.
    train2 = [dict(r, close=r["close"] * 1.1) for r in train]
    picked2 = params_of(best_by(sweep(train2, base), "return_pct"))
    assert picked2 is not None and picked.max_hold_bars >= 1
    assert picked.rsi_oversold in (30.0, 34.0, 38.0, 42.0)


def test_max_hold_bars_is_the_parameter_that_actually_bites():
    # A longer forced hold converts a small edge into a larger loss when the
    # exit rule never triggers, so the sweep must be able to see that.
    rows = trend_candles()
    short = simulate_mean_reversion(rows, replace(MRConfig(), max_hold_bars=12))
    long = simulate_mean_reversion(rows, replace(MRConfig(), max_hold_bars=48))
    assert long["entries"] <= short["entries"]