Chronos AI Workspace Instructions

Project:
Automated multi-timeframe trend-following research system for Deriv synthetic indices and Binance crypto pairs. Core rule: deterministic Python performs all market math; LLM components consume structured outputs and reason about context, but do not invent numeric analysis.

Repository Scope:
This summary describes the active repository outside archive/.

Implemented Areas

1. Core Market Structure Engine (src/core/)

- trend_id.py
	Scoring-based zigzag trend engine. Identifies trend direction, trend start, confirmed and unconfirmed legs, and current phase. Supports three optional impulse filters:
	- parent-relative filter
	- momentum filter
	- dominance filter

- features.py
	Pure feature engine for price-derived indicators and helpers. Includes compute_price_features(), compute_ema(), and crossover filtering logic used with structural legs.

- structure_levels.py
	Computes BOS and CHoCH levels for both global and internal structure. CHoCH requires at least two confirmed impulses. Structural lines are extended to the right edge of the chart.

- retracement_depth.py
	Measures retracement magnitude relative to the prior impulse. Adds ratio, percent, and exceeds_impulse annotations.

- retracement_analysis.py
	Higher-level retracement analysis utilities built around the structural model.

- leg_metrics.py
	Annotates legs with metrics such as duration and movement statistics, used in notebook diagnostics and structural evaluation.

- choch_zone.py
	Computes active CHoCH zones from confirmed structure so notebooks and visualizations can show invalidation regions.

- structural_walker.py
	Recursive structural analysis engine that walks nested retracements layer by layer, tracks CHoCH/BOS state, mitigation attempts, and termination conditions.

- signals.py
	Defines signal and strategy interfaces so the same strategy contract can be used in backtesting and later orchestration.

- timeframes.py
	Loads canonical timeframe windows from config/timeframe_windows.yaml and returns deterministic lookback windows.

- experiment_registry.py
	Creates stamped experiment folders for reproducible research runs.

2. Data Adapters and Storage

- src/adapters/deriv_data.py
	Deriv WebSocket OHLC adapter using environment-based credentials.

- src/adapters/binance_data.py
	Async Binance OHLC adapter with pagination, retry logic, deduplication, config-driven lookback behavior, and a synchronous wrapper.

- src/adapters/local_data.py
	CSV-based OHLC loader for local analysis and tests.

- src/data/candle_store.py
	Candle persistence utilities for storing and managing fetched data locally.

3. Backtesting and Metrics

- src/backtest/engine.py
	Single-symbol backtest engine with one-position-at-a-time execution flow.

- src/backtest/metrics.py
	Computes equity and trade performance metrics from backtest results.

4. LLM Integration Surface

- src/llm/schemas.py
	Pydantic schemas for structured market snapshots and state representations.

- src/llm/context.py
	Converts candles and feature outputs into MarketSnapshot-style payloads for downstream reasoning.

- src/llm/tools.py
	Small deterministic helper tools for calculations the LLM can call instead of doing math directly.

5. Agent and Scanner Layers

- src/agent/harness.py
	Multi-timeframe data collection and prompt-context assembly.

- src/agent/prompts.py
	System prompts and orchestration prompt text.

- src/scanner/market_scanner.py
	Multi-symbol scanning pipeline for evaluating multiple markets and timeframes.

6. Visualization and Research Tooling

- src/visualization/trend_chart.py
	Shared trend-structure plotting logic used by notebooks.

- exploration/feature_explorer.py
	Script for plotting indicators and structure outputs to PNG files.

- exploration/eda_deriv_trend.py
	Live exploratory analysis script for Deriv trend/structure workflows.

- scripts/fetch_and_save.py
	Utility script for fetching market data and storing it locally.

Implemented Notebooks (notebook/)

- 00_index.ipynb
	Notebook index and navigation entry point.

- 01_trend_id.ipynb
	Earlier trend-identification exploration notebook.

