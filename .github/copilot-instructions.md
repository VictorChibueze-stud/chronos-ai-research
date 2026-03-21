Session Summary — Chronos AI Development
Project: Automated multi-timeframe trend-following trading system for Deriv/Binance synthetic indices and crypto. Core philosophy: deterministic Python for all math, LLM only for reasoning and decisions.
Current repo state (src/core/):

trend_id.py — scoring-based zigzag engine with 3 optional filters (parent-relative, momentum decay, dominance). Returns {trend, trend_start, legs, current_phase}
trend_id_pip.py — PIP-based parallel implementation (built but discarded as inferior)
features.py — compute_price_features(), compute_ema(candles, period), filter_crossovers_in_impulses(crossover_indices, legs, suppress_indices)
structure_levels.py — compute_bos_levels(), compute_choch_level() (requires 2+ confirmed impulses), compute_all_structure_levels(), compute_internal_structure_levels(). All unbroken lines extend to len(candles)-1. TODO comment for analyze_impulse_as_trend().
retracement_depth.py — compute_retracement_depth(), annotate_legs_with_depth(), summarise_retracement_depths(). Measures how much of preceding impulse was retraced as ratio/pct. exceeds_impulse=True when >100% (CHoCH territory).
fibonacci.py — deleted, replaced by retracement_depth

Adapters:

binance_data.py — async paginated fetcher with config-driven lookback from timeframe_windows.yaml, retry logic, dedup, sync wrapper. 14 tests passing.
deriv_data.py — existing Deriv WebSocket adapter

Notebooks:

08_trend_id.ipynb — main analysis notebook. Config cell with 6 filter params + data source toggle. Multi-timeframe loop. Plots: global legs (red/green), internal structure (black dashed), BOS (blue dashed full-width), CHoCH (pink solid full-width), internal BOS (light blue dotted), internal CHoCH (light pink dotted), EMA crossover X markers (dark orange global impulse, lighter orange internal impulse, suppressed in internal retracements), retracement depth % labels on retracement midpoints.
09_trend_id_pip.ipynb — PIP comparison notebook (built, superseded)
10_lag_analysis.ipynb — 7-cell lag analysis notebook. Measures and plots feature detection lag bands (axvspan) per feature type with event circle + confirmation triangle markers. Retracement depth horizontal bar chart. In progress: adding full structural overlay (zigzags + BOS/CHoCH) to Cell 6.

Tests passing:

test_trend_id.py — 9 tests including EMA crossover suppression
test_trend_id_pip.py — 12 tests
test_structure_levels.py — covers BOS/CHoCH global and internal, offset, extension
test_retracement_depth.py — 7 tests
test_binance_adapter.py — 14 tests

Key architectural decisions made:

Trend ID is scoring-based (not PIP) — PIP was tested and discarded
BOS/CHoCH lines always extend to chart right edge regardless of broken status; broken communicated via style (dotted + alpha)
CHoCH requires minimum 2 confirmed impulses
EMA crossovers suppressed in internal retracements (two-tier filter)
Internal structure indices always offset back to global space before plotting
Retracement depth replaces Fibonacci — simpler, more analytically useful

Identified gaps (not yet implemented):

Must-Break Rule (BOS validation in leg confirmation)
CHoCH detection triggering trend reset
Range detection via retracement depth threshold (not just % move)
Market scanner (multi-asset loop)
build_snapshot() serialisation for LLM consumption
RSI divergence (deferred)
Trend channel lines (impulse start line + retracement low line)
Model design: State Classifier (XGBoost on tabular features) → Retracement Termination Predictor (LSTM) → Trend Score function

Current working example: BTCUSDT 1H shows downtrend with 5 legs, CHoCH at ~98K, global R3 at 118.2% (confirmed CHoCH breach), current phase retracement. System correctly identifies sell setup conditions.
Next pending task: Complete Cell 6 of 10_lag_analysis.ipynb with full structural overlay (zigzags + BOS/CHoCH + internal structure) on same chart as lag bands, using identical parameters to 08_trend_id.ipynb.