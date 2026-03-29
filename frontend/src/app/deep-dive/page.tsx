"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { TvChart } from "@/components/tv-chart";
import { RightSidebar } from "@/components/right-sidebar";
import { StatRow } from "@/components/stat-row";
import { QueryProvider } from "@/components/query-provider";
import { fetchBinanceCandles } from "@/lib/binance";
import { api } from "@/lib/api";
import type { ChartZone, StructuralState } from "@/lib/types";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"];
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

function zoneColor(depth: number): string {
  if (depth === 1) return "#2962FF";
  if (depth === 2) return "#089981";
  if (depth === 3) return "#9D2B6B";
  return "#F5A623";
}

function buildZones(structuralState?: StructuralState): ChartZone[] {
  const zones: ChartZone[] = [];
  const levels = structuralState?.levels ?? [];

  for (const level of levels) {
    const depth = Number(level.depth ?? 0);
    const color = zoneColor(depth);
    const bosPrice = level.structural_level?.price;
    const lower = level.choch_zone?.lower_boundary;
    const upper = level.choch_zone?.upper_boundary;

    if (typeof bosPrice === "number") {
      zones.push({
        price: bosPrice,
        color,
        title: `D${depth} BOS`,
      });
    }

    if (typeof lower === "number") {
      zones.push({
        price: lower,
        color,
        title: `D${depth} CHoCH L`,
      });
    }

    if (typeof upper === "number") {
      zones.push({
        price: upper,
        color,
        title: `D${depth} CHoCH H`,
      });
    }
  }

  return zones;
}

function convictionLevel(aligned: number, total: number): string {
  const ratio = total > 0 ? aligned / total : 0;
  if (ratio >= 1) return "HIGH";
  if (ratio >= 0.66) return "MEDIUM";
  return "LOW";
}

