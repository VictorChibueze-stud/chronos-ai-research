# Postgres Scanner Recovery Runbook

## 1) Confirm Runtime Target

- Verify `DATABASE_URL` points to Postgres.
- Verify migration head:
  - `.venv\Scripts\alembic.exe current`
  - expected: `20260401_0005 (head)`

## 2) Dry-run Backfill

- Run:
  - `.venv\Scripts\python.exe scripts/backfill_scanner_state.py`
- This runs in dry-run mode by default and reports per-source deltas.

## 3) Apply Backfill

- Run:
  - `.venv\Scripts\python.exe scripts/backfill_scanner_state.py --apply`
- Default source order is:
  1. `ikenga.db`
  2. `data/chronos.db`

## 4) Validate Coverage

- Run:
  - `.venv\Scripts\python.exe scripts/validate_db_migration.py --target-url "<DATABASE_URL>" --source "ikenga.db" --source "data/chronos.db"`
- Check key table counts and compare with source snapshots.

## 5) Scan Health Check

- Trigger scan:
  - `POST /api/setups/scan`
- Confirm status:
  - `GET /api/system/scan-status`
  - Verify `in_progress` toggles true and stage advances beyond initial state.
  - If failure occurs, inspect `last_error` in the status payload.
