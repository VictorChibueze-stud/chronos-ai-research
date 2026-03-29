import type {
  AnalysisResponse,
  AlertZone,
  CandleBar,
  HealthResponse,
  KillswitchResponse,
  Setup,
  SetupSummary,
  UniverseStats,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export const api = {
  getHealth: () => request<HealthResponse>("/api/system/health"),
  getSetups: () => request<Setup[]>("/api/setups"),
  getSetupsAll: () => request<Setup[]>("/api/setups"),
  getSetup: (symbol: string) =>
    request<Setup>(`/api/setups/${encodeURIComponent(symbol)}`),
  getUniverseStats: () =>
    request<UniverseStats>("/api/universe/stats"),
  getScanStatus: () =>
    request<{ in_progress: boolean; stage: string | null; stage1_complete: number; stage2_complete: number; stage2_total: number }>("/api/system/scan-status"),
  getCandles: (symbol: string, timeframe: string, limit = 200) =>
    request<CandleBar[]>(
      `/api/candles/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`,
    ),
  scanSetups: (payload: { symbols?: string[]; timeframe?: string }) =>
    request<Setup[]>("/api/setups/scan", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSetupsSummary: () => request<SetupSummary[]>("/api/setups/summary"),
  getAnalysis: (symbol: string, timeframe: string) =>
    request<AnalysisResponse>(
      `/api/analysis/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}`,
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
  toggleKillswitch: () =>
    request<KillswitchResponse>("/api/system/killswitch", {
      method: "POST",
    }),
};