function DeepDiveContent() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("1h");
  const [activeTab, setActiveTab] = useState<"ANALYSIS" | "STRUCTURE" | "HISTORY">("ANALYSIS");

  const candlesQuery = useQuery({
    queryKey: ["binance-candles", symbol, timeframe],
    queryFn: () => fetchBinanceCandles(symbol, timeframe, 500),
    refetchInterval: 15_000,
  });

  const analysisQuery = useQuery({
    queryKey: ["analysis", symbol, timeframe],
    queryFn: () => api.getAnalysis(symbol, timeframe),
    refetchInterval: 15_000,
  });

  const setupsQuery = useQuery({
    queryKey: ["setups"],
    queryFn: api.getSetups,
    refetchInterval: 30_000,
  });

  const structuralState: StructuralState | undefined = analysisQuery.data?.structural_state;
  const zones = useMemo(() => buildZones(structuralState), [structuralState]);
  const depth = Number(analysisQuery.data?.max_depth_reached ?? structuralState?.max_depth_reached ?? 1);
  const completedSteps = Math.max(0, Math.min(5, structuralState?.levels?.length ?? 0));
  const trendProgression = ["IMP 1", "RET 1", "IMP 2", "RET 2", "IMP 3"];
  const waitingFor = String(analysisQuery.data?.waiting_for ?? structuralState?.waiting_for ?? "").trim();
  const trendBias = String(analysisQuery.data?.global_trend ?? structuralState?.global_trend ?? "up").toLowerCase().includes("down")
    ? "SHORT"
    : "LONG";
  const alignedTimeframes = useMemo(() => {
    const set = new Set<string>();
    const setups = setupsQuery.data ?? [];
    for (const setup of setups) {
      if (String(setup.symbol).toUpperCase() !== symbol.toUpperCase()) {
        continue;
      }
      set.add(String(setup.htf_timeframe).toLowerCase());
    }
    return set;
  }, [setupsQuery.data, symbol]);
  const analysisWithScore = analysisQuery.data as (typeof analysisQuery.data & { trend_score?: number }) | undefined;
  const scoreFromApi = Number(analysisWithScore?.trend_score);
  const score = Number.isFinite(scoreFromApi)
    ? Math.max(0, Math.min(100, scoreFromApi <= 1 ? scoreFromApi * 100 : scoreFromApi))
    : Math.max(0, Math.min(100, Math.round((zones.length > 0 ? 70 : 45) + depth * 6)));
  const scoreForRing = analysisQuery.isLoading ? 0 : score;

  return (
    <div className="h-full flex overflow-hidden bg-[#131722] text-[#D1D4DC]">
      <section className="flex-1 flex flex-col overflow-hidden border-r border-[#2A2E39] bg-[#131722]">
        <div className="h-14 border-b border-[#2A2E39] px-4 flex items-center gap-2">
          <select
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            className="h-8 border border-[#2A2E39] bg-[#131722] px-2 text-[10px] uppercase text-[#D1D4DC]"
          >
            {SYMBOLS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <select
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value)}
            className="h-8 border border-[#2A2E39] bg-[#131722] px-2 text-[10px] uppercase text-[#D1D4DC]"
          >
            {TIMEFRAMES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>

          <div className="ml-auto flex items-center gap-1">
            {TIMEFRAMES.map((tf) => {
              const isSelected = tf === timeframe;
              const isAligned = alignedTimeframes.has(tf.toLowerCase());
              return (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  className="h-6 px-2 border text-[9px] uppercase tracking-[0.08em]"
                  style={{
                    borderColor: isSelected ? "#F5A623" : isAligned ? "rgba(245,166,35,0.4)" : "#2A2E39",
                    background: isSelected ? "#F5A623" : "transparent",
                    color: isSelected ? "#131722" : isAligned ? "#C8851A" : "#787B86",
                  }}
                >
                  {tf}
                </button>
              );
            })}
          </div>

          <span className="ml-2 text-[10px] uppercase tracking-[0.14em] text-[#787B86]">
            {candlesQuery.isFetching || analysisQuery.isFetching ? "Syncing" : "Live"}
          </span>
        </div>

        <div className="flex-1 overflow-hidden relative">
          {candlesQuery.isLoading ? (
            <div className="h-full flex items-center justify-center text-[#787B86] text-sm">Loading candles...</div>
          ) : candlesQuery.isError ? (
            <div className="h-full flex items-center justify-center text-[#F5A623] text-sm">
              Failed to fetch Binance candles.
            </div>
          ) : (
            <div className="h-full flex flex-col">
              <div className="flex-1 min-h-0">
                <TvChart data={candlesQuery.data ?? []} zones={zones} />
              </div>
              <div className="h-20 border-t border-[#1C1E24] bg-[#0A0C10] px-4 py-3">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-[9px] uppercase tracking-[0.12em] text-[#4A4D58]">TREND PHASE PROGRESSION</p>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-1">
                      <div className="h-[3px] w-[10px] rounded-[1px] bg-[#F5A623]" />
                      <span className="text-[9px] uppercase tracking-[0.12em] text-[#F5A623]">IMPULSE</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="h-[3px] w-[10px] rounded-[1px] bg-[#3A6BFF]" />
                      <span className="text-[9px] uppercase tracking-[0.12em] text-[#6B8FFF]">RETRACEMENT</span>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-5 gap-1">
                  {trendProgression.map((stepLabel, index) => {
                    const isDone = index < completedSteps;
                    const isRetrace = stepLabel.startsWith("RET");
                    return (
                      <div key={stepLabel} className="flex flex-col gap-1">
                        <div
                          className="h-1"
                          style={{ backgroundColor: isDone ? (isRetrace ? "#3A6BFF" : "#F5A623") : "#1C1E24" }}
                        />
                        <span className="text-[9px] uppercase tracking-[0.08em] text-[#787B86]">{stepLabel}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <p className="text-[9px] uppercase tracking-[0.08em] text-[#2A2E39]">
                    CURRENT PHASE: {waitingFor.length > 0 ? waitingFor : "AWAITING DATA"}
                  </p>
                  <span
                    className="border px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em]"
                    style={{
                      backgroundColor: trendBias === "LONG" ? "rgba(245,166,35,0.1)" : "rgba(242,54,69,0.12)",
                      borderColor: trendBias === "LONG" ? "rgba(245,166,35,0.3)" : "rgba(242,54,69,0.35)",
                      color: trendBias === "LONG" ? "#F5A623" : "#F23645",
                    }}
                  >
                    {trendBias} BIAS
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <RightSidebar
        score={scoreForRing}
        direction={trendBias}
        mtfAlignment={Array.from(alignedTimeframes)}
        conviction={{
          level: convictionLevel(alignedTimeframes.size, 3),
          aligned: alignedTimeframes.size,
          total: 3,
        }}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      >
        {activeTab === "ANALYSIS" && (
          <div className="space-y-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] text-[#4A4D58] mb-2">MARKET STATS</p>
              <StatRow label="Global Trend" value={analysisQuery.data?.global_trend ?? "n/a"} />
              <StatRow label="Mitigations" value={analysisQuery.data?.total_mitigation_count ?? "n/a"} />
              <StatRow label="Max Depth" value={analysisQuery.data?.max_depth_reached ?? "n/a"} />
            </div>
            <div style={{ height: 1, background: "#1C1E24" }} />
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] text-[#4A4D58] mb-2">ZONE INFO</p>
              <StatRow label="Zones Loaded" value={zones.length} />
              <StatRow label="Current Phase" value={waitingFor.length > 0 ? waitingFor : "AWAITING DATA"} />
            </div>
          </div>
        )}

        {activeTab === "STRUCTURE" && (
          <div className="space-y-3">
            <div>
              <p className="text-[10px] uppercase tracking-[0.1em] text-[#4A4D58] mb-2">TREND STATE</p>
              <StatRow label="Waiting For" value={analysisQuery.data?.waiting_for ?? "n/a"} />
              <StatRow label="Structural Levels" value={zones.length} />
              <StatRow label="Depth" value={depth} />
            </div>
          </div>
        )}

        {activeTab === "HISTORY" && (
          <div>
            <p className="text-[10px] uppercase tracking-[0.1em] text-[#4A4D58] mb-2">STREAM</p>
            <StatRow label="Status" value="Live" valueColor="#4CAF7D" />
            <StatRow label="Sync" value={candlesQuery.isFetching || analysisQuery.isFetching ? "Syncing..." : "Idle"} />
            <StatRow label="Interval" value="15s" />
          </div>
        )}
      </RightSidebar>
    </div>
  );
}

export default function DeepDivePage() {
  return (
    <QueryProvider>
      <DeepDiveContent />
    </QueryProvider>
  );
}