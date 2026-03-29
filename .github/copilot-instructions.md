Chronos AI Workspace Instructions

Purpose

- Chronos AI is a multi-timeframe trend-following research system for Deriv synthetic indices and Binance crypto pairs.
- Hard rule: deterministic Python owns all numeric market math. LLM components consume structured outputs and reason about context, but do not invent numeric analysis.

Scope

- Applies to active code under src/, tests/, notebook/, exploration/, scripts/, config/, docs/, and frontend/.
- Exclude archive/ unless a task explicitly targets archived material.

Quick Start Commands

- Install dependencies: pip install -r requirements.txt
- Run all tests: pytest
- Run one test file: pytest tests/test_trend_id.py
- Run one test by name: pytest tests/test_features.py::test_function_name
- Run API locally: python scripts/run_api.py
- Run Streamlit UI: python scripts/run_ui.py
- Visual exploration: python -m exploration.feature_explorer
- Live Deriv EDA: python -m exploration.eda_deriv_trend
- Frontend dev: cd frontend && npm run dev
- Frontend build: cd frontend && npm run build
- Frontend lint: cd frontend && npm run lint

Environment and Reproducibility

- Copy .env.example to .env and set DERIV_APP_ID and DERIV_API_TOKEN for Deriv workflows.
- Binance workflows do not require Deriv credentials.
- Notebook validation is deterministic: restart kernel and run all cells.
- Frontend expects NEXT_PUBLIC_API_URL to point at the FastAPI backend; default local backend is http://localhost:8000.

Architecture Boundaries

- src/core/: pure, stateless, broker-agnostic logic only. No API calls or external side effects.
- src/adapters/: broker and datasource integration (Deriv, Binance, local CSV), normalize to Candle structures.
- src/backtest/: deterministic simulation engine and metrics.
- src/llm/: schemas, snapshot builders, and deterministic callable tools for LLM use.
- src/agent/ and src/scanner/: orchestration and multi-symbol or multi-timeframe pipeline logic.
- src/ui/, src/db/, src/orchestrator/, src/cli/: newer app layers with tests present; keep changes scoped and additive.
- frontend/src/app/: Next.js App Router pages for scanner, signals, market, universe, analytics, and risk.
- frontend/src/components/: shared UI and charting components; frontend/src/lib/: API clients, chart data helpers, and types.

Project Invariants

- Trend identification is scoring-based in src/core/trend_id.py, not PIP-based.
- CHoCH requires at least two confirmed impulses.
- BOS and CHoCH levels extend to the chart right edge for visualization.
- Internal structure indices are offset into global candle index space before plotting.
- EMA crossover markers inside internal retracements are intentionally suppressed.
- Retracement depth is preferred structural measure over Fibonacci in current pipeline.
- Keep core deterministic and adapter-facing concerns separated.
- LLM-facing flows consume structured outputs and call deterministic Python tools for any numeric calculation; do not move market math into prompts or frontend code.

Testing Expectations

- If you change src/core/ logic, update or add tests in tests/ in the same change.
- Favor focused test runs first, then run full pytest when practical.
- Current test suite includes coverage for core structure, adapters, llm context and tools, scanner, ui, db, orchestrator, and backtest paths.
- If you change frontend/, run at least cd frontend && npm run build. Run npm run lint when making broader frontend edits.

Preferred Editing Targets

- Source of truth for market math: src/core/ modules.
- Notebooks in notebook/ are research and visualization surfaces, not canonical logic.
- Plotting behavior belongs in src/visualization/.
- Frontend route pages belong in frontend/src/app/; shared visual primitives belong in frontend/src/components/chronos-ui.tsx when reused across pages.

Pitfalls and Gotchas

- Do not add broker-specific logic to src/core/.
- Keep timestamp handling UTC-consistent across timeframe merges and comparisons.
- Guard notebook code against stale kernel state and out-of-order execution assumptions.
- For BOS or CHoCH visualization changes, preserve right-edge extension behavior unless explicitly requested otherwise.
- Frontend runs on Next.js 16+; read frontend/CLAUDE.md before making framework-level changes because current conventions differ from older Next.js patterns.
- Treat frontend Next.js behavior as potentially non-standard for this repo version; consult the local docs in node_modules/next/dist/docs/ before framework-level edits.
- lightweight-charts must stay client-only in Next.js pages. Use dynamic import with ssr: false when a page renders the chart directly.
- Prefer frontend/src/lib/api.ts for backend HTTP calls and keep page logic aligned with FastAPI response shapes.

Link, Do Not Duplicate

- For system intent and high-level context: see docs/systemspec.md and README.md.
- For dev workflow and conventions: see docs/dev_guide.md and CLAUDE.md.
- For schema and payload constraints: see docs/data_contract.md and src/llm/schemas.py.
- For canonical timeframe windows: see config/timeframe_windows.yaml.
- For frontend-specific framework guidance: see frontend/CLAUDE.md.
- For frontend agent-specific caveats: see frontend/AGENTS.md.
- For frontend route and component examples: see frontend/src/app/ and frontend/src/components/.

Area-Specific Instruction Layering

- Root guidance in this file applies workspace-wide.
- Frontend tasks should additionally follow frontend/AGENTS.md and frontend/CLAUDE.md.
- Notebook work should remain deterministic: restart kernel and run all cells before validating conclusions.

Current Notebooks of Interest

- notebook/00_index.ipynb
- notebook/01_trend_id.ipynb
- notebook/08_trend_id.ipynb
- notebook/10_lag_analysis.ipynb
- notebook/11_scanner_analysis.ipynb
- notebook/12_structural_analysis.ipynb
- notebook/13_move_inspector.ipynb
- notebook/14_full_analysis.ipynb

Known In-Progress Items

- Must-break BOS validation during leg confirmation.
- CHoCH-triggered trend reset logic.
- Range detection via retracement-depth behavior.
- Additional confluence experiments, for example RSI divergence.
- Trend channel lines.
- Additional orchestration and snapshot serialization polish.
- Frontend pages currently mix live backend-driven views with demo-mode surfaces; preserve that distinction unless a task explicitly wires demo pages to real data.