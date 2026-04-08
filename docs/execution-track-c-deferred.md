# Track C — Deferred execution work

This document scopes work intentionally **not** implemented in v1 (Deriv paper execution only). See the roadmap plan in the repository for full context.

## 1. Binance Demo provider

- New module: `src/execution/providers/binance.py`
- Signed `POST /api/v3/order`, `newClientOrderId`, user data stream for fills
- Config: `demo-api.binance.com` vs `testnet.binance.vision` via environment
- Tests: `tests/test_execution_binance.py`

## 2. Integrations UI revamp

- Richer onboarding on `frontend/src/app/settings/integrations/page.tsx`
- Optional API extensions in `src/api/routers/integrations.py`
- Still use `.env` for secrets until a future encrypted local store is justified

## 3. FTMO / MetaTrader 5

- No public FTMO REST order API; automation goes through **MT5** (or cTrader) attached to a logged-in terminal
- Optional `src/execution/providers/mt5_bridge.py`, `MetaTrader5` dependency (Windows-oriented), operational runbook
- Keep `src/adapters/ftmo_data.py` as read-only metrics if still useful

## Order

Implement **Binance Demo** first after Deriv paper is stable, then **integrations UX**, then **FTMO/MT5** only if prop execution in-repo remains a goal.
