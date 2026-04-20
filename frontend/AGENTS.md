# Frontend Agent Rules

Self-contained agent rules for the `frontend/` workspace. Do **not**
delegate upward to any parent `AGENTS.md` outside this repo — the
project root has its own `AGENTS.md` for project-wide context.

For framework-level Next.js 16 caveats, read
[`frontend/CLAUDE.md`](CLAUDE.md) and the local docs in
`node_modules/next/dist/docs/` before making structural changes.

## Hard rules

- **No raw `fetch`**. All backend calls go through `src/lib/api.ts`.
- **No market math in the UI.** Computed structure, scores, levels,
  and signals come from the backend. The frontend formats and
  displays — it does not derive trading decisions.
- **Never bypass the cache layer** by calling broker APIs directly
  from the browser (Binance/Deriv keys are not exposed client-side
  anyway, but do not introduce client-side broker calls under any
  circumstances).
- **`lightweight-charts` is client-only.** Wrap any chart component
  in `dynamic(() => import(...), { ssr: false })`.
- **Preserve demo-mode pages.** `analytics`, `risk`, `radar`,
  `watchtower`, and `command` are intentionally not wired to live
  data. Do not "fix" them by adding API calls unless a task
  explicitly asks for that page to go live.

## Editing workflow

1. Make your edit.
2. If you touched response shapes or added a new endpoint client,
   update `src/lib/types.ts` to match the FastAPI Pydantic schema.
3. Run `npm run build` before declaring done — it catches type
   errors that `npm run dev` will silently tolerate.
4. Run `npm run lint` for broader edits.

## File ownership

- `src/app/*/page.tsx` — route-level pages.
- `src/components/` — reusable UI. Charting, sidebars, badges, panels.
- `src/components/ui/` — atomic shadcn-style primitives.
- `src/lib/api.ts` — single axios instance + endpoint helpers.
- `src/lib/types.ts` — TypeScript mirrors of backend schemas.
- `src/lib/*` — small client-side helpers (storage, formatting,
  category mapping).

## Backend coupling

- Default backend URL: `NEXT_PUBLIC_API_URL` → `http://localhost:8000`.
- Start the backend with `python scripts/run_api.py` from the repo
  root.
- API routers live under `src/api/routers/` in the Python project.
  When you add a new client helper, mirror the router name where
  possible.

## Pitfalls

- The Next.js version here is ahead of common training data. Verify
  unfamiliar APIs against `node_modules/next/dist/docs/` rather than
  guessing from memory.
- Tailwind v4 syntax differs from v3 — do not auto-migrate v3 patterns.
- The page tree on disk is the source of truth for routes; do not
  rely on a separate route manifest.
