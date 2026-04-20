# Ikenga — Copilot Instructions

> The product is **Ikenga**. The folder name (`chronos-ai/`) is legacy.

This file is intentionally short. The canonical sources of agent
guidance are:

1. [`AGENTS.md`](../AGENTS.md) — project-level agent guide and hard rules
2. [`CLAUDE.md`](../CLAUDE.md) — current-state document (commands,
   architecture, invariants, DB tables, API endpoints)
3. [`.cursorrules`](../.cursorrules) — protected files and tech-stack
   conventions
4. [`docs/architecture.md`](../docs/architecture.md) — module map and
   data flow

For frontend work also read:

- [`frontend/AGENTS.md`](../frontend/AGENTS.md)
- [`frontend/CLAUDE.md`](../frontend/CLAUDE.md)
- [`frontend/README.md`](../frontend/README.md)

## Non-negotiables

- Deterministic Python owns all numeric market math. The LLM layer
  consumes structured snapshots and calls deterministic tools — it
  never invents math.
- Protected files in `src/core/`, `src/backtest/engine.py`,
  `src/adapters/{deriv,binance}_data.py`, and
  `config/timeframe_windows.yaml` must not be modified without
  explicit human instruction.
- All candle data goes through `src/cache/candle_store.py`.
- Trend ID is scoring-based, not PIP-based.
- CHoCH requires ≥2 confirmed impulses.
- BOS and CHoCH levels extend to the chart right edge.
- Retracement depth is preferred over Fibonacci.
- EMA crossover markers inside internal retracements are
  intentionally suppressed.
- No new dependencies without asking.

## Workflow

- If you change `src/core/`, update tests in the same change.
- If you change `frontend/`, run `npm run build` before declaring
  done.
- Notebooks: restart kernel and run all cells before treating output
  as canonical.

If a task seems to require violating any of the above, stop and
describe the issue rather than guessing.
