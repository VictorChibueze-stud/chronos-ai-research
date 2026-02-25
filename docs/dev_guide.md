# Chronos-AI Developer Guide (Skeleton)

## 1. Setup

- Create and activate a virtual environment.
- Install dependencies:

  ```bash
  pip install -r requirements.txt
```

* Run tests:

  ```bash
  pytest
  ```

## 2. Code Layout (High-Level)

* `src/core/`: core math, features, signals, risk.
* `src/adapters/`: broker and data-source adapters.
* `src/backtest/`: backtest engine and metrics.
* `src/llm/`: orchestration schemas and helpers for LLM integration.
* `src/cli/`: optional command-line entry points.
* `config/`: YAML configs for symbols and parameters.
* `docs/`: system spec and developer docs.
* `tests/`: pytest test files.

This document will be extended as functionality is implemented.

## 3. Visual Exploration

Use the exploration harness to visually inspect computed features and structure detection:

- Run the explorer:

```bash
python -m exploration.feature_explorer
```

- Configure `SYMBOL`, `TIMEFRAME`, and `CSV_PATH` at the top of `exploration/feature_explorer.py`.
- The script writes PNGs to `data/processed/plots/` (created automatically).
- This is the preferred method to visually approve indicator and structure definitions.

## 3. Data Adapters and Credentials

### 3.1 Deriv Adapter

- The Deriv OHLC adapter lives in `src/adapters/deriv_data.py`.
- It uses `DerivConfig.from_env()` which expects the following environment variables:
  - `DERIV_APP_ID`
  - `DERIV_API_TOKEN`
- For convenience, copy `.env.example` to `.env` and fill in your values locally, then configure your IDE or shell to load `.env` before running scripts.

### 3.2 Local CSV Loader

- The CSV loader is implemented in `src/adapters/local_data.py`.
- Use `load_ohlc_from_csv(path, ...)` to load data into `Candle` objects for backtesting or feature exploration.
- The `exploration/feature_explorer.py` script can use this loader to visualize indicators and structure on historical data.

## 4. Running a Simple Backtest

Once you have OHLC data (e.g., via `load_ohlc_from_csv` or `fetch_deriv_ohlc`) and a strategy function:

1. Convert raw data into `List[Candle>`.
2. Implement a `StrategyFn` that takes a `StrategyContext` and returns a `Signal`.
3. Call `run_backtest_single_symbol(candles, strategy_fn, BacktestConfig(...))`.
4. Use `compute_equity_metrics(result.trades)` to get basic summary stats.

In Phase 4, dedicated strategy modules will live in `src/core/signals.py`, and LLM/agent orchestration will call the same backtest engine for evaluation.

## Market-Structure Research Harness

This project includes a deterministic research harness for Market-Structure experiments (Phase 1).

- `config/timeframe_windows.yaml` defines canonical zoom-out windows per timeframe.
- `src/core/timeframes.py` provides `load_timeframe_windows()` and `get_time_window()` to compute deterministic start/end windows for a given timeframe.
- `src/core/experiment_registry.py` provides `create_experiment()` to create lightweight experiment folders under `experiments/`.
- Notebooks in `notebook/` follow a deterministic pattern: restart kernel, run all cells, and use a single `params.yaml` (or experiment params) for reproducibility.

Use these helpers to make notebook-driven experiments repeatable and easy to register.

