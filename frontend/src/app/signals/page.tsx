"use client";

import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";

import { QueryProvider } from "@/components/query-provider";
import { LiveStatusMeta, LiveStatusRow } from "@/components/ui/live-status";
import { Tooltip } from "@/components/ui/tooltip";
import { formatLocaleInt, formatScore } from "@/lib/format-display";
import { api } from "@/lib/api";
import {
  computeMetCount,
  computePipelineFlags,
  depthBadgeColor,
  depthBadgeLabel,
  normalizeAssetClassForFilter,
  normalizeTrend,
  selectTop50Setups,
  type FilterAssetClass,
  type ReadinessFilter,
} from "@/lib/signal-readiness";
import type { Setup } from "@/lib/types";

type SignalRow = Setup & {
  asset_bucket: ReturnType<typeof normalizeAssetClassForFilter>;
  trend: Setup["trend"];
  timeframe: string;
  waiting_for_display: string;
  waiting_for_raw: string;
};

function normalizeSignalRows(setups: Setup[]): SignalRow[] {
  return setups.map((setup) => {
    const waiting_for_raw = String(setup.waiting_for ?? setup.structural_state_json?.waiting_for ?? "").trim();
    return {
      ...setup,
      asset_bucket: normalizeAssetClassForFilter(setup.category),
      trend: normalizeTrend(setup.trend ?? setup.htf_trend_direction),
      timeframe: setup.timeframe ?? setup.htf_timeframe ?? "1h",
      waiting_for_display: waiting_for_raw || "-",
      waiting_for_raw,
    };
  });
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

function pillStyle(active: boolean): CSSProperties {
  return {
    padding: "4px 10px",
    fontSize: 9,
    letterSpacing: "0.08em",
    fontFamily: "'IBM Plex Mono', monospace",
    border: active ? "1px solid #F5A623" : "1px solid #1C1E24",
    borderRadius: 2,
    background: active ? "#F5A623" : "transparent",
    color: active ? "#0D0F14" : "#787B86",
    cursor: "pointer",
  };
}

function SummaryMetric({ label, value, color, borderRight = true }: { label: string; value: number; color?: string; borderRight?: boolean }) {
  return (
    <div
      style={{
        flex: 1,
        padding: "12px 0",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        borderRight: borderRight ? "1px solid var(--border-subtle)" : undefined,
      }}
    >
      <div
        style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 28,
          fontWeight: 700,
          color: color ?? "var(--text-primary)",
          lineHeight: 1,
        }}
      >
        {formatLocaleInt(value)}
      </div>
      <div
        style={{
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 9,
          letterSpacing: "0.14em",
          color: "#787B86",
          marginTop: 6,
          textAlign: "center",
        }}
      >
        {label}
      </div>
    </div>
  );
}

const PIPELINE_STEPS = [
  { id: "trend" as const, label: "TREND" },
  { id: "retracement" as const, label: "RETRACEMENT" },
  { id: "depth" as const, label: "DEPTH" },
  { id: "choch" as const, label: "CHOCH" },
  { id: "candidate" as const, label: "CANDIDATE" },
];

function PipelineStrip({ row, flags }: { row: SignalRow; flags: ReturnType<typeof computePipelineFlags> }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, marginTop: 10, width: "100%" }}>
      {PIPELINE_STEPS.map((step, i) => {
        const met = flags[step.id];
        return (
          <Fragment key={step.id}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3, flex: "1 1 0", minWidth: 0 }}>
              <div
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: 9999,
                  background: met ? "#F5A623" : "#2A2E39",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {met ? <Check size={8} strokeWidth={3} color="#0D0F14" aria-hidden /> : null}
              </div>
              {step.id === "depth" ? (
                <span
                  style={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 7,
                    fontWeight: 700,
                    color: depthBadgeColor(row.pullback_depth),
                    letterSpacing: "0.04em",
                  }}
                >
                  {depthBadgeLabel(row.pullback_depth)}
                </span>
              ) : null}
              <span
                style={{
                  fontFamily: "'IBM Plex Mono', monospace",
                  fontSize: 8,
                  letterSpacing: "0.06em",
                  color: met ? "#787B86" : "#4A4D58",
                  textAlign: "center",
                  lineHeight: 1.1,
                }}
              >
                {step.label}
              </span>
            </div>
            {i < PIPELINE_STEPS.length - 1 ? (
              <span style={{ color: "#4A4D58", fontSize: 10, marginTop: 1, flexShrink: 0, lineHeight: "12px" }}>
                →
              </span>
            ) : null}
          </Fragment>
        );
      })}
    </div>
  );
}

