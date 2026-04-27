"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryProvider } from "@/components/query-provider";
import { api } from "@/lib/api";
import type { KillswitchResponse, Setup } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getKillswitch(): Promise<KillswitchResponse> {
  const response = await fetch(`${API_URL}/api/system/killswitch`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return (await response.json()) as KillswitchResponse;
}

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

function inferCategory(symbol: string): string {
  return symbol.toUpperCase().endsWith("USDT") ? "crypto" : "synthetic";
}

function inferBroker(symbol: string): string {
  return symbol.toUpperCase().endsWith("USDT") ? "BINANCE" : "DERIV";
}

function formatTrend(value: string | undefined): "UP" | "DOWN" {
  return String(value || "").toLowerCase().includes("down") ? "DOWN" : "UP";
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

function isOlderThanOneHour(value: string | null): boolean {
  if (!value) return false;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return false;
  return Date.now() - ts > 60 * 60 * 1000;
}

function waitingForText(setup: Setup): string {
  const raw = String(setup.waiting_for ?? setup.structural_state_json?.waiting_for ?? "").trim();
  return raw.length > 0 ? raw : "-";
}

function waitingForPreview(text: string): string {
  return text.length > 40 ? `${text.slice(0, 40)}...` : text;
}

function fsmStateBadge(state: string): { cls: string; text: string } {
  if (state === "MONITORING") {
    return {
      cls: "bg-[#F5A623]/10 border-[#F5A623]/30 text-[#F5A623] font-bold",
      text: "MONITORING",
    };
  }
  if (state === "SCANNING") {
    return {
      cls: "bg-[var(--border-subtle)] border-border-default text-text-dim",
      text: "SCANNING",
    };
  }
  return {
    cls: "bg-[var(--border-default)] border-border-default text-text-primary",
    text: state,
  };
}

function WatchtowerContent() {
  const queryClient = useQueryClient();
  const [droppingSymbol, setDroppingSymbol] = useState<string | null>(null);

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

  const killswitchQuery = useQuery({
    queryKey: ["killswitch"],
    queryFn: getKillswitch,
    refetchInterval: 30_000,
  });

  const toggleKillswitchMutation = useMutation({
    mutationFn: api.toggleKillswitch,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["killswitch"] });
    },
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

  const rows = [...(setupsQuery.data ?? [])].sort((a, b) => a.symbol.localeCompare(b.symbol));
  const active = healthQuery.data?.active_setups ?? rows.length;
  const max = healthQuery.data?.max_capacity ?? 50;
  const capacityRatio = max > 0 ? Math.min(1, Math.max(0, active / max)) : 0;
  const capacityWarn = capacityRatio > 0.8;
  const killswitchActive = Boolean(killswitchQuery.data?.killswitch_active);
  const hasError = setupsQuery.isError || healthQuery.isError || killswitchQuery.isError;

  return (
    <div
      className="flex-1 overflow-auto px-4 pb-4 pt-3 bg-background-surface"
      style={{ fontFamily: '"IBM Plex Mono", monospace' }}
    >
      <div className="mb-3 flex items-end justify-between border-b border-border-default pb-2">
        <div>
          <h1 className="text-sm font-bold uppercase tracking-[0.16em] text-text-primary">WATCHTOWER</h1>
          <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-text-dim">
            FSM SURVEILLANCE MATRIX
          </p>
        </div>
        <div className="text-[10px] uppercase tracking-[0.12em] text-text-dim">rows: {rows.length}</div>
      </div>

      <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-3 border border-border-default bg-background-elevated px-3 py-2">
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-text-dim">
            CAPACITY {active}/{max}
          </div>
          <div className="h-[2px] w-full rounded-[1px] bg-[var(--border-subtle)]">
            <div
              className="h-full rounded-[1px]"
              style={{
                width: `${capacityRatio * 100}%`,
                backgroundColor: capacityWarn ? "#F23645" : "#F5A623",
              }}
            />
          </div>
        </div>

        <div />

        <div className="flex items-center justify-end gap-2">
          {killswitchActive ? (
            <span className="border border-[#F23645]/40 bg-[#F23645]/15 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-[#F23645]">
              KILLSWITCH ACTIVE
            </span>
          ) : (
            <>
              <span className="border border-border-default bg-[var(--border-default)] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-text-dim">
                KILLSWITCH OFF
              </span>
              <button
                type="button"
                onClick={() => toggleKillswitchMutation.mutate()}
                disabled={toggleKillswitchMutation.isPending}
                className="border border-border-default bg-background-elevated px-2 py-1 text-[10px] font-bold uppercase tracking-[0.08em] text-text-primary transition-colors hover:bg-[var(--border-default)] disabled:opacity-50"
              >
                TOGGLE
              </button>
            </>
          )}
        </div>
      </div>

      <div className="overflow-auto border border-border-default bg-background-elevated">
        <table className="w-full border-collapse whitespace-nowrap text-left text-[12px]">
          <thead className="sticky top-0 z-10 bg-background-elevated">
            <tr>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">SYMBOL</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">BROKER</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">TIMEFRAME</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">TREND</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">FSM STATE</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">WAITING FOR</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">SCORE</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">LAST CHECKED</th>
              <th className="border-b border-border-default px-3 py-2 text-[9px] font-normal uppercase tracking-[0.14em] text-text-dim">DROP</th>
            </tr>
          </thead>
          <tbody>
            {setupsQuery.isLoading && (
              <>
                {Array.from({ length: 3 }).map((_, idx) => (
                  <tr key={idx} className="border-b border-border-default/50">
                    <td className="px-3 py-3" colSpan={9}>
                      <div className="flex animate-pulse items-center gap-3">
                        <div className="h-2 w-24 bg-[var(--border-default)]" />
                        <div className="h-2 w-20 bg-[var(--border-default)]" />
                        <div className="h-2 w-16 bg-[var(--border-default)]" />
                        <div className="h-2 w-20 bg-[var(--border-default)]" />
                        <div className="h-2 w-24 bg-[var(--border-default)]" />
                        <div className="h-2 w-40 bg-[var(--border-default)]" />
                      </div>
                    </td>
                  </tr>
                ))}
              </>
            )}

            {!setupsQuery.isLoading && hasError && (
              <tr>
                <td className="px-3 py-3 text-[#F23645]" colSpan={9}>
                  [SYSTEM]: CONNECTION LOST
                </td>
              </tr>
            )}

            {!setupsQuery.isLoading && !hasError && rows.length === 0 && (
              <tr>
                <td className="px-3 py-3 text-text-dim" colSpan={9}>
                  No setups available.
                </td>
              </tr>
            )}

            {!setupsQuery.isLoading &&
              !hasError &&
              rows.map((setup) => {
                const trend = formatTrend(setup.trend ?? setup.htf_trend_direction);
                const fsm = fsmStateBadge(setup.fsm_state ?? setup.status ?? "UNKNOWN");
                const waiting = waitingForText(setup);
                const waitingPreview = waitingForPreview(waiting);
                const stale = isOlderThanOneHour(setup.last_checked_at);
                const isDropping = droppingSymbol === setup.symbol && dropMutation.isPending;

                return (
                  <tr
                    key={setup.id ?? setup.setup_id}
                    className="border-b border-border-default/50 transition-colors hover:bg-[var(--border-default)]/30"
                  >
                    <td className="px-3 py-2">
                      <div className="text-[12px] font-bold text-text-primary">{setup.symbol}</div>
                      <div className="mt-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                        {inferCategory(setup.symbol)}
                      </div>
                    </td>

                    <td className="px-3 py-2">
                      <span className="border border-border-default bg-[var(--border-default)] px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                        {inferBroker(setup.symbol)}
                      </span>
                    </td>

                    <td className="px-3 py-2 text-[11px] uppercase text-text-dim">{setup.timeframe ?? setup.htf_timeframe ?? "-"}</td>

                    <td
                      className="px-3 py-2 text-[11px] font-bold uppercase"
                      style={{ color: trend === "UP" ? "#089981" : "#F23645" }}
                    >
                      {trend}
                    </td>

                    <td className="px-3 py-2">
                      <span
                        className={`border px-2 py-0.5 text-xs uppercase tracking-[0.08em] ${fsm.cls}`}
                      >
                        {fsm.text}
                      </span>
                    </td>

                    <td className="max-w-[280px] px-3 py-2 text-[11px] text-text-dim" title={waiting}>
                      {waitingPreview}
                    </td>

                    <td className="px-3 py-2 text-[11px] font-bold text-[#F5A623]">
                      {(setup.trend_score * 100).toFixed(1)}
                    </td>

                    <td className="px-3 py-2 text-[11px]" style={{ color: stale ? "#F23645" : "var(--text-dim)" }}>
                      {formatRelativeTime(setup.last_checked_at)}
                    </td>

                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          setDroppingSymbol(setup.symbol);
                          dropMutation.mutate(setup.symbol, {
                            onSettled: () => setDroppingSymbol(null),
                          });
                        }}
                        disabled={isDropping}
                        className="border border-border-default bg-[var(--border-default)] px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim transition-colors hover:bg-[#F23645] hover:text-white disabled:opacity-50"
                      >
                        {isDropping ? "..." : "DROP"}
                      </button>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function WatchtowerPage() {
  return (
    <QueryProvider>
      <WatchtowerContent />
    </QueryProvider>
  );
}