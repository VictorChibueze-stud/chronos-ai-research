import type {
  AccountTargets,
  AnalysisDevParams,
  AnalysisResponse,
  AlertZone,
  ActiveListMutationResponse,
  ActiveListResponse,
  CandleBar,
  BrokerConnectionTestRequest,
  BrokerConnectionTestResponse,
  ExecutionOrderEventsResponse,
  ExecutionOrderListResponse,
  ExecutionStatusResponse,
  FromSignalRequest,
  FundamentalEventsResponse,
  FundamentalNewsResponse,
  HealthResponse,
  NormalizedOrderIntent,
  OrderSubmissionResponse,
  PaperAccount,
  PaperPerformance,
  PaperTrade,
  ScanJobLog,
  ScanStartResponse,
  IntegrationsStatusResponse,
  KillswitchResponse,
  ManualRecomputeLayer,
  ManualOverride,
  SignalHistoryResponse,
  SymbolParamsResponse,
  Setup,
  ScanSettings,
  ScanSettingsHistoryRow,
  SetupSummary,
  UniverseRankingStatus,
  UniverseSettings,
  UniverseStats,
} from "@/lib/types";
import { DEFAULT_ANALYSIS_DEV_PARAMS } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type RequestOptions = RequestInit & { next?: { revalidate: number } };

export class ApiError extends Error {
  status: number;
  reason: string;
  detail: unknown;

