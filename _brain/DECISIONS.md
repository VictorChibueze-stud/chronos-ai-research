# IKENGA — Decision log

---
**Date:** April 2026
**Category:** Documentation
**Decision:** Consolidated docs — single canonical name (Ikenga), single architecture doc, deleted stale runbook and deferred-roadmap files
**Why:** Three overlapping sources (`README.md`, `CLAUDE.md`, `.github/copilot-instructions.md`) restated the same invariants and disagreed on naming. `docs/systemspec.md` described a Phase-0 layout that no longer matched the codebase. Replaced with `docs/architecture.md`, slimmed `copilot-instructions.md` to a pointer file, added a project-level `AGENTS.md`, and rewrote frontend docs from boilerplate.

---
**Date:** April 2026
**Category:** Infrastructure
**Decision:** Universe and PaperUniverse tables for managed symbol sets
**Why:** Hardcoded symbol lists in scanner config didn't survive multi-environment work (live vs paper, Deriv vs Binance). Promoting universes to first-class DB rows lets the UI manage them and lets paper trading run a different set than live.

---
**Date:** April 2026
**Category:** Architecture
**Decision:** Manual structure overrides protected from eviction
**Why:** Operator-pinned zones encode discretionary insight that the scoring system cannot reproduce. Marking `is_manual_override=True` removes the setup from LRU eviction so important context survives scan cycles.

---
**Date:** April 2026
**Category:** Execution
**Decision:** Paper trading engine + contract spec seeding before any live execution
**Why:** Position sizing and SL/TP rounding require accurate contract metadata. Seeding `ContractSpec` first, then exercising the lifecycle on paper, surfaces sizing bugs before they touch real capital.

---
**Date:** March 2026
**Category:** Infrastructure
**Decision:** Postgres-compatible migration path via Alembic
**Why:** SQLite is fine for research but limits concurrent scanner + API + frontend access in production-style deployments. Alembic-managed schema with backfill scripts lets the same code target either backend.

---
**Date:** February 2026
**Category:** Logic
**Decision:** Market state cache + candidate walker / impulse caches
**Why:** Re-running the structural walker on every API request is too expensive at universe scale. Caching intermediate candidate impulses and global market state lets reads stay fast while the scanner owns the write side.

---
**Date:** January 2026
**Category:** Logic
**Decision:** Per-symbol analysis param overrides (`SymbolAnalysisParams`)
**Why:** A single global filter threshold doesn't fit symbols with different volatility regimes. Per-symbol overrides let the operator tune without touching code or YAML for one-off cases.

---
**Date:** December 2025
**Category:** Architecture
**Decision:** MonitoredSetup scoring fields formalized on the table
**Why:** Score components were derived ad-hoc per query. Materializing them on the row makes ranking, eviction, and UI sorting deterministic and auditable.

---
**Date:** April 2025
**Category:** Naming
**Decision:** Renamed system from Chronos AI to IKENGA
**Why:** Named after the Igbo deity of personal achievement. The system encodes years of manual trading methodology — the name must reflect that origin and weight.

---
**Date:** March 2025
**Category:** Architecture
**Decision:** Signal gate added as hard blocker during high-impact macro events
**Why:** FOMC, NFP, and similar events create artificial volatility that breaks structural analysis. The gate prevents the system from taking positions it would reject manually.

---
**Date:** March 2025
**Category:** Infrastructure
**Decision:** SQLite chosen over live broker API calls for candle data
**Why:** Caching avoids rate limits and keeps signal logic fast. Local cache enables backtesting and replay without broker dependency.

---
**Date:** February 2025
**Category:** Logic
**Decision:** VADER replaced by local Gemma for sentiment classification
**Why:** VADER is rule-based and misses financial nuance. Gemma running locally avoids API costs and latency, and can later be fine-tuned on financial context.

---
**Date:** January 2025
**Category:** Architecture
**Decision:** Core trading files declared protected from Cursor edits
**Why:** Cursor was making unsolicited changes to trading logic that violated structural rules. Protected files enforce that only deliberate human-approved changes reach core logic.

---
**Date:** January 2025
**Category:** Logic
**Decision:** Trend identification switched from PIP-based to scoring-based approach
**Why:** Absolute price thresholds were noisy and non-adaptive. Scoring-based filtering (parent ratio, momentum ratio, dominance ratio) allows impulse validation relative to context and prior moves.

