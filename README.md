# Chronos-AI

> A personal side project — rebuilding and systematising a manual trading strategy I ran a few years ago.

Back then the strategy was entirely discretionary: reading price structure, identifying trend context across timeframes, and timing entries around break-of-structure and fair-value gaps. It worked reasonably well, but it was inconsistent and non-reproducible. This project is my attempt to encode that same logic into a rigorous, testable Python system, and eventually use an LLM layer to reason about market context the way I used to do manually.

## What this is

A modular research lab for systematic trend-following on **Deriv synthetic indices** (Volatility 10 / Volatility 25). The core design keeps a hard split between:

- **Deterministic Python** — all numeric logic: feature extraction, indicator math, market structure detection (BOS/CHOCH, FVGs, swing highs/lows), backtesting, and risk sizing.
- **LLM reasoning** — reads a structured market snapshot and reasons at a conceptual level; never does raw math.

## Project Structure

```
src/
  core/         # Feature engine, signals, risk, timeframes
  adapters/     # Deriv WebSocket + local CSV data loaders
  backtest/     # Engine and metrics
  llm/          # Schemas, context builder, tools
  agent/        # Agent harness and prompts
config/         # YAML configs for symbols, timeframes, params
notebook/       # Phase-by-phase research notebooks (00–07)
exploration/    # Visual feature explorer
tests/          # Unit tests (pytest)
```

## Current Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Repo setup & hygiene | Done |
| 1 | Core feature engine | Done |
| 2 | Data adapters (Deriv + CSV) | Done |
| 3 | Backtest engine & metrics | In progress |
| EDA | Exploratory data analysis | In progress |
| 4 | Strategy API & baseline strategy | In progress |
| 5 | Risk engine | In progress |
| 6 | LLM / agent integration | In progress |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in DERIV_APP_ID and DERIV_API_TOKEN
```

```bash
pytest                              # run all tests
python -m exploration.feature_explorer   # visual indicator output
```

## Notes

This is not a production trading system. No live execution is implemented. The goal is a reproducible research environment where I can rigorously test whether the edge from my old discretionary approach actually holds up.
