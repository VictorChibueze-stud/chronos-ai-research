# Ikenga Developer Guide

This guide covers the day-to-day developer workflow. For the canonical
module map and data flow, see [`docs/architecture.md`](architecture.md).
For agent-facing rules, see [`CLAUDE.md`](../CLAUDE.md) and
[`.cursorrules`](../.cursorrules).

## 1. Setup

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set credentials for any broker you
plan to exercise. Binance and CSV workflows do not require Deriv keys.

```bash
DERIV_APP_ID=...
DERIV_API_TOKEN=...
```

For Postgres workflows, set `DATABASE_URL`. The default is local SQLite.

## 2. Common Commands

```bash
pytest                                # full test suite
pytest tests/test_trend_id.py         # single file
pytest tests/test_features.py::test_x # single test

python scripts/run_api.py             # FastAPI on http://localhost:8000
python scripts/run_ui.py              # Streamlit research UI
python scripts/init_db.py             # initialize SQLite schema

alembic upgrade head                  # apply migrations
alembic revision --autogenerate -m "..."  # new migration

cd frontend
npm install
npm run dev                           # Next.js dev server
npm run build                         # production build (run before commit)
npm run lint
```

## 3. Visual Exploration

Use the exploration harness to inspect computed features and structure
detection:

```bash
python -m exploration.feature_explorer
```

- Configure `SYMBOL`, `TIMEFRAME`, and `CSV_PATH` at the top of
  `exploration/feature_explorer.py`.
- PNGs are written to `data/processed/plots/` (created automatically).
- Preferred path for visually approving indicator and structure
  definitions before they reach `src/core/`.

For live Deriv exploration:

```bash
python -m exploration.eda_deriv_trend
```

## 4. Data Adapters and Credentials

### 4.1 Deriv Adapter

- Implementation: `src/adapters/deriv_data.py`.
- Configuration: `DerivConfig.from_env()` reads `DERIV_APP_ID` and
  `DERIV_API_TOKEN`.
- All Deriv candle reads go through the cache layer
  (`src/cache/candle_store.py`); never call the WebSocket directly from
  signal logic.

### 4.2 Binance Adapter

- Implementation: `src/adapters/binance_data.py`.
- No credentials required for public REST candles.
- Same cache contract as Deriv.

### 4.3 Local CSV Loader

- Implementation: `src/adapters/local_data.py`.
- Use `load_ohlc_from_csv(path, ...)` to materialize `Candle` objects
  for backtesting or feature exploration.

## 5. Running a Backtest

With OHLC data (via `load_ohlc_from_csv`, `fetch_deriv_ohlc`, or
`fetch_binance_ohlc`) and a strategy callable:

1. Materialize a `List[Candle]`.
2. Implement a `StrategyFn` that takes a `StrategyContext` and returns
   a `Signal` (`src/core/signals.py`).
3. Call `run_backtest_single_symbol(candles, strategy_fn, BacktestConfig(...))`
   from `src/backtest/engine.py`.
4. Compute summary metrics via `compute_equity_metrics(result.trades)`
   from `src/backtest/metrics.py`.

The same strategy + risk code is intended for live use, so the backtest
loop must not introduce its own market math.

## 6. Market-Structure Research Harness

- `config/timeframe_windows.yaml` — canonical zoom-out windows per
  timeframe. Edit here, not in code.
- `src/core/timeframes.py` — `load_timeframe_windows()` and
  `get_time_window()` produce deterministic start/end windows.
- `src/core/experiment_registry.py` — `create_experiment()` lays out
  `experiments/<exp_id>/` with `params.yaml`, `data_manifest.json`,
  `results.json`, and `figures/`.
- Notebooks in `notebook/` are deterministic: restart kernel and run
  all cells before treating output as canonical.

## 7. Sandbox Workflow

For algorithm changes you want to validate against live data without
touching `src/`:

1. Edit copies under `sandbox/algorithms/`.
2. Iterate in `sandbox/research.ipynb` (imports from `sandbox/algorithms/`,
   not `src/`).
3. Compare with live via `sandbox/diff_tool.py`.
4. Promote with `sandbox/push_to_live.py` (interactive confirmation).
5. Restart the API server.

See `sandbox/README.md` for details.
