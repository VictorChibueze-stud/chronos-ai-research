"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { QueryProvider } from "@/components/query-provider";
import { api } from "@/lib/api";
import { formatScore } from "@/lib/format-display";
import type { SetupSummary } from "@/lib/types";

const CATEGORIES: SetupSummary["category"][] = ["FOREX", "CRYPTO", "COMMODITIES", "INDICES", "SYNTHETIC"];

function normalizeTrend(value: string): "up" | "down" | "other" {
  const trend = value.toLowerCase();
  if (trend === "up") return "up";
  if (trend === "down") return "down";
  return "other";
}

function accentColor(setup: SetupSummary): string {
  if (setup.fsm_state === "MONITORING") return "#F5A623";
  return normalizeTrend(setup.trend) === "down" ? "#F23645" : "#089981";
}

function StatSkeleton() {
  return <div className="skeleton-bar h-[68px] border border-[#2A2E39]" />;
}

function HeatmapSkeleton() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2">
      {Array.from({ length: 24 }).map((_, idx) => (
        <div key={idx} className="skeleton-bar h-[72px] border border-[#2A2E39]" />
      ))}
    </div>
  );
}

function RadarContent() {
  const summaryQuery = useQuery({
    queryKey: ["setups-summary"],
    queryFn: api.getSetupsSummary,
    refetchInterval: 30_000,
  });

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: api.getHealth,
    refetchInterval: 30_000,
  });

  const setups = useMemo(() => summaryQuery.data ?? [], [summaryQuery.data]);

  const counts = useMemo(() => {
    let up = 0;
    let down = 0;
    let monitoring = 0;
    let scanning = 0;

    const byCategory: Record<SetupSummary["category"], number> = {
      FOREX: 0,
      CRYPTO: 0,
      COMMODITIES: 0,
      INDICES: 0,
      SYNTHETIC: 0,
    };

    for (const setup of setups) {
      const trend = normalizeTrend(setup.trend);
      if (trend === "up") up += 1;
      if (trend === "down") down += 1;

      if (setup.fsm_state === "MONITORING") monitoring += 1;
      if (setup.fsm_state === "SCANNING") scanning += 1;

      if (setup.category in byCategory) {
        byCategory[setup.category] += 1;
      }
    }

    return { up, down, monitoring, scanning, byCategory };
  }, [setups]);

  const monitored = setups.length;
  const capacityCurrent = healthQuery.data?.active_setups ?? monitored;
  const heatmapTotalSlots = 50;
  const placeholderCount = Math.max(0, heatmapTotalSlots - setups.length);
  const totalForBars = Math.max(1, monitored);
  const monitoringRatio = monitored > 0 ? (counts.monitoring / monitored) * 100 : 0;

  const isLoading = summaryQuery.isLoading || healthQuery.isLoading;
  const isError = summaryQuery.isError || healthQuery.isError;

  return (
    <div
      className="flex h-full flex-1 flex-col overflow-hidden bg-[#131722] px-4 pb-4 pt-3"
      style={{ fontFamily: '"IBM Plex Mono", monospace' }}
    >
      <div className="mb-3 flex items-end justify-between border-b border-[#2A2E39] pb-2">
        <div>
          <h1 className="text-sm font-bold uppercase tracking-[0.16em] text-[#D1D4DC]">GLOBAL RADAR</h1>
          <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">MARKET BREADTH OVERVIEW</p>
        </div>
      </div>

      {isLoading ? (
        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-4">
          <StatSkeleton />
          <StatSkeleton />
          <StatSkeleton />
          <StatSkeleton />
        </div>
      ) : (
        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-4">
          <div className="border border-[#2A2E39] bg-[#1E222D] px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-[#787B86]">TRENDING UP</div>
            <div className="mt-1 text-xl font-bold text-[#089981]">{counts.up}</div>
          </div>
          <div className="border border-[#2A2E39] bg-[#1E222D] px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-[#787B86]">TRENDING DOWN</div>
            <div className="mt-1 text-xl font-bold text-[#F23645]">{counts.down}</div>
          </div>
          <div className="border border-[#2A2E39] bg-[#1E222D] px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-[#787B86]">MONITORED</div>
            <div className="mt-1 text-xl font-bold text-[#D1D4DC]">{monitored}</div>
          </div>
          <div className="border border-[#2A2E39] bg-[#1E222D] px-3 py-2">
            <div className="text-[9px] uppercase tracking-[0.12em] text-[#787B86]">CAPACITY</div>
            <div className="mt-1 text-xl font-bold text-[#F5A623]">{capacityCurrent}/50</div>
          </div>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-rows-[3fr_2fr] gap-3 overflow-hidden">
        <section className="min-h-0 border border-[#2A2E39] bg-[#1E222D] p-3">
          <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">THE BREADTH HEATMAP</div>
          <div className="h-[calc(100%-20px)] overflow-auto pr-1">
            {isLoading ? (
              <HeatmapSkeleton />
            ) : isError ? (
              <div className="flex h-full items-center justify-center text-sm font-bold text-[#F23645]">
                [SYSTEM]: RADAR OFFLINE
              </div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2">
                {setups.map((setup) => (
                  <div
                    key={`${setup.symbol}-${setup.timeframe}`}
                    className="relative h-[72px] border border-[#2A2E39] bg-[#1E222D] px-2 py-2"
                    style={{ borderLeft: `4px solid ${accentColor(setup)}` }}
                  >
                    <div className="truncate text-[12px] font-bold text-[#D1D4DC]">{setup.symbol}</div>
                    <div className="mt-4 text-[9px] uppercase tracking-[0.08em] text-[#787B86]">{setup.category}</div>
                    <div className="absolute bottom-1 right-2 text-[11px] text-[#787B86]">{formatScore(setup.trend_score)}</div>
                  </div>
                ))}
                {Array.from({ length: placeholderCount }).map((_, idx) => (
                  <div
                    key={`empty-${idx}`}
                    className="flex h-[72px] items-center justify-center border border-dashed border-[#1C1E24] bg-[#0D0F14] text-xl text-[#2A2E39]"
                  >
                    —
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
          <div className="min-h-0 border border-[#2A2E39] bg-[#1E222D] p-3">
            <div className="mb-3 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">CATEGORY DISTRIBUTION</div>
            <div className="space-y-3">
              {CATEGORIES.map((category) => {
                const value = counts.byCategory[category];
                const width = (value / totalForBars) * 100;
                const isZero = value === 0;
                return (
                  <div key={category}>
                    <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.08em] text-[#787B86]">
                      <span>{category}</span>
                      <span>{value}</span>
                    </div>
                    <div className="h-2 w-full bg-[#131722]">
                      <div
                        className="h-2"
                        style={{
                          width: `${width}%`,
                          backgroundColor: isZero ? "#2A2E39" : "#F5A623",
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="min-h-0 border border-[#2A2E39] bg-[#1E222D] p-3">
            <div className="mb-3 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">PHASE DISTRIBUTION</div>
            <div className="mb-3 grid grid-cols-2 gap-2">
              <div className="border border-[#2A2E39] bg-[#131722] px-3 py-2">
                <div className="text-[9px] uppercase tracking-[0.08em] text-[#787B86]">IMPULSE</div>
                <div className="mt-1 text-xl font-bold text-[#F5A623]">{counts.monitoring}</div>
              </div>
              <div className="border border-[#2A2E39] bg-[#131722] px-3 py-2">
                <div className="text-[9px] uppercase tracking-[0.08em] text-[#787B86]">SCANNING</div>
                <div className="mt-1 text-xl font-bold text-[#787B86]">{counts.scanning}</div>
              </div>
            </div>

            <div className="flex h-3 w-full overflow-hidden border border-[#2A2E39] bg-[#131722]">
              <div className="h-full bg-[#F5A623]" style={{ width: `${monitoringRatio}%` }} />
              <div className="h-full bg-[#2A2E39]" style={{ width: `${100 - monitoringRatio}%` }} />
            </div>

            <div className="mt-2 text-[10px] uppercase tracking-[0.08em] text-[#787B86]">
              {counts.monitoring} of {monitored} setups in active monitoring
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function RadarPage() {
  return (
    <QueryProvider>
      <RadarContent />
    </QueryProvider>
  );
}
