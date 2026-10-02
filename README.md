# ai-agent-trader

Hermes × [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) client for BTC spot paper trading.

Current phase: **Unified local agent + read-only dashboard (live)**.
Live trading is disabled and this repo has no exchange or broker credentials.

## Quick start — local LLM agent with dashboard

```bash
export PATH=/home/wempya/projects/AI-Trader/.venv/bin:$PATH
cd /home/wempya/projects/AI-Trader-hermes-client
PYTHONPATH=. python run_agent.py --model qwen2.5:7b --cycles 6 --hold
```

Dashboard: `http://127.0.0.1:8788/` (read-only; there is no order endpoint).

Requires Ollama with a local model (`qwen2.5:7b` or `qwen2.5:1.5b`) and the upstream
paper API running. Exit code `3` means Ollama is not reachable.

Paper order mode needs **two** explicit flags:

```bash
PYTHONPATH=. python run_agent.py --cycles 6 --execute --i-understand-this-orders-paper
```

`--execute` alone exits `2` with `execute_requires_explicit_flag`.

## Safety boundaries

- Localhost only: `http://127.0.0.1:8000`.
- Paper ledger only. No live exchange, no real funds.
- Buy-only, BTC-only, 1h, no leverage, no short, no sell automation.
- Risk engine sits outside strategy and outside any LLM.
- LLM output is validated as a structured proposal before it can reach the risk gate.
- The LLM cannot choose its own symbol, timeframe, candle, or baseline signal; a code sanitizer forces those fields.
- LLM BUY size is capped at `0.0002` BTC and `2%` of equity; oversized requests are downgraded to HOLD.
- If the LLM is unreachable or its output cannot be parsed, the cycle degrades to HOLD with a recorded reason.
- Kill switch, duplicate-signal guard, exposure cap, daily-loss cap, stale-price and spread guards are enforced and tested.
- Tokens are read from `~/.config/ai-trader/hermes-local.json` (mode `600`). Credentials are never stored in this repo.

## Environment

```bash
export PATH=/home/wempya/projects/AI-Trader/.venv/bin:$PATH
```

Requires the pinned upstream clone at `/home/wempya/projects/AI-Trader`
(commit `d03ff6c056b32ced735adf7c19ed8175adb1c8df`) plus its local API running.

The upstream `.env` sets a **relative** `DB_PATH`, so the API must be started from the
project root, not from `service/server`:

```bash
cd /home/wempya/projects/AI-Trader
PYTHONPATH=service/server python service/server/main.py
```

Starting it from the wrong working directory silently uses a different SQLite file and
every authenticated endpoint returns `401 Invalid token`.

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
p5_soak.py               P5.3 disagreement soak runner
run_p5_soak.py           P5.3 live-candle dry-run entrypoint (execute=false)
llm_agent.py             local + remote backend, structured proposal, sanitizer, fail-safe HOLD
remote_llm.py            remote HTTP client (OpenAI-compatible + System One), mode-600 config
agent_loop.py            one full cycle: provider -> baseline -> LLM -> validator -> risk -> ledger
indicators.py            RSI14, ATR14, EMA20/50 spread, returns, 24h range position
replay.py                agent vs baseline vs buy-and-hold, costs charged both sides
run_replay.py            historical replay CLI (--backend dry|gate|ollama|remote)
entry_agent.py           entry gate + exit rules; model proposes, code decides entry
dashboard.py             read-only dashboard state
dashboard_server.py      read-only HTTP server (/ and /api/state)
run_agent.py             unified agent CLI (loop + dashboard, --entry-mode)
```

## Evidence artifacts

`data/` holds reproducible artifacts, not secrets:

```text
btc_1h_last365d.json          5,000 clean BTC 1h candles (SHA-256 recorded in metadata)
fresh_observation_24h.jsonl   24 fresh-candle dry-run cycles
paper_execute_6cycle.jsonl    bounded execute observation evidence
paper_execute_6cycle.audit.jsonl  matching audit records
p5_soak.jsonl                 P5.3 disagreement soak evidence
p5_soak.audit.jsonl           P5.3 matching audit records
agent_live.jsonl              unified agent cycle evidence
agent_live.audit.jsonl        unified agent risk audit
agent_dashboard_state.json    read-only dashboard state
```

State files and `*.state.json` are runtime artifacts; they are kept out of git via `.gitignore`
only for caches, so they may appear in `data/` locally. They contain no credentials.

## P5.3 dry run

```bash
export PATH=/home/wempya/projects/AI-Trader/.venv/bin:$PATH
PYTHONPATH=. python run_p5_soak.py
```

`--execute` is refused with `execute_requires_explicit_ledger`. P5.4 bounded agent-assisted
paper execute needs explicit user approval before it may write a paper order.

## Historical replay and edge validation

```bash
export PATH=/home/wempya/projects/AI-Trader/.venv/bin:$PATH

# control run: no API calls, measures the harness itself
PYTHONPATH=. python run_replay.py --backend dry  --limit 2000

# deterministic entry gate only, no LLM. The floor the LLM must beat.
PYTHONPATH=. python run_replay.py --backend gate --limit 2000

# remote LLM with the entry gate applied
PYTHONPATH=. python run_replay.py --backend remote --entry-mode --limit 60
```

Every run reports buy-and-hold and baseline EMA beside the agent, with fee and
slippage charged on both sides. The agent must beat buy-and-hold to be worth
anything; beating only the baseline is not evidence of an edge.

## Entry gate

`entry_agent.py` moves the entry decision into code. The model still reads the
indicators and still proposes, but a BUY only survives when all five computed
criteria hold:

```text
ema_spread_positive    EMA20 above EMA50
price_above_ema20      last close above EMA20
rsi_in_band            RSI(14) between 45 and 70
not_overbought         RSI(14) below 70
momentum_positive      4h return above zero
```

A missing indicator counts as false: an unknown is not a yes. Every rejection is
recorded in `invalid_conditions`, so a HOLD caused by the gate is never
indistinguishable from a silent model failure.

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
