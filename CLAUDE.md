# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Ikenga** is a research-grade, multi-timeframe trend-following system for Deriv synthetic indices and Binance crypto pairs. It encodes a discretionary trading strategy into deterministic Python with an optional LLM reasoning layer.

> The repository folder is `chronos-ai/` for legacy reasons. The product name is **Ikenga**.

**This is not a production trading system.** No live orders are placed without `EXECUTION_ENABLED=1` explicitly set.

## Commands

### Backend
```bash
# Run FastAPI backend (http://localhost:8000)
python scripts/run_api.py

# Run Streamlit research UI
python scripts/run_ui.py

# Initialize database
python scripts/init_db.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_trend_id.py

# Run a single test by name
pytest tests/test_features.py::test_function_name
```

### Frontend
```bash
cd frontend
npm run dev      # development server
npm run build    # production build
npm run lint     # lint check
```

### Database Migrations
```bash
alembic upgrade head     # apply migrations
alembic revision --autogenerate -m "description"  # generate new migration
```

## Architecture

### Core Design Invariants (read before editing `src/core/`)

- **Deterministic Python owns all numeric logic.** The LLM layer (`src/llm/`) consumes structured Pydantic outputs and calls deterministic tools — it never performs market math directly.
- **Trend identification is scoring-based, not PIP-based.**
- **CHoCH requires ≥2 confirmed impulses** before it is valid.
- **BOS and CHoCH levels extend to chart right edge** for visualization continuity.
- **Internal structure indices are offset into global candle index space** before plotting.
- **Retracement depth is preferred over Fibonacci** in the analysis pipeline.
- **EMA crossover markers inside internal retracements are intentionally suppressed.**
- When changing `src/core/`, always update corresponding tests in the same commit.

### Layer Separation

```
Data Adapters        src/adapters/          Deriv WebSocket, Binance REST, CSV
        ↓
Core Feature Engine  src/core/              Trend ID, leg detection, structure, indicators
        ↓
Scanner / Orchestrator  src/scanner/, src/orchestrator/   Multi-symbol scanning, setup lifecycle
        ↓
API                  src/api/               FastAPI routers, background jobs, CORS
        ↓
Frontend             frontend/src/          Next.js 16 / React 19 / TailwindCSS v4
```

The LLM layer (`src/llm/`) is a parallel concern that consumes `src/core/` output via `src/llm/context.py` and `src/llm/tools.py`.

### Key Data Flows

1. **Candle ingestion**: `binance_data.py` / `deriv_data.py` → normalized `Candle` objects → `CandleCache` table
2. **Trend analysis**: `features.py` (swing detection, EMA/RSI/ATR) → `trend_id.py` (scoring, leg classification) → `structure_levels.py` (BOS, CHoCH, FVG) → `structural_walker.py` (recursive nested resolution)
3. **Scanner**: `market_scanner.py` runs 4-hourly, scans 350+ Binance pairs + hardcoded Deriv universe, stores `MonitoredSetup` records (capped at 50, score-based LRU eviction)
4. **Execution**: `NormalizedOrderIntent` → `orchestrator.py` (killswitch check) → provider (`deriv.py` or `stub.py`) → persisted `ExecutionOrder` + `ExecutionEvent`

### Configuration Files

- `config/timeframe_windows.yaml` — all indicator lookback windows and ATR multipliers per timeframe. Modify here, not in code.
- `config/correlation_rules.yaml` — symbol correlation groups for confluence analysis.

### Database Schema (key tables)

- `MonitoredSetup` — symbol + HTF timeframe + trend direction + score + structural state JSON
- `AlertZone` — support/resistance zones; `is_manual_override=True` protects setup from eviction
- `CandleCache` — OHLC with unique (symbol, timeframe, timestamp) constraint
- `ExecutionOrder` / `ExecutionEvent` — order lifecycle with full audit trail
- `SystemSettings` — killswitch state (check before any execution path)

### API Key Endpoints

| Router | Key Endpoints |
|--------|--------------|
| `/api/analysis/{symbol}` | Full trend + structure analysis; query params override filter thresholds |
| `/api/setups/` | CRUD for monitored setups, trigger scan |
| `/api/universe/{symbol}/readiness` | Bootstrap stage: 0=new → 3=ready |
| `/api/trend/{symbol}` | Chart overlay data (BOS, CHoCH, FVG levels) |
| `/api/execution/orders` | Submit `NormalizedOrderIntent` |
| `/api/execution/from-signal` | Auto-derive intent from current trend |
| `/api/system/killswitch` | Emergency stop toggle |

### Frontend Notes

- **`candle-chart.tsx`** must always use `dynamic` import with `ssr: false` — lightweight-charts does not support SSR.
- All HTTP calls go through `frontend/src/lib/api.ts` (axios instance). Never add raw fetch calls.
- TypeScript interfaces live in `frontend/src/lib/types.ts` — keep aligned with FastAPI response shapes.
- Some pages are demo-mode surfaces, not live-backend-driven. Preserve that distinction when editing.
- Run `npm run build` after any frontend change to catch type errors before committing.

### Testing

- Integration tests hit a real DB (SQLite in test env). No mocking the database layer.
- `tests/test_api_backend.py` — full FastAPI integration tests
- `tests/test_structural_walker.py`, `test_structure_levels.py`, `test_trend_id.py` — core logic
- Execution, signal bridge, and integrations each have dedicated test files

### In-Progress Areas (as of last checkpoint)

- Must-break BOS validation during leg confirmation
- CHoCH-triggered trend reset logic
- Range detection via retracement-depth behavior
- Trend channel lines
- Frontend pages: scanner, market, universe, signals are live-driven; analytics/risk/radar are demo surfaces
