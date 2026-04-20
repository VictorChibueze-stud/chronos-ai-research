# Ikenga — Architecture

Canonical module map and data flow for the live system. For
day-to-day commands see [`dev_guide.md`](dev_guide.md). For agent
rules see [`../AGENTS.md`](../AGENTS.md) and
[`../CLAUDE.md`](../CLAUDE.md).

## 1. Design intent

Ikenga is a multi-timeframe trend-following research system for
Deriv synthetic indices and Binance crypto pairs. It encodes a
discretionary trading strategy into deterministic Python with an
optional LLM reasoning layer.

Two design invariants drive the layering:

1. **Deterministic Python owns all numeric market math.** Anything
   that touches prices, levels, scoring, or sizing lives in
   `src/core/`, `src/backtest/`, `src/execution/`, or
   `src/llm/tools.py`.
2. **The LLM layer is a parallel concern.** It consumes structured
   snapshots from `src/llm/context.py` and calls Python tools. It
   never invents math.

This is a research system. Live execution is gated behind
`EXECUTION_ENABLED=1`.

## 2. Layered module map

```
Data Adapters         src/adapters/        Deriv WebSocket, Binance REST,
                                           local CSV, yfinance, FTMO
        │
        ▼
Cache Layer           src/cache/           candle_store: single read path
                                           for candles (SQLite/Postgres)
        │
        ▼
Core Feature Engine   src/core/            features (EMA/RSI/ATR), trend_id,
                                           structure_levels (BOS/CHoCH/FVG),
                                           structural_walker (recursive depth),
                                           retracement_analysis, signals,
                                           choch_zone, leg_metrics, timeframes
        │
        ▼
Scanner               src/scanner/         market_scanner, universe,
                                           universe_ranking, global_structure,
                                           alert_watcher, job_log
        │
        ▼
Orchestrator          src/orchestrator/    setup lifecycle (trigger →
                                           confirm → execute → settle)
        │
        ▼
Execution             src/execution/       paper_engine, position_sizing,
                                           signal_bridge, account_router,
                                           contract_spec_seed,
                                           providers/{deriv,stub,base}
        │
        ▼
API                   src/api/             FastAPI routers, background jobs
        │
        ▼
Frontend              frontend/src/        Next.js 16, React 19, Tailwind v4
```

Parallel concerns:

- `src/llm/` — schemas, snapshot builders, deterministic callable
  tools for LLM use.
- `src/agent/` — agent harness and prompts.
- `src/fundamentals/` — economic calendar, news fetchers, market
  mapping for the macro signal gate.
- `src/services/` — cross-cutting service helpers (e.g.
  `structure_deepening`, `integrations_service`).
- `src/backtest/` — deterministic simulation engine and metrics.
- `src/visualization/` — chart rendering for research surfaces.
- `src/db/` — SQLAlchemy models and session management.
- `src/ui/` — Streamlit research UI.
- `src/cli/` — optional command-line entry points.

## 3. Key data flows

### 3.1 Candle ingestion

```
broker adapter → normalized Candle → cache.get_candles(symbol, tf, db)
                                  → CandleCache table
```

All downstream layers read candles via the cache. Signal logic does
not touch broker SDKs directly.

### 3.2 Trend analysis

```
features.py            (swing detection, EMA/RSI/ATR)
   ↓
trend_id.py            (scoring-based leg classification)
   ↓
structure_levels.py    (BOS, CHoCH, FVG extraction)
   ↓
structural_walker.py   (recursive depth resolution)
   ↓
retracement_analysis   (active retracement structural state)
```

Output is a structural state JSON blob — see
[`data_contract.md`](data_contract.md) for the exact schema.

### 3.3 Scanning and watchlist

- `market_scanner.py` runs on a 4-hourly schedule.
- It scans 350+ Binance pairs plus the Deriv synthetic universe.
- Results are written to `MonitoredSetup` (capped at 50, score-based
  LRU eviction).
- `AlertZone` rows track watch zones; `is_manual_override=True`
  protects a setup from eviction.

### 3.4 Execution

