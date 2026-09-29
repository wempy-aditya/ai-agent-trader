# ai-agent-trader

Hermes × [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) client for BTC spot paper trading.

Current phase: **P5.2 — agent-assisted paper trading (design + schema + deterministic mock comparison)**.
Live trading is disabled and this repo has no exchange or broker credentials.

## Safety boundaries

- Localhost only: `http://127.0.0.1:8000`.
- Paper ledger only. No live exchange, no real funds.
- Buy-only, BTC-only, 1h, no leverage, no short, no sell automation.
- Risk engine sits outside strategy and outside any LLM.
- LLM output is validated as a structured proposal before it can reach the risk gate.
- Kill switch, duplicate-signal guard, exposure cap, daily-loss cap, stale-price and spread guards are enforced and tested.
- Tokens are read from `~/.config/ai-trader/hermes-local.json` (mode `600`). Credentials are never stored in this repo.

## Environment

```bash
export PATH=/home/wempya/projects/AI-Trader/.venv/bin:$PATH
```

Requires the pinned upstream clone at `/home/wempya/projects/AI-Trader`
(commit `d03ff6c056b32ced735adf7c19ed8175adb1c8df`) plus its local API running.

## Tests

```bash
pytest -q
```

## Modules

```text
baseline.py              deterministic EMA20/EMA50 baseline + cost model
backtest.py              reproducible backtest harness
download_data.py         Hyperliquid public BTC 1h dataset download
risk.py                  deterministic RiskGate
audit_store.py           append-only audit + atomic runtime state
paper_loop.py            proposal -> RiskGate -> audit -> ledger callback
ledger_adapter.py        localhost-only paper ledger adapter
client.py                minimal Hermes-facing local API client
observation.py           bounded observation runner (execute=false default)
recurring_observation.py bounded schedule config validation
fresh_polling.py         fresh closed-candle acceptance + duplicate skip
fresh_observation.py     provider -> poller -> EMA -> PaperLoop chain
collect_fresh_observation.py   bounded 24-cycle dry-run collector
run_paper_execute_6.py   bounded six-cycle paper execute observation
hyperliquid_provider.py  public BTC 1h candle provider
signal_observation.py    closed-candle EMA signal builder
agent_proposal.py        P5 structured LLM proposal validator
p5_comparison.py         P5 baseline vs deterministic mock comparison
```

## Evidence artifacts

`data/` holds reproducible artifacts, not secrets:

```text
btc_1h_last365d.json          5,000 clean BTC 1h candles (SHA-256 recorded in metadata)
fresh_observation_24h.jsonl   24 fresh-candle dry-run cycles
paper_execute_6cycle.jsonl    bounded execute observation evidence
paper_execute_6cycle.audit.jsonl  matching audit records
```

## P5 proposal schema v1

```json
{
  "schema_version": "p5.v1",
  "signal_id": "string",
  "candle_timestamp": 0,
  "symbol": "BTC",
  "timeframe": "1h",
  "action": "hold|buy",
  "quantity": 0.0,
  "reference_price": 0.0,
  "confidence": 0.0,
  "reason_codes": ["string"],
  "invalid_conditions": ["string"],
  "baseline_signal": "hold|buy",
  "model_id": "string"
}
```

## Project notes

Design, phase gates, evidence ledger, and next action are tracked in the Obsidian vault at
`Projects/TRADING-AGENT/`, starting with `Project-State.md`.

*Update terakhir: 2026-09-21*
