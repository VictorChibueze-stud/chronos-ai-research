import type { AnalysisDevParams } from "@/lib/types";

/** Six user-facing GET /api/analysis query overrides persisted per symbol. */
export type AnalysisCoreParams = Pick<
  AnalysisDevParams,
  | "use_parent_relative_filter"
  | "min_impulse_parent_ratio"
  | "use_momentum_filter"
  | "min_momentum_ratio"
  | "use_dominance_filter"
  | "min_dominance_ratio"
>;

export function analysisParamsStorageKey(symbol: string): string {
  return `ikenga.params.${symbol.trim().toUpperCase()}`;
}

export function loadCoreAnalysisParams(symbol: string): Partial<AnalysisCoreParams> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(analysisParamsStorageKey(symbol));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    return parsed as Partial<AnalysisCoreParams>;
  } catch {
    return null;
  }
}

export function saveCoreAnalysisParams(symbol: string, params: AnalysisCoreParams): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(analysisParamsStorageKey(symbol), JSON.stringify(params));
  } catch {
    // quota / private mode
  }
}

export function clearCoreAnalysisParams(symbol: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(analysisParamsStorageKey(symbol));
  } catch {
    // no-op
  }
}

export function pickCoreParams(p: AnalysisDevParams): AnalysisCoreParams {
  return {
    use_parent_relative_filter: p.use_parent_relative_filter,
    min_impulse_parent_ratio: p.min_impulse_parent_ratio,
    use_momentum_filter: p.use_momentum_filter,
    min_momentum_ratio: p.min_momentum_ratio,
    use_dominance_filter: p.use_dominance_filter,
    min_dominance_ratio: p.min_dominance_ratio,
  };
}
