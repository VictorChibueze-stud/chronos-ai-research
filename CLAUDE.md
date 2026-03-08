# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_features.py

# Run a single test by name
pytest tests/test_features.py::test_function_name

# Visual feature exploration (edit SYMBOL/TIMEFRAME/CSV_PATH at top of the script first)
python -m exploration.feature_explorer

# Live EDA: fetch Deriv OHLC and plot trend/structure features (requires .env)
python -m exploration.eda_deriv_trend
```

## Environment Setup

Copy `.env.example` to `.env` and fill in:
- `DERIV_APP_ID`
- `DERIV_API_TOKEN`

The Deriv adapter loads these via `DerivConfig.from_env()`.

## Architecture

Chronos-AI is a research lab for systematic trend-following strategies on Deriv synthetic indices (Volatility 10/25). The core design principle is a **hard split between deterministic Python and LLM reasoning**: all numeric trading math lives in Python; the LLM only reasons at a conceptual level and calls Python tools.

### Data Flow

```
Candle (OHLC struct)
  → compute_price_features()       [src/core/features.py]   → features dict
  → build_snapshot() / build_multi_snapshot()  [src/llm/context.py]  → MarketSnapshot (Pydantic)
  → StrategyFn(StrategyContext) → Signal       [src/core/signals.py]
  → run_backtest_single_symbol()   [src/backtest/engine.py]  → BacktestResult
```

### Module Responsibilities

| Path | Responsibility |
|------|----------------|
| `src/core/features.py` | Pure, stateless feature engine. Defines `Candle` dataclass and `compute_price_features()`. All indicator and market-structure logic (EMAs, ATR, swing highs/lows, BOS/CHOCH, FVGs, regime tags). |
| `src/core/trend_structure.py` | `detect_structure(candles)` — pure BOS state machine that segments candles into alternating impulse/retracement legs and emits BOS events. No indicator lookback; purely price-action driven. |
| `src/core/signals.py` | Defines `Signal`, `StrategyContext`, and `StrategyFn` protocol. Strategies are pluggable callables. |
| `src/core/risk.py` | Broker-agnostic position sizing, drawdown limits, kill-switch logic. |
| `src/core/timeframes.py` | Loads `config/timeframe_windows.yaml`; computes deterministic start/end windows for a given timeframe. |
| `src/core/experiment_registry.py` | Creates stamped experiment folders under `experiments/` with params, data manifest, and results. |
| `src/adapters/deriv_data.py` | Deriv WebSocket adapter: `fetch_deriv_ohlc()` returns `List[Candle]`. |
| `src/adapters/local_data.py` | CSV loader: `load_ohlc_from_csv()` returns `List[Candle]`. |
| `src/adapters/execution_stub.py` | No-op execution adapter (live trading not yet implemented). |
| `src/backtest/engine.py` | `run_backtest_single_symbol(candles, strategy_fn, BacktestConfig)` → `BacktestResult`. One open position at a time. |
| `src/backtest/metrics.py` | `compute_equity_metrics(trades)` for P&L, R-multiples, drawdown, equity curve. |
| `src/llm/schemas.py` | Pydantic models for LLM payloads: `MarketSnapshot`, `TrendState`, `VolatilityState`, `StructureState`, etc. |
| `src/llm/context.py` | `build_snapshot()` / `build_multi_snapshot()` convert `List[Candle]` → `MarketSnapshot`. |
| `src/llm/tools.py` | Small, audited Python tools the LLM can call (SL/TP calculation, position sizing). |
| `src/llm/orchestrator_schema.py` | JSON schema for LLM orchestration (e.g., Langflow integration). |
| `src/agent/harness.py` | `AgentHarness`: fetches multi-timeframe candles (D1/4H/1H), builds feature context, generates LLM prompt. |
| `src/agent/prompts.py` | `SYSTEM_PROMPT_V1` and other prompt templates. |
| `exploration/feature_explorer.py` | Script to visualize indicator and structure outputs as PNGs saved to `data/processed/plots/`. |
| `notebook/` | Jupyter notebooks for phase experiments (00_index through 06). Run deterministically: restart kernel, run all cells. |
| `config/params.yaml` | Global params (timeframes, min R:R 3.0, risk per trade) and per-symbol Deriv settings. |
| `config/symbols.yaml` | Human-readable symbol → broker code mapping (e.g., "Volatility 10 Index" → "R_10"). |
| `config/timeframe_windows.yaml` | Canonical lookback windows per timeframe for reproducible experiments. |

### Key Invariants

- `src/core/` is **broker-agnostic** — no Deriv or external API references.
- `src/core/features.py` is **pure and stateless** — functions take candle lists, return dicts, no side effects.
- The backtest engine and live path use **the same** `StrategyFn` and risk code — no separate simulation branch.
- LLM never does numeric math; it calls `src/llm/tools.py` for all levels and sizing.

## Development Phases

The project tracks progress in `progress.json`. Phases:
- **Phase 0** (done): Repo structure, configs, system spec
- **Phase 1** (done): Core feature engine (`src/core/features.py`) with full unit tests
- **Phase 2** (done): Data adapters (Deriv + CSV)
- **Phase 3** (in progress): Backtest engine and metrics
- **Phase E1** (in progress): EDA — live Deriv data fetch and visual validation
- **Phase 4** (in progress): Strategy API and baseline strategy
- **Phase 5** (in progress): Risk engine
- **Phase 6** (in progress): LLM/agent integration (Langflow)