---
**Date:** December 2024
**Category:** Architecture
**Decision:** Hard separation of deterministic Python (core) and LLM reasoning layer
**Why:** LLMs are non-deterministic and hallucinate math. By isolating all market calculations to Python and having LLMs call deterministic tools, the system remains reproducible and auditable.

---
**Date:** December 2024
**Category:** Architecture
**Decision:** Recursive structural depth walker implementation
**Why:** Market structure is fractal; a trend's retracement can be analyzed as its own trend. The walker detects when a retracement CHoCH zone is crossed by a subsequent impulse, creating the next depth level.

---
**Date:** November 2024
**Category:** Infrastructure
**Decision:** Multi-broker adapter pattern (Deriv, Binance, yfinance, FTMO)
**Why:** Single-broker dependencies are fragile. Adapters normalize all sources to a Candle object, allowing strategy logic to remain broker-agnostic.

---
**Date:** November 2024
**Category:** Logic
**Decision:** CHoCH requires ≥2 confirmed impulses before a zone is valid
**Why:** A single impulse provides no reference level for a character change. The CHoCH zone is defined between the start of the most recent impulse and the end (BOS) of the prior impulse.

---
**Date:** October 2024
**Category:** Architecture
**Decision:** Retracement depth preferred over Fibonacci ratios
**Why:** Fibonacci ratios are heuristic. Retracement depth (normalized as % of impulse size) is mechanistically computed and more consistent with the scoring-based trend ID approach.

---
**Date:** October 2024
**Category:** Visualization
**Decision:** BOS and CHoCH levels extend to chart right edge for continuity
**Why:** Truncating levels at the last confirmed impulse creates visual gaps and ambiguity. Right-edge extension shows where the structure is currently active and unbroken.

---
**Date:** September 2024
**Category:** Logic
**Decision:** Internal structure indices offset into global candle index space before visualization
**Why:** Nested structures are extracted on slices (local indices). Offsetting them back to global indices ensures correct chart positioning and historical reproducibility.

---
**Date:** September 2024
**Category:** Logic
**Decision:** EMA crossover markers intentionally suppressed inside internal retracements
**Why:** Crossovers inside retracements are noise; they reflect minor pullback reversals, not trend decisions. Suppression focuses on structural-level signals.

---
**Date:** August 2024
**Category:** Architecture
**Decision:** Callback-based orchestrator for setup lifecycle (trigger → confirm → execute → settle)
**Why:** Trading is state-driven. Explicit state machines (triggered, confirmed, executed) prevent accidental double-entries and ensure signal gate and risk checks run at the right time.

---
**Date:** August 2024
**Category:** Infrastructure
**Decision:** Database-first monitoring via MonitoredSetup table (capped at 50, LRU eviction)
**Why:** Scanner runs 4-hourly across 350+ pairs. Capping at 50 and evicting by score ensures the watchlist stays focused while the database serves as the source of truth.

---
**Date:** July 2024
**Category:** Infrastructure
**Decision:** Three-tier filtering for multi-symbol scanning (correlation → confluence → scoring)
**Why:** 350+ pairs is too many to track individually. First, group by correlation to reduce false setups. Next, check confluence (HTF + LTF alignment). Finally, score by structural quality.

---
**Date:** July 2024
**Category:** Architecture
**Decision:** Three optional filters for trend identification (parent ratio, momentum ratio, dominance ratio)
**Why:** Impulses can be valid even if smaller than expected. Optional filters allow macro exploration (tight filters for strong trends) and micro exploration (loose filters for internal structure).

---
**Date:** June 2024
**Category:** Research
**Decision:** Notebooks are deterministic research vehicles, not live systems
**Why:** Out-of-order execution and stale kernels break reproducibility. Notebooks must restart kernel and run all cells, and parameter changes go to a single config reference.

---
**Date:** June 2024
**Category:** Testing
**Decision:** Integration tests use real SQLite DB, no mocking the data layer
**Why:** Mocks hide integration bugs. Real DB tests are slower but catch serialization, transaction, and schema errors that matter in production.

---
**Date:** May 2024
**Category:** Infrastructure
**Decision:** FastAPI backend with Pydantic request/response schemas as the contract
**Why:** Ensures API clients (frontend, notebooks, agents) consume validated, typed responses. Schema mismatches are caught early.