function CardSkeletonGrid() {
  const placeholders = Array.from({ length: 9 }, (_, i) => i);
  return (
    <div
      className="signal-board-grid"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: 12,
      }}
    >
      {placeholders.map((i) => (
        <div
          key={i}
          style={{
            height: 148,
            borderRadius: 2,
            background: "#0E1014",
            border: "1px solid #1E222D",
            animation: "pulse 1.2s ease-in-out infinite",
          }}
        />
      ))}
    </div>
  );
}

function SignalBoardContent() {
  const router = useRouter();
  const [trendFilter, setTrendFilter] = useState<"ALL" | "LONG" | "SHORT">("ALL");
  const [assetClassFilter, setAssetClassFilter] = useState<FilterAssetClass | "ALL">("ALL");
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>("ALL");

  const setupsQuery = useQuery({
    queryKey: ["setups"],
    queryFn: api.getSetups,
    refetchInterval: 30_000,
  });

  const { top50Rows, summary, filteredRows } = useMemo(() => {
    const raw = setupsQuery.data ?? [];
    const top50 = selectTop50Setups(raw);
    const rows = normalizeSignalRows(top50);

    let full = 0;
    let partial = 0;
    let waiting = 0;
    const enriched = rows.map((row) => {
      const flags = computePipelineFlags({
        trend: row.trend,
        current_phase: row.current_phase,
        pullback_depth: row.pullback_depth,
        waiting_for_raw: row.waiting_for_raw,
        ema_signal: row.ema_signal ?? null,
      });
      const met = computeMetCount(flags);
      if (met === 5) full += 1;
      else if (met >= 3) partial += 1;
      else waiting += 1;
      return { row, flags, met };
    });

    const filtered = enriched.filter(({ row, met }) => {
      if (trendFilter === "LONG" && row.trend !== "up") return false;
      if (trendFilter === "SHORT" && row.trend !== "down") return false;
      if (assetClassFilter !== "ALL") {
        if (row.asset_bucket === null || row.asset_bucket === "INDICES") return false;
        if (row.asset_bucket !== assetClassFilter) return false;
      }
      if (readinessFilter === "FULL" && met !== 5) return false;
      if (readinessFilter === "PARTIAL" && (met < 3 || met > 4)) return false;
      if (readinessFilter === "EARLY" && (met < 1 || met > 2)) return false;
      return true;
    });

    return {
      top50Rows: enriched,
      summary: { full, partial, waiting },
      filteredRows: filtered,
    };
  }, [setupsQuery.data, trendFilter, assetClassFilter, readinessFilter]);

  const hasError = setupsQuery.isError;
  const freshnessLabel = formatFreshness(setupsQuery.dataUpdatedAt);

  const ASSET_PILLS: (FilterAssetClass | "ALL")[] = ["ALL", "CRYPTO", "FOREX", "SYNTHETIC", "COMMODITY"];

  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: "20px",
        background: "#0D0F14",
        fontFamily: "'IBM Plex Mono', monospace",
        display: "flex",
        flexDirection: "column",
        gap: 0,
      }}
    >
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 0.45; } 50% { opacity: 0.85; } }
        @media (max-width: 1200px) {
          .signal-board-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 640px) {
          .signal-board-grid { grid-template-columns: minmax(0, 1fr) !important; }
        }
        .signal-readiness-card:hover { border-color: #363A45 !important; }
      `}</style>

      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          borderBottom: "1px solid var(--border-default)",
          paddingBottom: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: "0.18em", color: "var(--text-primary)" }}>
            SIGNAL BOARD
          </h1>
          <p style={{ margin: "8px 0 0", fontSize: 10, letterSpacing: "0.1em", color: "#787B86", fontWeight: 500 }}>
            TOP 50 BY RANK WHEN PRESENT, ELSE BY SCORE — STRATEGY READINESS
          </p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, textAlign: "right" }}>
          <LiveStatusRow
            variant={hasError ? "idle" : "live"}
            showSecondaryBusyDot={setupsQuery.isFetching}
            label="FEED"
            rightSlot={<LiveStatusMeta>{freshnessLabel}</LiveStatusMeta>}
          />
          <LiveStatusMeta dim>
            SHOWING {filteredRows.length} / {top50Rows.length}
          </LiveStatusMeta>
        </div>
      </div>

      <div style={{ display: "flex", padding: "16px 0", borderBottom: "1px solid var(--border-default)", marginBottom: 16 }}>
        <SummaryMetric label="ALL GREEN (5/5)" value={summary.full} color="#26A69A" />
        <SummaryMetric label="PARTIALLY READY (3–4)" value={summary.partial} color="#F5A623" />
        <SummaryMetric label="WAITING (&lt;3)" value={summary.waiting} borderRight={false} />
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          paddingBottom: 14,
          borderBottom: "1px solid var(--border-default)",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.12em", minWidth: 56 }}>TREND</span>
          {(["ALL", "LONG", "SHORT"] as const).map((key) => (
            <Tooltip key={key} content={key === "ALL" ? "All trends" : key === "LONG" ? "Uptrend only" : "Downtrend only"}>
              <button type="button" onClick={() => setTrendFilter(key)} style={pillStyle(trendFilter === key)}>
                {key === "LONG" ? "↑ LONG" : key === "SHORT" ? "↓ SHORT" : "ALL"}
              </button>
            </Tooltip>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.12em", minWidth: 56 }}>ASSET</span>
          {ASSET_PILLS.map((key) => (
            <Tooltip
              key={key}
              content={key === "ALL" ? "Includes indices and unclassified" : `Filter ${key}`}
            >
              <button type="button" onClick={() => setAssetClassFilter(key)} style={pillStyle(assetClassFilter === key)}>
                {key}
              </button>
            </Tooltip>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.12em", minWidth: 56 }}>READINESS</span>
          {(["ALL", "FULL", "PARTIAL", "EARLY"] as const).map((key) => (
            <Tooltip key={key} content={`Readiness: ${key}`}>
              <button type="button" onClick={() => setReadinessFilter(key)} style={pillStyle(readinessFilter === key)}>
                {key}
              </button>
            </Tooltip>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 200 }}>
        {setupsQuery.isLoading ? (
          <CardSkeletonGrid />
        ) : hasError ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 220, color: "var(--bear)", fontSize: 11 }}>
            [SYSTEM]: CONNECTION LOST
          </div>
        ) : filteredRows.length === 0 ? (
          <div style={{ padding: 24, color: "#787B86", fontSize: 11, textAlign: "center" }}>
            No setups match these filters in the current top 50.
          </div>
        ) : (
          <div
            className="signal-board-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              gap: 12,
            }}
          >
            {filteredRows.map(({ row, flags }) => {
              const marketHref = `/market?symbol=${encodeURIComponent(row.symbol)}&timeframe=${encodeURIComponent(row.timeframe)}`;
              const assetLabel = row.asset_bucket === "INDICES" ? "INDICES" : row.asset_bucket ?? "—";
              const wf = row.waiting_for_display.length > 40 ? `${row.waiting_for_display.slice(0, 40)}…` : row.waiting_for_display;

              return (
                <button
                  key={row.id ?? row.setup_id ?? row.symbol}
                  type="button"
                  onClick={() => router.push(marketHref)}
                  style={{
                    textAlign: "left",
                    background: "#0E1014",
                    border: "1px solid #1E222D",
                    borderRadius: 2,
                    padding: "12px 14px",
                    cursor: "pointer",
                    transition: "border-color 0.12s ease",
                  }}
                  className="signal-readiness-card"
                >
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
                      <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{row.symbol}</span>
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: row.trend === "up" ? "#26A69A" : row.trend === "down" ? "#EF5350" : "#787B86",
                        }}
                      >
                        {row.trend === "up" ? "▲" : row.trend === "down" ? "▼" : "—"}
                      </span>
                      <span
                        style={{
                          fontSize: 8,
                          letterSpacing: "0.1em",
                          color: "#787B86",
                          border: "1px solid #1E222D",
                          padding: "2px 6px",
                          borderRadius: 2,
                        }}
                      >
                        {assetLabel}
                      </span>
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#F5A623", flexShrink: 0 }}>
                      {formatScore(row.trend_score)}
                    </span>
                  </div>
                  <PipelineStrip row={row} flags={flags} />
                  <div
                    style={{
                      marginTop: 10,
                      fontSize: 10,
                      color: "#4A4D58",
                      lineHeight: 1.35,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={row.waiting_for_display}
                  >
                    {wf}
                  </div>
                </button>
              );
            })}
          </div>
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
