/**
 * Strategy readiness pipeline for Signal Board (UI-R2).
 * Derived from GET /api/setups Setup fields only — no per-symbol analysis fetch.
 */

import type { Setup } from "@/lib/types";

export type ReadinessFilter = "ALL" | "FULL" | "PARTIAL" | "EARLY";

export type FilterAssetClass =
  | "ALL"
  | "CRYPTO"
  | "FOREX"
  | "SYNTHETIC"
  | "COMMODITY"
  | "EQUITIES"
  | "INDICES";

/** Unknown classes map to null — visible only when asset filter is ALL. */
export function normalizeAssetClassForFilter(category: string | undefined): FilterAssetClass | null {
  const c = String(category || "").toLowerCase();
  if (c === "crypto") return "CRYPTO";
  if (c === "forex") return "FOREX";
  if (c === "synthetic") return "SYNTHETIC";
  if (c === "commodity" || c === "commodities") return "COMMODITY";
  if (c === "indices" || c === "index") return "INDICES";
  if (c === "equities" || c === "stocks") return "EQUITIES";
  return null;
}

export function normalizeTrend(value: string | undefined): Setup["trend"] {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("down")) return "down";
  if (normalized.includes("up")) return "up";
  return "range";
}

/** CHoCH step: fragile string heuristic — "not yet reached" means zone not reached. Empty = unmet. */
export function isChochHeuristicMet(waitingForRaw: string): boolean {
  const t = String(waitingForRaw ?? "").trim();
  if (!t) return false;
  const lower = t.toLowerCase();
  return !lower.includes("not yet reached");
}

export interface PipelineFlags {
  trend: boolean;
  retracement: boolean;
  depth: boolean;
  choch: boolean;
  candidate: boolean;
}

export function computePipelineFlags(setup: {
  trend: Setup["trend"];
  current_phase: Setup["current_phase"];
  pullback_depth: number;
  waiting_for_raw: string;
  ema_signal: Setup["ema_signal"];
}): PipelineFlags {
  const trendOk = setup.trend === "up" || setup.trend === "down";
  const retracementOk = setup.current_phase === "retracement";
  const depthOk = setup.pullback_depth >= 1;
  const chochOk = isChochHeuristicMet(setup.waiting_for_raw);
  const ema = setup.ema_signal;
  const candidateOk = ema === "LONG" || ema === "SHORT";
  return {
    trend: trendOk,
    retracement: retracementOk,
    depth: depthOk,
    choch: chochOk,
    candidate: candidateOk,
  };
}

export function computeMetCount(flags: PipelineFlags): number {
  return (
    (flags.trend ? 1 : 0) +
    (flags.retracement ? 1 : 0) +
    (flags.depth ? 1 : 0) +
    (flags.choch ? 1 : 0) +
    (flags.candidate ? 1 : 0)
  );
}

export function readinessBucket(metCount: number): "FULL" | "PARTIAL" | "EARLY" | "NONE" {
  if (metCount === 5) return "FULL";
  if (metCount >= 3) return "PARTIAL";
  if (metCount >= 1) return "EARLY";
  return "NONE";
}

/**
 * Top 50 by rank when present, else by score: `universe_rank` ascending (nulls last),
 * then `trend_score` descending, then `symbol` ascending.
 */
export function selectTop50Setups(setups: Setup[]): Setup[] {
  const copy = [...setups];
  copy.sort((a, b) => {
    const ar = a.universe_rank;
    const br = b.universe_rank;
    const aHas = ar != null && Number.isFinite(Number(ar));
    const bHas = br != null && Number.isFinite(Number(br));
    if (aHas && bHas) return Number(ar) - Number(br);
    if (aHas && !bHas) return -1;
    if (!aHas && bHas) return 1;
    const sc = b.trend_score - a.trend_score;
    if (sc !== 0) return sc;
    return String(a.symbol).localeCompare(String(b.symbol));
  });
  return copy.slice(0, 50);
}

export type UniverseKey = "multi_asset" | "synthetic" | "crypto";

/**
 * Mirror of src/api/routers/setups.py::_infer_universe for rows whose
 * backend `universe` column is null (legacy pre-backfill data).
 */
function inferUniverseClient(setup: Setup): string {
  const sym = (setup.symbol ?? "").toUpperCase();
  if (sym.endsWith("USDT") || sym.endsWith("BTC")) return "crypto";
  const SYNTH = ["R_", "1HZ", "BOOM", "CRASH", "JD", "OTC_", "STEP", "WLD", "RB"];
  if (SYNTH.some((p) => sym.startsWith(p))) return "synthetic";
  if ((setup.category ?? "") === "synthetic") return "synthetic";
  if ((setup.category ?? "") === "crypto") return "crypto";
  return "multi_asset";
}

/**
 * Top-N setups within a single universe (or across all when `universe === "all"`).
 * Sort key matches `selectTop50Setups`: universe_rank asc (nulls last),
 * then trend_score desc, then symbol asc.
 */
export function selectTopNByUniverse(
  setups: Setup[],
  universe: UniverseKey | "all",
  n: number = 50,
): Setup[] {
  const filtered =
    universe === "all"
      ? setups
      : setups.filter((s) => (s.universe ?? inferUniverseClient(s)) === universe);
  const copy = [...filtered];
  copy.sort((a, b) => {
    const ar = a.universe_rank;
    const br = b.universe_rank;
    const aHas = ar != null && Number.isFinite(Number(ar));
    const bHas = br != null && Number.isFinite(Number(br));
    if (aHas && bHas) return Number(ar) - Number(br);
    if (aHas && !bHas) return -1;
    if (!aHas && bHas) return 1;
    const sc = b.trend_score - a.trend_score;
    if (sc !== 0) return sc;
    return String(a.symbol).localeCompare(String(b.symbol));
  });
  return copy.slice(0, n);
}

export function depthBadgeLabel(depth: number): string {
  if (depth <= 0) return "D0";
  return `D${Math.min(3, depth)}`;
}

/** Met depth label color (spec: #2962FF for D1/D2/D3). */
export function depthBadgeColor(depth: number): string {
  if (depth <= 0) return "#2A2E39";
  return "#2962FF";
}
