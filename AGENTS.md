# Ikenga — Agent Guide

This is the project-level entry point for any AI coding agent working
in this repo. It is intentionally short. Read the linked canonical
docs before making changes.

> The product is **Ikenga**. The folder name (`chronos-ai/`) is legacy.

## Read these first

1. [`CLAUDE.md`](CLAUDE.md) — canonical current-state document
   (commands, architecture, invariants, key data flows, DB tables,
   API endpoints).
2. [`.cursorrules`](.cursorrules) — concise rules of engagement
   (protected files, hard constraints, tech stack).
3. [`docs/architecture.md`](docs/architecture.md) — module map and
   data flow diagram.
4. [`_brain/DECISIONS.md`](_brain/DECISIONS.md) — why the system is
   shaped this way.
5. [`_brain/TASKS.md`](_brain/TASKS.md) — what is in progress vs done.

For frontend work, also read:

- [`frontend/AGENTS.md`](frontend/AGENTS.md)
- [`frontend/CLAUDE.md`](frontend/CLAUDE.md)
- [`frontend/README.md`](frontend/README.md)

## Hard rules (no exceptions)

- **Protected files** (see `.cursorrules` for the full list) must
  never be modified without explicit human instruction:
  `src/core/trend_id.py`, `src/core/structural_walker.py`,
  `src/core/choch_zone.py`, `src/core/structure_levels.py`,
  `src/core/retracement_analysis.py`, `src/backtest/engine.py`,
  `config/timeframe_windows.yaml`, `src/adapters/deriv_data.py`,
  `src/adapters/binance_data.py`.
- **All trading logic lives in `src/core/`.** Never put trade
  decisions in UI, API, or LLM prompts.
- **All candle data goes through the cache layer**
  (`src/cache/candle_store.py`). Never call broker APIs directly
  from signal logic.
- **The LLM layer never does numeric market math.** It consumes
  structured snapshots and calls deterministic Python tools in
  `src/llm/tools.py`.
- **Core functions are pure and stateless.** No I/O, no side
  effects, no external API calls inside `src/core/`.
- **Configuration is data, not code.** Tunable parameters go to
  `config/*.yaml`.
- **Add no new dependencies without asking.**

## Trading invariants (do not regress)

- Trend ID is **scoring-based**, not PIP-based.
- CHoCH requires **≥2 confirmed impulses** before a zone is valid.
- BOS and CHoCH levels **extend to the chart right edge**.
- **Retracement depth** is preferred over Fibonacci ratios.
- EMA crossover markers inside internal retracements are
  **intentionally suppressed**.
- Internal structure indices are **offset into global candle index
  space** before plotting.

## Workflow

- If you change `src/core/`, update tests in `tests/` in the same
  change.
- If you change `frontend/`, run `npm run build` before declaring
  done.
- Use `.venv\Scripts\` on Windows; the repo runs on Python 3.10+.
- Notebooks are deterministic: restart kernel and run all cells
  before treating output as canonical.

## When in doubt

Stop and describe the issue rather than guessing at trading logic.
Cascading bugs in protected files are expensive to unwind.