```
NormalizedOrderIntent
   ↓
orchestrator.manager       (killswitch + risk checks)
   ↓
execution.signal_bridge    (intent → provider call)
   ↓
provider (deriv|stub|paper) → ExecutionOrder + ExecutionEvent rows
```

`SystemSettings.killswitch` is checked before any execution path.

## 4. Configuration

All runtime tuning lives under `config/`:

- `timeframe_windows.yaml` — canonical lookback windows and ATR
  multipliers per timeframe. **Protected.**
- `correlation_rules.yaml` — symbol correlation groups for
  confluence analysis.
- `symbols.yaml` — human-readable symbol → broker code mapping.
- `params.yaml` — strategy and risk parameters.

Environment variables (see `.env.example`):

- `DERIV_APP_ID`, `DERIV_API_TOKEN` — Deriv adapter.
- `DATABASE_URL` — defaults to local SQLite; set to Postgres URL for
  the production-style stack.
- `EXECUTION_ENABLED` — must be `1` for any live order path.
- `NEXT_PUBLIC_API_URL` — frontend → backend URL.

## 5. Database

Primary tables (see `src/db/models.py` and `alembic/versions/`):

| Table | Purpose |
|---|---|
| `CandleCache` | OHLC with unique `(symbol, timeframe, timestamp)` |
| `MonitoredSetup` | Symbol + HTF + direction + score + structural_state_json |
| `AlertZone` | Active CHoCH/BOS watch zones; manual-override aware |
| `ExecutionOrder` / `ExecutionEvent` | Order lifecycle + audit trail |
| `SystemSettings` | Killswitch and global toggles |
| `Universe` / `PaperUniverse` | Symbol universes for live and paper |
| `ContractSpec` | Instrument metadata for sizing |
| `MarketState` | Cached market regime tags |
| `ManualStructureOverride` | User-pinned structural levels |
| `GlobalStructureCache` | Cached scanner global structure |
| `CandidateImpulseCache` / `CandidateWalker` | Walker intermediates |
| `SymbolAnalysisParams` | Per-symbol overrides for filter thresholds |

Migrations use Alembic. Run `alembic upgrade head` after a pull;
generate new migrations with `alembic revision --autogenerate -m "..."`.

## 6. API surface

Routers live under `src/api/routers/`:

| Router | Purpose |
|---|---|
| `analysis.py` | Full trend + structure analysis per symbol |
| `setups.py` | CRUD for monitored setups, scan trigger |
| `trend_visual.py` | Chart overlay data (BOS, CHoCH, FVG) |
| `candles.py` | Cached OHLC reads |
| `execution.py` | Submit `NormalizedOrderIntent`, list orders/events |
| `system.py` | Killswitch, scan status, system health |
| `integrations.py` | Broker integration onboarding |
| `universes.py` | Universe management |
| `universe_ranking.py` | Ranked universe view for the scanner |
| `manual_overrides.py` / `overrides.py` | User-pinned levels |
| `symbol_params.py` | Per-symbol analysis param overrides |
| `global_structure.py` | Global structure cache reads |

## 7. Frontend

Next.js 16 (App Router) + React 19 + Tailwind v4 in `frontend/`.
Pages mix live backend-driven views (scanner, signals, market,
universe, deep-dive, trades, integrations) with demo-mode surfaces
(analytics, risk, radar, watchtower, command). See
[`../frontend/README.md`](../frontend/README.md).

## 8. Testing

- Real SQLite (no mocks on the data layer).
- `pytest` runs the full suite.
- Core logic: `tests/test_trend_id.py`,
  `tests/test_structural_walker.py`, `tests/test_structure_levels.py`.
- Integration: `tests/test_api_backend.py`.
- Execution, signal bridge, and integrations each have dedicated
  test files.

## 9. What's deferred

- Binance Demo execution provider (after Deriv paper is stable).
- Integrations UI revamp (richer onboarding).
- FTMO / MetaTrader 5 bridge — there is no public FTMO REST order
  API; automation requires an MT5 terminal. `src/adapters/ftmo_data.py`
  remains as a read-only metrics adapter.

See [`../_brain/TASKS.md`](../_brain/TASKS.md) for the live task board.
