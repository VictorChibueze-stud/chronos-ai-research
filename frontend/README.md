# Ikenga Frontend

Next.js 16 (App Router) + React 19 + TailwindCSS v4. Acts as the
operator console for the Ikenga research backend.

> The page tree mixes **live, backend-driven** views with **demo-mode**
> surfaces. Preserve that distinction when editing — see the per-page
> notes below.

## Quick start

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build (run before commit to catch type errors)
npm run lint
```

The dev server expects the FastAPI backend at the URL in
`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). Start the
backend with `python scripts/run_api.py` from the repo root.

## Page map

Live (backend-driven):

- `app/scanner/page.tsx` — multi-symbol scanner output
- `app/signals/page.tsx` — actionable signals derived from monitored setups
- `app/market/page.tsx` — market cockpit
- `app/universe/page.tsx` — universe management and bootstrap state
- `app/deep-dive/page.tsx` — per-symbol structural analysis
- `app/trades/page.tsx` — execution orders + events
- `app/settings/integrations/page.tsx` — broker integration onboarding

Demo / placeholder surfaces (do not assume backend wiring):

- `app/analytics/page.tsx`
- `app/risk/page.tsx`
- `app/radar/page.tsx`
- `app/watchtower/page.tsx`
- `app/command/page.tsx`

## Conventions

- **HTTP**: every backend call goes through the axios client in
  `src/lib/api.ts`. Do not add raw `fetch` calls.
- **Types**: response shapes live in `src/lib/types.ts`. Keep them in
  sync with the FastAPI Pydantic schemas.
- **Charting**: `components/candle-chart.tsx` (and any other
  `lightweight-charts` consumer) must be loaded with
  `dynamic(() => import(...), { ssr: false })`. The library breaks
  under SSR.
- **Shared UI primitives** that get reused across pages belong in
  `components/chronos-ui.tsx` and `components/ui/*`.
- **Storage**: per-user analysis param overrides go through
  `src/lib/analysis-params-storage.ts`.

## Next.js 16 caveats

This is **not the Next.js you know**. Read
[`frontend/CLAUDE.md`](CLAUDE.md) and skim
`node_modules/next/dist/docs/` before making framework-level changes.
APIs, conventions, and file structure differ from older Next.js
patterns commonly seen in training data.

## Agent rules

For agent-specific rules (what to never do, when to run `npm run
build`, how demo pages should be treated), see
[`frontend/AGENTS.md`](AGENTS.md).
