import type { ReadinessState } from "@/lib/types";

/** Canonical buckets aligned with heatmap / breakdown (lowercase keys). */
export const UNIVERSE_CATEGORY_ORDER = ["crypto", "forex", "commodity", "synthetic", "indices"] as const;
export type UniverseCanonicalCategory = (typeof UNIVERSE_CATEGORY_ORDER)[number];

export function normalizeUniverseCategory(raw: string | undefined): UniverseCanonicalCategory {
  const c = (raw || "").trim().toLowerCase();
  if (c === "commodities" || c === "commodity") return "commodity";
  if (c === "indices" || c === "index") return "indices";
  if (c === "synthetic") return "synthetic";
  if (c === "forex") return "forex";
  if (c === "crypto") return "crypto";
  if (c === "stocks" || c === "etfs") return "forex";
  return "forex";
}

export function formatUniverseCategoryLabel(cat: string): string {
  return cat.toUpperCase();
}

const READINESS_STACK_KEYS = ["FULL", "PARTIAL", "ERROR", "UNSCANNED"] as const;

export type ReadinessStackKey = (typeof READINESS_STACK_KEYS)[number];

export function normalizeReadinessState(state: ReadinessState | undefined): ReadinessStackKey {
  if (state === "FULL" || state === "PARTIAL" || state === "ERROR") return state;
  return "UNSCANNED";
}

export function buildMarketDistributionRows(
  setups: { category: string; readiness_state?: ReadinessState }[],
): Array<{ label: string } & Record<ReadinessStackKey, number>> {
  const byCat: Record<string, Record<ReadinessStackKey, number>> = {};
  for (const key of UNIVERSE_CATEGORY_ORDER) {
    byCat[key] = { FULL: 0, PARTIAL: 0, ERROR: 0, UNSCANNED: 0 };
  }
  for (const s of setups) {
    const cat = normalizeUniverseCategory(s.category);
    if (!byCat[cat]) {
      byCat[cat] = { FULL: 0, PARTIAL: 0, ERROR: 0, UNSCANNED: 0 };
    }
    const rs = normalizeReadinessState(s.readiness_state);
    byCat[cat][rs] += 1;
  }
  return UNIVERSE_CATEGORY_ORDER.map((k) => ({
    label: formatUniverseCategoryLabel(k),
    ...byCat[k]!,
  }));
}

export const MARKET_DIST_READINESS_COLORS: Record<ReadinessStackKey, string> = {
  FULL: "#26A69A",
  PARTIAL: "#F5A623",
  ERROR: "#EF5350",
  UNSCANNED: "#434651",
};
