# Ikenga

> A personal side project — rebuilding and systematising a manual
> trading strategy I ran a few years ago.

Back then the strategy was entirely discretionary: reading price
structure, identifying trend context across timeframes, and timing
entries around break-of-structure and fair-value gaps. It worked
reasonably well, but it was inconsistent and non-reproducible. This
project is my attempt to encode that same logic into a rigorous,
testable Python system, with an LLM layer to reason about market
context the way I used to do manually.

> The repository folder is `chronos-ai/` for legacy reasons. The
> product name is **Ikenga**.

## What this is

A modular research lab for systematic trend-following on **Deriv
synthetic indices** (Volatility 10 / Volatility 25) and **Binance
crypto pairs**. The core design keeps a hard split between:

- **Deterministic Python** — all numeric logic: feature extraction,
  indicator math, market structure detection (BOS / CHoCH / FVGs,
  swing highs/lows), backtesting, sizing, and execution.
- **LLM reasoning** — reads structured market snapshots and reasons
  at a conceptual level; never does raw market math.

This is not a production trading system. No live orders are placed
without `EXECUTION_ENABLED=1` explicitly set.

## Project structure

```
src/
  core/          # Trend ID, structural walker, BOS/CHoCH/FVG, signals
  adapters/      # Deriv WebSocket, Binance REST, CSV, yfinance, FTMO
  cache/         # Single read path for candles (SQLite/Postgres)
  scanner/       # Multi-symbol scanning, universe ranking, alert watcher
  orchestrator/  # Setup lifecycle (trigger → confirm → execute → settle)
  execution/     # Paper engine, position sizing, providers, signal bridge
  api/           # FastAPI routers + background jobs
  llm/           # Schemas, snapshot builders, deterministic tools
  agent/         # Agent harness and prompts
  fundamentals/  # Economic calendar, news, macro signal gate
  backtest/      # Deterministic engine + metrics
  visualization/ # Chart rendering for research
  db/            # SQLAlchemy models + sessions
  ui/            # Streamlit research UI
  cli/           # Optional CLI entry points

frontend/        # Next.js 16 + React 19 operator console
config/          # YAML configs (timeframe windows, symbols, params)
alembic/         # Database migrations
notebook/        # Phase-by-phase research notebooks
exploration/     # Visual feature explorer
sandbox/         # Algorithm staging area (live data, isolated code)
experiments/     # Registered experiment runs
tests/           # Pytest suite (real DB, no mocks)
docs/            # Architecture, dev guide, data contract
_brain/          # Decision log + task board
```

## What's working today

- Multi-symbol scanner across 350+ Binance pairs and the Deriv
  synthetic universe, with 4-hourly cadence and score-based LRU
  eviction.
- Recursive structural walker with manual override protection.
- FastAPI backend with full router surface (analysis, setups,
  execution, universes, manual overrides, system).
- Frontend operator console (Next.js 16) — scanner, signals,
  market, universe, deep-dive, and trades pages are live-driven.
- Paper trading scaffold with contract-spec seeding.
- Postgres migration path via Alembic.

See [`_brain/TASKS.md`](_brain/TASKS.md) for the live task board and
[`docs/architecture.md`](docs/architecture.md) for the canonical
module map.

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate           # Windows
pip install -r requirements.txt

cp .env.example .env               # set DERIV_APP_ID, DERIV_API_TOKEN
                                   # (Binance does not require keys)

alembic upgrade head               # initialize / migrate schema
```

```bash
pytest                                  # run all tests
python scripts/run_api.py               # FastAPI on http://localhost:8000
python scripts/run_ui.py                # Streamlit research UI
python -m exploration.feature_explorer  # visual indicator output

cd frontend
npm install
npm run dev                             # http://localhost:3000
```

## Reading order

- [`AGENTS.md`](AGENTS.md) — agent guide and hard rules
- [`CLAUDE.md`](CLAUDE.md) — canonical current-state document
- [`docs/architecture.md`](docs/architecture.md) — module map + data flow
- [`docs/dev_guide.md`](docs/dev_guide.md) — developer workflow
- [`docs/data_contract.md`](docs/data_contract.md) — engine output schema
- [`_brain/DECISIONS.md`](_brain/DECISIONS.md) — why the system is
  shaped this way
- [`_brain/TASKS.md`](_brain/TASKS.md) — live task board

## Notes

This is not a production trading system. No live execution runs
without `EXECUTION_ENABLED=1`. The goal is a reproducible research
environment where I can rigorously test whether the edge from my
old discretionary approach actually holds up.
