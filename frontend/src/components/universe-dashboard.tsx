"use client";
import { useState } from "react";
import type { Setup, UniverseStats } from "@/lib/types";
import { StatCard } from "@/components/chronos-ui";

interface UniverseDashboardProps {
  setups: Setup[];
  stats: UniverseStats;
}

const CORRELATION_GROUPS = [
  { group: "Crypto Beta", lead: "BTCUSDT", linked: ["ETHUSDT", "SOLUSDT"], note: "Risk-on rotation cluster" },
  { group: "Macro Hedge", lead: "XAUUSD", linked: ["EURUSD"], note: "Dollar sensitivity overlap" },
  { group: "Synthetic Momentum", lead: "Volatility 75", linked: ["Crash 500", "Boom 1000"], note: "Synthetic impulse basket" },
];

function trendTone(trend: Setup["trend"]): string {
  if (trend === "up") return "#00C853";
  if (trend === "down") return "#FF1744";
  return "#787B86";
}

function formatCategory(value: string): string {
  return value.toUpperCase();
}

export function UniverseDashboard({ setups, stats }: UniverseDashboardProps) {
  const [phaseFilter, setPhaseFilter] = useState<string>("ALL PHASES");
  const [depthFilter, setDepthFilter] = useState<string>("ALL DEPTHS");
  const [heatmapSort, setHeatmapSort] = useState<string>("SCORE \u2193");
  const totalUniverse = 140;
  const selectedCount = stats.total_monitored;
  const notSelectedCount = Math.max(0, totalUniverse - selectedCount);
  const correlationFiltered = 20;

  const grouped = setups.reduce<Record<string, Setup[]>>((acc, setup) => {
    const key = setup.category;
    if (!acc[key]) acc[key] = [];
    acc[key].push(setup);
    return acc;
  }, {});

  return (
    <div className="flex h-full flex-1 flex-col overflow-auto bg-[#131722] p-4 text-[#D1D4DC]">
      <div className="mb-4 border-b border-[#363A45] pb-3">
        <h1 className="text-sm font-bold uppercase tracking-[0.16em] text-[#D1D4DC]">UNIVERSE</h1>
        <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">MARKET BREADTH DASHBOARD</p>
      </div>

      <section className="mb-4 grid grid-cols-4 gap-1 bg-[#080A0E] pt-1">
        <StatCard label="TOTAL MONITORED" value={stats.total_monitored} highlight />
        <div className="flex-1 border border-[#1C1E24] border-t border-t-[#1C1E24] bg-[#111318] px-[18px] py-[14px]">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-[#4A4D58]">CATEGORY BREAKDOWN</div>
          <div className="mt-3 space-y-2">
            {Object.entries(stats.by_category).map(([category, value]) => {
              const ratio = stats.total_monitored > 0 ? (value.count / stats.total_monitored) * 100 : 0;
              return (
                <div key={category}>
                  <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.08em]">
                    <span className="text-[#787B86]">{formatCategory(category)}</span>
                    <span className="text-[#D1D4DC]">{value.count}</span>
                  </div>
                  <div className="h-[3px] w-full bg-[#1C1E24]">
                    <div className="h-[3px] bg-[#F5A623]" style={{ width: `${ratio}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <StatCard label="IN RETRACEMENT" value={stats.by_phase.retracement} sub="entry zones active" />
        <StatCard label="DEPTH 3 CONFIRMED" value={stats.by_depth.depth_3} sub="highest conviction" highlight />
      </section>

      <section className="mb-4 border border-[#363A45] bg-[#1E222D]">
        <div className="border-b border-[#363A45] px-4 py-3 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">Correlation Groups</div>
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              {['GROUP', 'LEAD MARKET', 'LINKED MARKETS', 'NOTES'].map((header) => (
                <th key={header} className="border-b border-[#363A45] px-4 py-3 text-[9px] font-normal uppercase tracking-[0.14em] text-[#787B86]">{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CORRELATION_GROUPS.map((row) => (
              <tr key={row.group} className="border-b border-[#363A45]/50">
                <td className="px-4 py-3 text-[11px] font-semibold text-[#D1D4DC]">{row.group}</td>
                <td className="px-4 py-3 text-[11px] text-[#D1D4DC]">{row.lead}</td>
                <td className="px-4 py-3 text-[11px] text-[#787B86]">{row.linked.join(', ')}</td>
                <td className="px-4 py-3 text-[11px] text-[#787B86]">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mb-4 border border-[#363A45] bg-[#1E222D] p-4">
        <div style={{ fontSize: 9, letterSpacing: "0.14em", color: "#434651" }}>SCAN COVERAGE</div>
        <div style={{ marginTop: 4, fontSize: 9, color: "#2A2E39" }}>
          Top 50 active · remaining markets available on next discovery scan
        </div>
        <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
          {[
            { label: "TOTAL IN UNIVERSE", value: totalUniverse },
            { label: "IN TOP 50", value: selectedCount },
            { label: "NOT SELECTED", value: notSelectedCount },
            { label: "CORRELATION FILTERED", value: correlationFiltered },
          ].map((item) => (
            <div key={item.label} style={{ border: "1px solid #1E222D", background: "#131722", padding: "10px 8px", textAlign: "center" }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: "#434651", lineHeight: 1 }}>
                {item.value}
              </div>
              <div style={{ marginTop: 6, fontSize: 8, color: "#2A2E39", letterSpacing: "0.08em" }}>
                {item.label}
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 8, fontSize: 9, color: "#1E222D", textAlign: "center" }}>
          Click SCAN ALL on the Scanner page to refresh the full universe
        </div>
      </section>

      <section className="border border-[#363A45] bg-[#1E222D] p-4">
        <div className="mb-3 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">Category Heatmap</div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
          {["ALL PHASES", "RETRACEMENT", "IMPULSE"].map(opt => (
            <button key={opt} onClick={() => setPhaseFilter(opt)} style={{
              fontSize: 9, padding: "2px 8px", border: "1px solid #1E222D", borderRadius: 0,
              background: phaseFilter === opt ? "#F5A623" : "transparent",
              color: phaseFilter === opt ? "#0B0D11" : "#434651",
              cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.08em",
            }}>{opt}</button>
          ))}
          <span style={{ color: "#2A2D36", fontSize: 9, margin: "0 4px" }}>|</span>
          <select value={heatmapSort} onChange={e => setHeatmapSort(e.target.value)} style={{
            background: "#0D0F14", color: "#434651", border: "1px solid #1E222D", borderRadius: 0,
            fontSize: 9, padding: "2px 8px", fontFamily: "'IBM Plex Mono', monospace",
            letterSpacing: "0.08em", cursor: "pointer", appearance: "none", outline: "none",
          }}>
            {["SCORE \u2193", "SCORE \u2191", "SYMBOL A-Z", "DEPTH \u2193"].map(opt => (
              <option key={opt} value={opt} style={{ background: "#0D0F14", color: "#D1D4DC" }}>{opt}</option>
            ))}
          </select>
          <span style={{ color: "#2A2D36", fontSize: 9, margin: "0 4px" }}>|</span>
          {["ALL DEPTHS", "1", "2", "3"].map(opt => (
            <button key={opt} onClick={() => setDepthFilter(opt)} style={{
              fontSize: 9, padding: "2px 8px", border: "1px solid #1E222D", borderRadius: 0,
              background: depthFilter === opt ? "#F5A623" : "transparent",
              color: depthFilter === opt ? "#0B0D11" : "#434651",
              cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.08em",
            }}>{opt}</button>
          ))}
        </div>
        <div className="space-y-4">
          {Object.entries(grouped).map(([category, rows]) => {
            const filteredRows = rows
              .filter(s => phaseFilter === "ALL PHASES" || s.current_phase.toUpperCase() === phaseFilter)
              .filter(s => depthFilter === "ALL DEPTHS" || String(s.pullback_depth) === depthFilter)
              .sort((a, b) => {
                if (heatmapSort === "SCORE \u2193") return b.trend_score - a.trend_score;
                if (heatmapSort === "SCORE \u2191") return a.trend_score - b.trend_score;
                if (heatmapSort === "SYMBOL A-Z") return String(a.symbol).localeCompare(String(b.symbol));
                if (heatmapSort === "DEPTH \u2193") return b.pullback_depth - a.pullback_depth;
                return 0;
              });
            if (filteredRows.length === 0) return null;
            return (
              <div key={category}>
                <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-[#787B86]">{formatCategory(category)}</div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
                  {filteredRows.map((setup) => (
                    <div
                      key={setup.setup_id}
                      className="border border-[#363A45] bg-[#2A2E39] p-3"
                      style={{ borderLeft: setup.current_phase === "retracement" ? "2px solid #F5A623" : "1px solid #363A45" }}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-1 text-[12px] font-semibold text-[#D1D4DC]">
                            <span>{setup.symbol}</span>
                            {setup.fsm_state === "MONITORING" && <span style={{ color: "#F5A623" }}>●</span>}
                          </div>
                          <div className="mt-1 text-[10px] uppercase tracking-[0.08em] text-[#787B86]">{setup.timeframe}</div>
                        </div>
                        <div className="h-3 w-3 rounded-full" style={{ background: trendTone(setup.trend) }} />
                      </div>
                      <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-[0.08em]">
                        <span className="text-[#787B86]">Trend</span>
                        <span style={{ color: trendTone(setup.trend) }}>{setup.trend}</span>
                      </div>
                      <div className="mt-2 text-right text-[10px] text-[#4A4D58]">{setup.trend_score.toFixed(0)}</div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}