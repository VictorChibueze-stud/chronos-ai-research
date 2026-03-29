# Ikenga System Specification – Trend-Following Research Lab

## 1. Purpose and Scope

Ikenga is a research-oriented project to design, test, and iteratively refine systematic trading strategies with a strong focus on:

- Trend-following and pullback entries.
- Multi-timeframe analysis (e.g., 1D, 4H, 1H, 15M, 5M).
- Clean separation between **data**, **features**, **strategy**, **risk management**, **backtesting**, and **LLM orchestration**.
- Initial universe: Deriv synthetic indices (e.g., Volatility 10 Index, Volatility 25 Index).
- Later: ability to reuse the same core modules for real markets (FX, indices, etc.) by swapping adapters.

Non-goals:
- No discretionary GUI trading terminal.
- No guaranteed profitability.
- No copy-trading service or managing third-party money.

## 2. High-Level Architecture

Ikenga is structured into the following logical components:

1. **Data Adapters (`src/adapters/`)**
   - Responsibility: Fetch OHLCV candles from external sources (e.g., Deriv WebSocket, CSV files).
   - Output: Standardized list/DataFrame of candles with fields `(timestamp, open, high, low, close, volume)`.

2. **Core Feature Engine (`src/core/features.py`)**
   - Responsibility: Convert OHLCV series into a rich but structured description of the market state:
     - Classic indicators (moving averages, volatility, momentum).
     - Price structure features (swing highs/lows, BOS/CHOCH, fair value gaps, liquidity sweeps, order blocks).
     - Regime tags (trending vs ranging, volatility state).
   - Pure, stateless, broker-agnostic.

3. **Agentic Microservice Architecture (Strategy & Orchestration)**
  - Responsibility: Split reasoning (LLM) from deterministic execution (Python tools).
  - Design principles:
    - The LLM performs high-level reasoning, pattern recognition, and plans trade ideas in natural language.
    - All numeric trading math (position sizing, exact SL/TP calculation, risk clamps) is performed by small, audited Python tools in `src/llm/tools.py` and `src/core/risk.py`.
    - The strategy interface (`src/core/signals.py`) remains deterministic: it accepts structured features and validated numeric parameters from the tooling layer and emits clear `Signal` objects (no free-form numeric math inside the LLM).
    - Orchestration: the LLM constructs a plan (e.g., preferred direction, rationale, timeframe priorities) and calls the deterministic toolset to compute levels and sizing. This reduces agentic risk and ensures the system enforces hard guardrails.
  - Benefits: auditability, reproducibility, and strict enforcement of risk limits while preserving the LLM's ability to reason and explain.

4. **Risk Engine (`src/core/risk.py`)**
   - Responsibility: Position sizing and risk constraints:
     - Risk per trade (fixed amount or % of equity).
     - Max daily/weekly loss.
     - Max account drawdown / kill-switch.
   - Broker-agnostic (no knowledge of Deriv specifics, just uses prices and tick values).

5. **Backtest Engine (`src/backtest/`)**
   - `engine.py`: Replays historical data, calls the feature engine and strategy module at each step, simulates orders and P&L.
   - `metrics.py`: Computes P&L, R-multiples, drawdowns, equity curves, and other evaluation metrics.
   - Uses the same strategy + risk code intended for live usage, to avoid drift.

6. **LLM / Orchestrator Layer (`src/llm/`)**
   - Responsibility: Provide structured JSON payloads and helpers for LLM-driven orchestration (e.g., Langflow).
   - LLM should:
     - Orchestrate calls (data → features → strategy → risk).
     - Explain decisions in price-action terms.
   - LLM should **not** contain the core strategy rules; those live in Python and are fully deterministic.

7. **Execution Adapter (`src/adapters/execution_stub.py`)**
   - For now, a stub (no real live trading).
   - Future: send orders to Deriv or another broker while respecting risk constraints and logging all actions.

## 3. Data Model

### 3.1 Candle

A standard candle structure used across the project:

- `timestamp` (UTC, ISO string or epoch).
- `open` (float).
- `high` (float).
- `low` (float).
- `close` (float).
- `volume` (float, can be 0 or synthetic for instruments without volume).

### 3.2 Features

Per timeframe, the feature engine will produce a structured dictionary, including (but not limited to):

- Latest bar snapshot (open, high, low, close, change%).
- Selected indicators (e.g., EMA20, EMA50, ATR%).
- Regime tags (e.g., is_trending_up, is_trending_down, is_range, is_vol_spike).
- Structure map:
  - recent swing highs/lows,
  - recent BOS/CHOCH events,
  - FVG zones and whether they are filled,
  - potential order block zones.
- Recent-window summaries (slopes, volatility, max drawdown, % up bars).

Exact fields will be refined in Phase 1 when porting over the existing indicator and ICT logic.

### 3.3 Signal Object

The strategy layer will work with a clear signal object (to be defined precisely in `src/core/signals.py`), conceptually containing:

- `status`: `"no_trade" | "long" | "short"`.
- `direction`: `"long" | "short" | null`.
- `entry_price`: float or null.
- `stop_loss_price`: float or null.
- `take_profit_price`: float or null.
- `risk_reward`: float (R:R ratio).
- `horizon_minutes`: integer.
- `metadata`: dict with diagnostics (e.g., which timeframe patterns supported the decision).

## 4. Configuration (`src/config/`)

- `symbols.yaml`: Mapping of human-readable symbol names to broker codes (e.g., "Volatility 10 Index" → "R_10").
- `params.yaml`: Strategy and risk parameters, per symbol or per market group:
  - Timeframes used (e.g., D1, H4, 15M).
  - Trend thresholds (e.g., EMA and ADX conditions).
  - Risk per trade.
  - Max holding period, etc.

## 5. Development Phases

The project is divided into phases to keep progress organized and traceable:

- **Phase 0 – Setup & Hygiene (current):**
  - Repo structure, config files, system specification, and progress tracking.
- **Phase 1 – Core Feature Engine:**
  - Refactor existing indicator and ICT-style logic into `src/core/features.py` with unit tests.
- **Phase 2 – Data Adapters:**
  - Implement Deriv and local CSV data adapters.
- **Phase 3 – Backtest Engine:**
  - Implement generic backtest loop and metrics.
- **Phase 4 – Strategy API:**
  - Define strategy interfaces and an initial baseline strategy in `signals.py`.
- **Phase 5 – Risk Engine:**
  - Implement risk sizing, drawdown rules, and tests.
- **Phase 6 – LLM Integration:**
  - Integrate with Langflow/LLM using JSON schemas, keeping decisions deterministic.

## 6. Testing Strategy

- Use `pytest` for:
  - Unit tests of indicator and feature functions.
  - Sanity checks for data adapters.
  - Backtest engine logic with simple toy strategies.
- Aim for deterministic behavior, especially in feature and strategy layers.

## 7. Future Work / Productization

- Add real-market data adapters and execution adapters.
- Package `src/core` and `src/backtest` as reusable libraries.
- Optional: build a small API or dashboard on top of the backtest engine for experimentation.