  constructor(message: string, status: number, reason = "", detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail: unknown = null;
    let reason = "";
    let message = `API request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = payload?.detail ?? payload;
      if (detail && typeof detail === "object" && "reason" in detail) {
        reason = String((detail as { reason?: unknown }).reason ?? "");
      }
      const formatted = formatApiErrorDetail(detail);
      if (formatted) {
        message = formatted;
      }
    } catch {
      // Non-JSON response body; retain status-based message.
    }
    throw new ApiError(message, response.status, reason, detail);
  }

  return (await response.json()) as T;
}

function formatApiErrorDetail(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    const m = (detail as { message?: string }).message;
    if (typeof m === "string") return m;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errBody = data as { detail?: unknown };
    const msg = formatApiErrorDetail(errBody.detail ?? data);
    throw new Error(msg || `API request failed: ${response.status}`);
  }
  return data as T;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientCandleError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if ([429, 500, 502, 503, 504].includes(err.status)) return true;
  return [
    "rate_limited",
    "timeout",
    "upstream_fetch_failed",
    "unknown_upstream_error",
  ].includes((err.reason || "").toLowerCase());
}

/** Build query string for GET /api/analysis/{symbol} (timeframe + optional debug overrides). */
export function buildAnalysisQueryString(
  timeframe: string,
  params?: Record<string, string | number | boolean>,
): string {
  const u = new URLSearchParams();
  u.set("timeframe", timeframe);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null) continue;
      u.set(k, String(v));
    }
  }
  return u.toString();
}

export function analysisDevParamsToQueryRecord(
  p: AnalysisDevParams,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  const d = DEFAULT_ANALYSIS_DEV_PARAMS;
  if (p.use_parent_relative_filter !== d.use_parent_relative_filter) {
    out.use_parent_relative_filter = p.use_parent_relative_filter;
  }
  if (p.min_impulse_parent_ratio !== d.min_impulse_parent_ratio) {
    out.min_impulse_parent_ratio = p.min_impulse_parent_ratio;
  }
  if (p.use_momentum_filter !== d.use_momentum_filter) {
    out.use_momentum_filter = p.use_momentum_filter;
  }
  if (p.min_momentum_ratio !== d.min_momentum_ratio) {
    out.min_momentum_ratio = p.min_momentum_ratio;
  }
  if (p.use_dominance_filter !== d.use_dominance_filter) {
    out.use_dominance_filter = p.use_dominance_filter;
  }
  if (p.min_dominance_ratio !== d.min_dominance_ratio) {
    out.min_dominance_ratio = p.min_dominance_ratio;
  }
  if (p.min_swing_candles != null) {
    out.min_swing_candles = p.min_swing_candles;
  }
  if (p.trend_confirmation_pct != null) {
    out.trend_confirmation_pct = p.trend_confirmation_pct;
  }
  if (p.max_walk_depth != null) {
    out.max_walk_depth = p.max_walk_depth;
  }
  if (p.rmt_use_parent_relative_filter != null) {
    out.rmt_use_parent_relative_filter = p.rmt_use_parent_relative_filter;
  }
  if (p.rmt_min_impulse_parent_ratio != null) {
    out.rmt_min_impulse_parent_ratio = p.rmt_min_impulse_parent_ratio;
  }
  if (p.rmt_use_momentum_filter != null) {
    out.rmt_use_momentum_filter = p.rmt_use_momentum_filter;
  }
  if (p.rmt_min_momentum_ratio != null) {
    out.rmt_min_momentum_ratio = p.rmt_min_momentum_ratio;
  }
  if (p.rmt_use_dominance_filter != null) {
    out.rmt_use_dominance_filter = p.rmt_use_dominance_filter;
  }
  if (p.rmt_min_dominance_ratio != null) {
    out.rmt_min_dominance_ratio = p.rmt_min_dominance_ratio;
  }
  return out;
}

export const api = {
  getHealth: () => request<HealthResponse>("/api/system/health"),
  /** Health (scan line) + ranking-status (universe ranking + global / prime / walker job flags). */
  getAnalysisProgress: () =>
    Promise.all([
      request<HealthResponse>("/api/system/health"),
      request<UniverseRankingStatus>("/api/scanner/ranking-status"),
    ]).then(([health, ranking]) => ({ health, ranking })),
  getExecutionStatus: () => request<ExecutionStatusResponse>("/api/execution/status"),
  getExecutionOrders: (limit = 50) =>
    request<ExecutionOrderListResponse>(
      `/api/execution/orders?limit=${encodeURIComponent(String(limit))}`,
    ),
  getExecutionOrderEvents: (orderId: number) =>
    request<ExecutionOrderEventsResponse>(`/api/execution/orders/${orderId}/events`),
  postExecutionOrder: (body: NormalizedOrderIntent) =>
    postJson<OrderSubmissionResponse>("/api/execution/orders", body),
  postExecutionFromSignal: (body: FromSignalRequest) =>
    postJson<OrderSubmissionResponse>("/api/execution/from-signal", body),
  getSetups: () => request<Setup[]>("/api/setups", { next: { revalidate: 120 } }),
  getSetupsAll: () => request<Setup[]>("/api/setups", { next: { revalidate: 120 } }),
  getSetupsUniverse: () => request<Setup[]>("/api/setups/universe", { next: { revalidate: 120 } }),
  getSetup: (symbol: string) =>
    request<Setup>(`/api/setups/${encodeURIComponent(symbol)}`, { next: { revalidate: 120 } }),
  deleteSetup: (symbol: string) =>
    request<{ deleted: boolean; symbol: string }>(`/api/setups/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  getActiveList: () => request<ActiveListResponse>("/api/setups/active-list"),
  addActiveSymbol: (symbol: string) =>
    request<ActiveListMutationResponse>(`/api/setups/active-list/${encodeURIComponent(symbol)}`, {
      method: "POST",
    }),
  removeActiveSymbol: (symbol: string) =>
    request<ActiveListMutationResponse>(`/api/setups/active-list/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  getUniverseStats: () =>
    request<UniverseStats>("/api/universe/stats"),
  getScanStatus: () =>
    request<{ in_progress: boolean; stage: string | null; stage1_complete: number; stage2_complete: number; stage2_total: number }>("/api/system/scan-status"),
  getScanJobLog: () => request<ScanJobLog[]>("/api/scanner/job-log"),
  triggerUniverseRanking: () =>
    postJson<{ status: string }>("/api/scanner/rank-universe", {}),
  getUniverseRankingStatus: () =>
    request<UniverseRankingStatus>("/api/scanner/ranking-status"),
  getUniverses: () =>
    request<UniverseSettings[]>("/api/universes"),
  updateUniverse: (
    universe_name: string,
    settings: Partial<UniverseSettings>,
  ) =>
    request<{ status: string }>(
      `/api/universes/${encodeURIComponent(universe_name)}`,
      {
        method: "PATCH",
        body: JSON.stringify(settings),
        headers: { "Content-Type": "application/json" },
      },
    ),
  rankUniverseSpecific: (universe_name: string) =>
    request<{ status: string }>(
      `/api/scanner/rank-universe/${encodeURIComponent(universe_name)}`,
      { method: "POST" },
    ),
  getCandles: async (symbol: string, timeframe: string) => {
    const path = `/api/candles/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}`;
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        return await request<CandleBar[]>(path, { next: { revalidate: 120 } });
      } catch (error) {
        if (attempt === maxAttempts || !isTransientCandleError(error)) {
          throw error;
        }
        await sleep(300 * attempt);
      }
    }
    return [];
  },
  /** Fetch at most `limit` most-recent candles. Pass 0 for all candles. */
  getCandlesLimited: (
    symbol: string,
    timeframe: string,
    limit: number,
  ) => {
    const params = new URLSearchParams({
      timeframe,
      limit: String(limit),
    });
    return request<CandleBar[]>(
      `/api/candles/${encodeURIComponent(symbol)}?${params.toString()}`,
    );
  },
  /** Lightweight metadata probe — candle count + earliest/latest timestamp. */
  getCandlesInfo: (
    symbol: string,
    timeframe: string,
  ) =>
    request<{
      count: number;
      earliest: string | null;
      latest: string | null;
    }>(
      `/api/candles/${encodeURIComponent(symbol)}/info?timeframe=${encodeURIComponent(timeframe)}`,
    ),
  getScanSettings: () => request<ScanSettings>("/api/setups/scan-settings"),
  saveScanSettings: (payload: ScanSettings) =>
    request<ScanSettings>("/api/setups/scan-settings", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getScanSettingsHistory: (limit = 20) =>
    request<ScanSettingsHistoryRow[]>(
      `/api/setups/scan-settings/history?limit=${encodeURIComponent(String(limit))}`,
    ),
  scanSetups: (payload: {
    symbols?: string[];
    timeframe?: string;
    settings_override?: ScanSettings;
  }) =>
    request<ScanStartResponse>("/api/setups/scan", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSetupsSummary: () => request<SetupSummary[]>("/api/setups/summary"),
  getAnalysis: (
    symbol: string,
    timeframe: string,
    params?: Record<string, string | number | boolean>,
  ) =>
    request<AnalysisResponse>(
      `/api/analysis/${encodeURIComponent(symbol)}?${buildAnalysisQueryString(timeframe, params)}`,
    ),
  getSymbolParams: (symbol: string) =>
    request<SymbolParamsResponse>(`/api/symbol-params/${encodeURIComponent(symbol)}`),
  saveSymbolParams: (symbol: string, params: Partial<AnalysisDevParams>) =>
    request<SymbolParamsResponse>(`/api/symbol-params/${encodeURIComponent(symbol)}`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  getSignalHistory: (symbol: string, timeframe?: string, limit = 50) =>
    request<SignalHistoryResponse>(
      `/api/analysis/${encodeURIComponent(symbol)}/signals?limit=${encodeURIComponent(String(limit))}${
        timeframe ? `&timeframe=${encodeURIComponent(timeframe)}` : ""
      }`,
    ),
  postOverride: (payload: {
    symbol: string;
    zone_type: string;
    price_high: number;
    price_low: number;
  }) =>
    request<AlertZone>("/api/overrides", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getOverrides: () => request<AlertZone[]>("/api/overrides"),
  getManualStructureOverrides: (symbol: string) =>
    request<ManualOverride[]>(
      `/api/manual-structure-overrides/${encodeURIComponent(symbol)}`,
    ),
  setManualStructureOverride: (
    symbol: string,
    payload: Pick<ManualOverride, "override_type"> &
      Partial<
        Omit<ManualOverride, "id" | "symbol" | "override_type" | "is_active" | "created_at" | "updated_at" | "reset_at">
      >,
  ) =>
    request<{ status: string; override: ManualOverride; recompute_triggered: boolean }>(
      `/api/manual-structure-overrides/${encodeURIComponent(symbol)}`,
      {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      },
    ),
  resetManualStructureOverride: (symbol: string, override_type: string) =>
    request<{ status: string; symbol: string; override_type: string; rows_deactivated: number; recompute_triggered: boolean }>(
      `/api/manual-structure-overrides/${encodeURIComponent(symbol)}/${encodeURIComponent(override_type)}`,
      { method: "DELETE" },
    ),
  resetAllManualStructureOverrides: (symbol: string) =>
    request<{ status: string; symbol: string; rows_deactivated: number; recompute_triggered: boolean }>(
      `/api/manual-structure-overrides/${encodeURIComponent(symbol)}`,
      { method: "DELETE" },
    ),
  recomputeManualStructureOverrides: (symbol: string, layers?: ManualRecomputeLayer[]) =>
    request<{ status: string; symbol: string; layers: ManualRecomputeLayer[]; recompute_triggered: boolean }>(
      `/api/manual-structure-overrides/${encodeURIComponent(symbol)}/recompute`,
      {
        method: "POST",
        body: JSON.stringify({ layers }),
        headers: { "Content-Type": "application/json" },
      },
    ),
  toggleKillswitch: () =>
    request<KillswitchResponse>("/api/system/killswitch", {
      method: "POST",
    }),
  getIntegrationsStatus: () =>
    request<IntegrationsStatusResponse>("/api/integrations/status"),
  testBinanceConnection: (payload: BrokerConnectionTestRequest) =>
    request<BrokerConnectionTestResponse>("/api/integrations/binance/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  testDerivConnection: (payload: BrokerConnectionTestRequest) =>
    request<BrokerConnectionTestResponse>("/api/integrations/deriv/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  testFtmoConnection: (payload: BrokerConnectionTestRequest) =>
    request<BrokerConnectionTestResponse>("/api/integrations/ftmo/test", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getFundamentalEvents: (symbol: string) =>
    request<FundamentalEventsResponse>(
      `/api/fundamentals/events/${encodeURIComponent(symbol)}`,
    ),
  getFundamentalNews: (symbol: string) =>
    request<FundamentalNewsResponse>(
      `/api/fundamentals/news/${encodeURIComponent(symbol)}`,
    ),
  getSetupStateHistory: (symbol: string, limit = 20) =>
    request<import("@/lib/types").MarketStateHistoryItem[]>(
      `/api/setups/${encodeURIComponent(symbol)}/state-history?limit=${limit}`,
    ),
  getPaperAccounts: () => request<PaperAccount[]>("/api/execution/paper/accounts"),
  getPaperTrades: (params?: {
    account_id?: number;
    symbol?: string;
    status?: string;
    limit?: number;
  }) => {
    const qs = params
      ? "?" +
        new URLSearchParams(
          Object.fromEntries(
            Object.entries(params)
              .filter(([, v]) => v !== undefined)
              .map(([k, v]) => [k, String(v)]),
          ),
        ).toString()
      : "";
    return request<PaperTrade[]>(`/api/execution/paper/trades${qs}`);
  },
  getPaperPerformance: (account_id?: number, universe?: string) => {
    const params = new URLSearchParams();
    if (account_id !== undefined) params.set("account_id", String(account_id));
    if (universe) params.set("universe", universe);
    const qs = params.toString();
    return request<PaperPerformance>(
      `/api/execution/paper/performance${qs ? "?" + qs : ""}`,
    );
  },
  closePaperTrade: (trade_id: number) =>
    request<{ status: string; pnl_usd: number; trade_id?: number; close_price?: number }>(
      `/api/execution/paper/trades/${trade_id}/close`,
      { method: "POST" },
    ),
  runPaperEngine: () =>
    request<{ monitor: object; new_trades_opened: number }>("/api/execution/paper/engine/run", {
      method: "POST",
    }),
  updatePaperAccountSettings: (account_id: number, settings: Partial<PaperAccount>) =>
    request<{ status: string }>(`/api/execution/paper/accounts/${account_id}/settings`, {
      method: "PATCH",
      body: JSON.stringify(settings),
      headers: { "Content-Type": "application/json" },
    }),
  getAccountTargets: (account_id: number) =>
    request<AccountTargets>(
      `/api/execution/paper/accounts/${account_id}/targets`,
    ),
  updateAccountTargets: (account_id: number, targets: AccountTargets) =>
    request<{ status: string; targets: AccountTargets }>(
      `/api/execution/paper/accounts/${account_id}/targets`,
      {
        method: "PATCH",
        body: JSON.stringify(targets),
        headers: { "Content-Type": "application/json" },
      },
    ),
};