- 08_trend_id.ipynb
	Main structural analysis notebook. Includes global legs, internal structure, BOS/CHoCH overlays, EMA crossover markers, and retracement depth labels.

- 10_lag_analysis.ipynb
	Lag analysis notebook for measuring detection delay across structure-related events and plotting confirmation timing.

- 11_scanner_analysis.ipynb
	Scanner-oriented notebook for reviewing multi-symbol or multi-timeframe outputs.

- 12_structural_analysis.ipynb
	Deep-dive notebook for recursive structural walker analysis, CHoCH zones, mitigation tracking, and layered retracement visualization.

Configuration and Docs

- config/timeframe_windows.yaml
	Canonical lookback windows and timeframe-specific settings.

- config/params.yaml
	Global parameters, symbol-specific settings, and risk-related defaults.

- config/symbols.yaml
	Human-readable symbol mapping.

- docs/systemspec.md
	System specification and project intent.

- docs/dev_guide.md
	Developer guide skeleton.

- README.md
	High-level repo introduction and setup.

Test Coverage (tests/)

Current automated tests cover at least the following implemented areas:

- trend identification
- structure levels
- retracement depth
- retracement analysis
- structural walker
- leg metrics
- CHoCH zone logic
- Binance adapter
- Deriv adapter
- local CSV loader
- candle storage
- timeframe utilities
- experiment registry
- LLM context and tools
- agent harness
- market scanner
- backtest engine

Key files include:
- test_trend_id.py
- test_structure_levels.py
- test_retracement_depth.py
- test_retracement_analysis.py
- test_structural_walker.py
- test_leg_metrics.py
- test_choch_zone.py
- test_binance_adapter.py
- test_deriv_data.py
- test_local_data.py
- test_candle_store.py
- test_timeframes.py
- test_experiment_registry.py
- test_llm_context.py
- test_llm_tools.py
- test_agent_harness.py
- test_market_scanner.py
- test_backtest_engine.py

Working Architecture Decisions

- Trend identification is scoring-based, not PIP-based.
- All numeric trading logic remains in deterministic Python.
- BOS and CHoCH lines extend to the chart right edge; broken state is communicated visually rather than by truncating the line.
- CHoCH requires at least two confirmed impulses.
- Internal structure indices are offset back into global candle space before plotting.
- EMA crossover markers inside internal retracements are suppressed to avoid misleading noise.
- Retracement depth replaced Fibonacci as the simpler and more useful structural measure.
- Core modules should remain broker-agnostic; external API behavior belongs in adapters.

Common Commands

- Install dependencies:
	pip install -r requirements.txt

- Run all tests:
	pytest

- Run one test file:
	pytest tests/test_trend_id.py

- Run visual feature exploration:
	python -m exploration.feature_explorer

- Run live Deriv exploratory analysis:
	python -m exploration.eda_deriv_trend

Environment Notes

- Copy .env.example to .env and fill in DERIV_APP_ID and DERIV_API_TOKEN for Deriv data access.
- Binance workflows do not require the Deriv credentials.
- Notebook work should remain deterministic: restart kernel and run all cells when validating analysis notebooks.

Still Open or Explicitly In Progress

- Must-Break rule for BOS validation during leg confirmation
- CHoCH-triggered trend reset logic
- Range detection using retracement-depth behavior rather than simple percent move
- Further strategy confluence such as RSI divergence
- Trend channel lines
- Further snapshot serialization and orchestration polish around the LLM surface
- ML-driven state classification and retracement-termination modeling are design ideas, not implemented production modules

Usage Guidance for Coding Agents

- Prefer modifying the active deterministic Python pipeline rather than duplicating logic in notebooks.
- Treat notebooks as research and visualization surfaces, not the source of truth for core calculations.
- When changing structure logic, update or add tests in tests/ first or alongside the change.
- Preserve the split between core/, adapters/, backtest/, llm/, and notebook/ responsibilities.