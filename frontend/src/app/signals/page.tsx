"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { QueryProvider } from "@/components/query-provider";
import { api } from "@/lib/api";
import type { HealthResponse, Setup } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type SignalSetup = Setup & {
  broker: string;
  timeframe: string;
  trend: Setup["trend"];
  fsm_state: string;
  waiting_for: string;
};

async function dropSetup(symbol: string): Promise<{ deleted: boolean; symbol: string }> {
  const response = await fetch(`${API_URL}/api/setups/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return (await response.json()) as { deleted: boolean; symbol: string };
}

function inferBroker(symbol: string): string {
  return symbol.toUpperCase().endsWith("USDT") ? "BINANCE" : "DERIV";
}

function normalizeTrend(value: string | undefined): Setup["trend"] {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("down")) return "down";
  if (normalized.includes("up")) return "up";
  return "range";
}

function normalizeSetups(setups: Setup[]): SignalSetup[] {
  return setups
    .map((setup) => ({
      ...setup,
      broker: setup.broker ? String(setup.broker).toUpperCase() : inferBroker(setup.symbol),
      timeframe: setup.timeframe ?? setup.htf_timeframe ?? "-",
      trend: normalizeTrend(setup.trend ?? setup.htf_trend_direction),
      fsm_state: setup.fsm_state ?? setup.status ?? "UNKNOWN",
      waiting_for: String(setup.waiting_for ?? setup.structural_state_json?.waiting_for ?? "").trim() || "-",
    }))
    .sort((a, b) => a.symbol.localeCompare(b.symbol));
}

function formatRelativeTime(value: string | null): string {
  if (!value) return "-";
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return "-";

  const diffMs = Date.now() - ts;
  if (diffMs < 0) return "just now";

  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;

  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;

  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;

  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

function isStale(value: string | null): boolean {
  if (!value) return false;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return false;
  return Date.now() - ts > 60 * 60 * 1000;
}

function formatFreshness(updatedAt: number): string {
  if (!updatedAt) return "WAITING FOR DATA";

  const diffMs = Date.now() - updatedAt;
  if (diffMs < 0) return "UPDATED JUST NOW";

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `UPDATED ${seconds}S AGO`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `UPDATED ${minutes}M AGO`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `UPDATED ${hours}H AGO`;

  const days = Math.floor(hours / 24);
  return `UPDATED ${days}D AGO`;
}

function stateBadgeStyle(state: string): React.CSSProperties {
  if (state === "MONITORING") {
    return {
      background: "rgba(245,166,35,0.10)",
      border: "1px solid rgba(245,166,35,0.30)",
      color: "var(--amber)",
      fontWeight: 700,
    };
  }
  if (state === "SCANNING") {
    return {
      background: "var(--bg-elevated)",
      border: "1px solid var(--border-subtle)",
      color: "var(--text-secondary)",
    };
  }
  return {
    background: "var(--bg-elevated)",
    border: "1px solid var(--border-subtle)",
    color: "var(--text-primary)",
  };
}

function CompactMetricBlock({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ flex: 1, padding: "12px 0", display: "flex", flexDirection: "column", alignItems: "center", borderRight: "1px solid var(--border-subtle)" }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 28, fontWeight: 700, color: color || "var(--text-primary)", lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: "0.14em", color: "var(--text-dim)", marginTop: 6 }}>
        {label}
      </div>
    </div>
  );
}

function EmaSignalBadge({ signal }: { signal: Setup["ema_signal"] }) {
  if (signal === "LONG") {
    return (
      <span style={{
        fontSize: 9,
        padding: "2px 5px",
        borderRadius: 2,
        letterSpacing: "0.06em",
        fontFamily: "'IBM Plex Mono', monospace",
        background: "rgba(76,175,125,0.1)",
        color: "#4CAF7D",
        border: "1px solid rgba(76,175,125,0.3)",
      }}>
        ▲ LONG
      </span>
    );
  }

  if (signal === "SHORT") {
    return (
      <span style={{
        fontSize: 9,
        padding: "2px 5px",
        borderRadius: 2,
        letterSpacing: "0.06em",
        fontFamily: "'IBM Plex Mono', monospace",
        background: "rgba(224,90,90,0.1)",
        color: "#E05A5A",
        border: "1px solid rgba(224,90,90,0.3)",
      }}>
        ▼ SHORT
      </span>
    );
  }

  return <span style={{ fontSize: 11, color: "#3A3D48" }}>—</span>;
}

function SignalBoardContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [droppingSymbol, setDroppingSymbol] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<"ALL" | "MONITORING" | "SCANNING">("ALL");
  const [trendFilter, setTrendFilter] = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [depthFilter, setDepthFilter] = useState<"ALL DEPTHS" | "DEPTH 1+" | "DEPTH 2+" | "DEPTH 3">("ALL DEPTHS");
  const [sortField, setSortField] = useState<"signal" | "score" | "depth" | "lastSeen">("score");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  const setupsQuery = useQuery({
    queryKey: ["setups"],
    queryFn: api.getSetups,
    refetchInterval: 30_000,
  });

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 30_000,
  });

  const dropMutation = useMutation({
    mutationFn: dropSetup,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["setups"] }),
        queryClient.invalidateQueries({ queryKey: ["health"] }),
      ]);
    },
  });

  const setups = normalizeSetups(setupsQuery.data ?? []);
  const health: HealthResponse = healthQuery.data ?? {
    status: "unknown",
    active_setups: setups.length,
    max_capacity: 0,
    last_scan: null,
    next_scan: null,
    scan_in_progress: false,
  };
  const monitoringCount = setups.filter((s) => s.fsm_state === "MONITORING").length;
  const scanningCount = setups.filter((s) => s.fsm_state === "SCANNING").length;
  const capacityRatio = health.max_capacity > 0 ? Math.min(1, Math.max(0, health.active_setups / health.max_capacity)) : 0;
  const hasError = setupsQuery.isError || healthQuery.isError;
  const freshnessLabel = formatFreshness(setupsQuery.dataUpdatedAt);

  const filteredSetups = setups
    .filter((setup) => {
      if (stateFilter === "ALL") return true;
      return setup.fsm_state === stateFilter;
    })
    .filter((setup) => {
      if (trendFilter === "ALL") return true;
      if (trendFilter === "LONG") return setup.trend === "up";
      return setup.trend === "down";
    })
    .filter((setup) => {
      if (depthFilter === "ALL DEPTHS") return true;
      if (depthFilter === "DEPTH 1+") return setup.pullback_depth >= 1;
      if (depthFilter === "DEPTH 2+") return setup.pullback_depth >= 2;
      return setup.pullback_depth >= 3;
    });

  const sortedSetups = [...filteredSetups].sort((a, b) => {
    let comparison = 0;

    if (sortField === "signal") {
      comparison = String(a.symbol).localeCompare(String(b.symbol));
    } else if (sortField === "score") {
      comparison = a.trend_score - b.trend_score;
    } else if (sortField === "depth") {
      comparison = a.pullback_depth - b.pullback_depth;
    } else {
      const aTs = new Date(a.last_checked_at || "").getTime();
      const bTs = new Date(b.last_checked_at || "").getTime();
      comparison = (Number.isFinite(aTs) ? aTs : 0) - (Number.isFinite(bTs) ? bTs : 0);
    }

    return sortDirection === "asc" ? comparison : -comparison;
  });

  function handleSort(nextField: "signal" | "score" | "depth" | "lastSeen") {
    if (sortField === nextField) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }

    setSortField(nextField);
    setSortDirection(nextField === "signal" ? "asc" : "desc");
  }

  function sortIndicator(field: "signal" | "score" | "depth" | "lastSeen") {
    if (sortField !== field) return "";
    return sortDirection === "asc" ? " ↑" : " ↓";
  }

  const filterButtonStyle = (active: boolean): React.CSSProperties => ({
    fontSize: 9,
    padding: "2px 8px",
    border: "1px solid #1E222D",
    borderRadius: 0,
    background: active ? "#F5A623" : "transparent",
    color: active ? "#0B0D11" : "#434651",
    fontFamily: "'IBM Plex Mono', monospace",
    cursor: "pointer",
    letterSpacing: "0.08em",
  });

  return (
    <div style={{
      flex: 1,
      overflow: "auto",
      padding: "20px",
      background: "var(--bg-base)",
      fontFamily: "'IBM Plex Mono', monospace",
      display: "flex",
      flexDirection: "column",
      gap: 0,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", borderBottom: "1px solid var(--border-default)", paddingBottom: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: "0.18em", color: "var(--text-primary)" }}>SIGNAL BOARD</h1>
          <p style={{ margin: "8px 0 0", fontSize: 10, letterSpacing: "0.12em", color: "var(--amber)", fontWeight: 600 }}>{monitoringCount} MARKETS IN RETRACEMENT ZONE</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, textAlign: "right" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--text-secondary)", textTransform: "uppercase" }}>{freshnessLabel}</div>
          <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--text-secondary)" }}>rows: {sortedSetups.length}</div>
        </div>
      </div>

      <div style={{ display: "flex", padding: "16px 0", borderBottom: "1px solid var(--border-default)", marginBottom: 16 }}>
        <CompactMetricBlock label="ACTIVE SIGNALS" value={setups.length} color="var(--text-primary)" />
        <CompactMetricBlock label="MONITORING" value={monitoringCount} color="var(--amber)" />
        <CompactMetricBlock label="SCANNING" value={scanningCount} />
        <CompactMetricBlock label="CAPACITY" value={`${health.active_setups}/${health.max_capacity}`} color={capacityRatio > 0.8 ? "#EF5350" : "var(--text-primary)"} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", paddingBottom: 12, borderBottom: "1px solid var(--border-default)", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 9, color: "#434651", letterSpacing: "0.1em" }}>STATE</span>
          {(["ALL", "MONITORING", "SCANNING"] as const).map((value) => (
            <button key={value} type="button" onClick={() => setStateFilter(value)} style={filterButtonStyle(stateFilter === value)}>
              {value}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 9, color: "#434651", letterSpacing: "0.1em" }}>TREND</span>
          {([
            { key: "ALL", label: "ALL" },
            { key: "LONG", label: "↑ LONG" },
            { key: "SHORT", label: "↓ SHORT" },
          ] as const).map((item) => (
            <button key={item.key} type="button" onClick={() => setTrendFilter(item.key)} style={filterButtonStyle(trendFilter === item.key)}>
              {item.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 9, color: "#434651", letterSpacing: "0.1em" }}>DEPTH</span>
          <select
            value={depthFilter}
            onChange={(event) => setDepthFilter(event.target.value as "ALL DEPTHS" | "DEPTH 1+" | "DEPTH 2+" | "DEPTH 3")}
            style={{
              fontSize: 9,
              padding: "2px 8px",
              border: "1px solid #1E222D",
              borderRadius: 0,
              background: "transparent",
              color: "#434651",
              fontFamily: "'IBM Plex Mono', monospace",
              letterSpacing: "0.08em",
              outline: "none",
            }}
          >
            {(["ALL DEPTHS", "DEPTH 1+", "DEPTH 2+", "DEPTH 3"] as const).map((option) => (
              <option key={option} value={option} style={{ background: "#131722", color: "#D1D4DC" }}>
                {option}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflow: "auto", flex: 1 }}>
        {setupsQuery.isLoading ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 220, color: "var(--text-secondary)", fontSize: 11 }}>
            [SCANNING MARKETS...]
          </div>
        ) : hasError ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 220, color: "var(--bear)", fontSize: 11 }}>
            [SYSTEM]: CONNECTION LOST
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", whiteSpace: "nowrap", textAlign: "left", fontSize: 12 }}>
            <thead style={{ position: "sticky", top: 0, zIndex: 10, background: "var(--bg-base)" }}>
              <tr>
                <th
                  onClick={() => handleSort("signal")}
                  style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left", cursor: "pointer" }}
                >
                  SIGNAL{sortIndicator("signal")}
                </th>
                {[
                  "BROKER",
                  "TF",
                  "TREND",
                  "STATE",
                  "WAITING FOR",
                ].map((header) => (
                  <th key={header} style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left" }}>
                    {header}
                  </th>
                ))}
                <th
                  onClick={() => handleSort("score")}
                  style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left", cursor: "pointer" }}
                >
                  SCORE{sortIndicator("score")}
                </th>
                <th style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left" }}>
                  EMA
                </th>
                <th
                  onClick={() => handleSort("depth")}
                  style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left", cursor: "pointer" }}
                >
                  DEPTH{sortIndicator("depth")}
                </th>
                <th
                  onClick={() => handleSort("lastSeen")}
                  style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left", cursor: "pointer" }}
                >
                  LAST SEEN{sortIndicator("lastSeen")}
                </th>
                <th style={{ borderBottom: "1px solid var(--border-subtle)", padding: "8px 10px", fontSize: 9, fontWeight: 400, letterSpacing: "0.14em", color: "var(--text-dim)", textAlign: "left" }}>
                  DROP
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedSetups.length === 0 ? (
                <tr>
                  <td colSpan={11} style={{ padding: "16px 12px", color: "#787B86" }}>
                    No setups available.
                  </td>
                </tr>
              ) : (
                sortedSetups.map((setup) => {
                  const stale = isStale(setup.last_checked_at);
                  const isMonitoring = setup.fsm_state === "MONITORING";
                  const waitingPreview = setup.waiting_for.length > 40 ? `${setup.waiting_for.slice(0, 40)}...` : setup.waiting_for;
                  const isDropping = droppingSymbol === setup.symbol && dropMutation.isPending;
                  const marketHref = `/market?symbol=${encodeURIComponent(setup.symbol)}&timeframe=${encodeURIComponent(setup.timeframe)}`;
                  const depthTone = setup.pullback_depth === 1
                    ? "#3A6BFF"
                    : setup.pullback_depth === 2
                      ? "#4CAF7D"
                      : setup.pullback_depth === 3
                        ? "#9B59B6"
                        : "#3A3D48";

                  return (
                    <tr
                      key={setup.id ?? setup.setup_id}
                      onClick={() => {
                        router.push(marketHref);
                      }}
                      style={{ borderBottom: "1px solid var(--border-subtle)", transition: "background 0.1s ease", background: isMonitoring ? "rgba(245,166,35,0.04)" : "transparent", cursor: "pointer" }}
                      className="signal-row"
                    >
                      <td style={{ padding: "8px 10px" }}>
                        <div style={{ borderLeft: isMonitoring ? "2px solid var(--amber)" : "2px solid transparent", paddingLeft: 8, fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                          ● {setup.symbol}
                        </div>
                      </td>

                      <td style={{ padding: "8px 10px", fontSize: 10, color: "var(--text-secondary)" }}>
                        <span style={{ border: "1px solid var(--border-default)", background: "var(--border-default)", padding: "2px 8px", borderRadius: 2, letterSpacing: "0.08em" }}>
                          {setup.broker}
                        </span>
                      </td>

                      <td style={{ padding: "8px 10px", fontSize: 10, textTransform: "uppercase", color: "var(--text-secondary)" }}>{setup.timeframe}</td>

                      <td style={{ padding: "8px 10px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: setup.trend === "up" ? "var(--bull)" : setup.trend === "down" ? "var(--bear)" : "var(--text-secondary)" }}>
                        {setup.trend === "up" ? "▲" : setup.trend === "down" ? "▼" : "—"}
                      </td>

                      <td style={{ padding: "8px 10px" }}>
                        <span
                          className={setup.fsm_state === "MONITORING" ? "drop-shadow-glow-amber" : undefined}
                          style={{ ...stateBadgeStyle(setup.fsm_state), display: "inline-block", padding: "1px 6px", fontSize: 9, letterSpacing: "0.08em", borderRadius: 2 }}
                        >
                          {setup.fsm_state}
                        </span>
                      </td>

                      <td style={{ maxWidth: 280, padding: "8px 10px", fontSize: 11, color: "var(--text-secondary)" }} title={setup.waiting_for}>
                        {waitingPreview}
                      </td>

                      <td style={{ padding: "8px 10px", fontSize: 12, fontWeight: 700, color: setup.trend_score > 0 ? "var(--amber)" : "var(--text-dim)" }}>
                        {setup.trend_score.toFixed(1)}
                      </td>

                      <td style={{ padding: "8px 10px" }}>
                        <EmaSignalBadge signal={setup.ema_signal} />
                      </td>

                      <td style={{ padding: "8px 10px", fontSize: 12, fontWeight: 700, color: depthTone }}>
                        {setup.pullback_depth}
                      </td>

                      <td style={{ padding: "8px 10px", fontSize: 11, color: stale ? "var(--bear)" : "var(--text-secondary)" }}>
                        {formatRelativeTime(setup.last_checked_at)}
                      </td>

                      <td style={{ padding: "8px 10px" }}>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setDroppingSymbol(setup.symbol);
                            dropMutation.mutate(setup.symbol, {
                              onSettled: () => setDroppingSymbol(null),
                            });
                          }}
                          disabled={isDropping}
                          style={{
                            border: "1px solid var(--border-default)",
                            background: "var(--border-default)",
                            padding: "2px 8px",
                            fontSize: 10,
                            letterSpacing: "0.08em",
                            color: "var(--text-secondary)",
                            cursor: isDropping ? "default" : "pointer",
                            opacity: isDropping ? 0.5 : 1,
                            borderRadius: 2,
                          }}
                        >
                          {isDropping ? "..." : "DROP"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function SignalsPage() {
  return (
    <QueryProvider>
      <SignalBoardContent />
    </QueryProvider>
  );
}