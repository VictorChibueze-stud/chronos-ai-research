"use client";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import { RelativeTimeWithTooltip } from "@/components/ui/relative-time";
import { Tooltip } from "@/components/ui/tooltip";
import { formatLocaleInt, formatScore } from "@/lib/format-display";
import type { Setup, UniverseStats } from "@/lib/types";
import {
  MARKET_DIST_READINESS_COLORS,
  UNIVERSE_CATEGORY_ORDER,
  buildMarketDistributionRows,
  formatUniverseCategoryLabel,
  normalizeUniverseCategory,
  type ReadinessStackKey,
} from "@/lib/universe-category";
import { StatCard } from "@/components/chronos-ui";

const HEATMAP_COLLAPSE_PREFIX = "ikenga.universeHeatmap.collapsed.";

interface UniverseDashboardProps {
  setups: Setup[];
  stats: UniverseStats;
  onSetupMerged?: (setup: Setup) => void;
  /** ISO timestamp of latest completed universe_ranking job */
  lastRankedIso?: string | null;
}

function trendTone(trend: Setup["trend"]): string {
  if (trend === "up") return "#00C853";
  if (trend === "down") return "#FF1744";
  return "var(--text-dim)";
}

function readinessDotColor(state: Setup["readiness_state"] | undefined): string {
  if (state === "FULL") return "#26A69A";
  if (state === "PARTIAL") return "#F5A623";
  if (state === "ERROR") return "#EF5350";
  return "var(--text-dim)";
}

function setupCardKey(setup: Setup, index: number): string {
  if (typeof setup.setup_id === "number") {
    return `setup-${setup.setup_id}`;
  }
  return `placeholder-${setup.symbol}-${setup.timeframe}-${index}`;
}

function rankDisplay(setup: Setup): { text: string; color: string } {
  const r = setup.universe_rank;
  if (r == null || !Number.isFinite(Number(r))) {
    return { text: "—", color: "var(--text-dim)" };
  }
  const n = Math.floor(Number(r));
  return {
    text: `#${n}`,
    color: n >= 1 && n <= 50 ? "#F5A623" : "var(--text-primary)",
  };
}

function basisBadgeLabel(basis: Setup["timeframe_basis"]): string | null {
  if (basis === "weekly") return "W";
  if (basis === "daily") return "D";
  return null;
}

function isOutsideTop50(setup: Setup): boolean {
  const r = setup.universe_rank;
  if (r == null || !Number.isFinite(Number(r))) return true;
  return Math.floor(Number(r)) > 50;
}

function loadCollapsedFromStorage(): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  if (typeof window === "undefined") return out;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k?.startsWith(HEATMAP_COLLAPSE_PREFIX)) continue;
      if (localStorage.getItem(k) === "true") {
        out[k.slice(HEATMAP_COLLAPSE_PREFIX.length)] = true;
      }
    }
  } catch {
    /* private mode / quota */
  }
  return out;
}

export function UniverseDashboard({ setups, stats, onSetupMerged, lastRankedIso }: UniverseDashboardProps) {
  const router = useRouter();
  const [phaseFilter, setPhaseFilter] = useState<string>("ALL PHASES");
  const [depthFilter, setDepthFilter] = useState<string>("ALL DEPTHS");
  const [heatmapSort, setHeatmapSort] = useState<string>("SCORE \u2193");
  const [hoveredSymbol, setHoveredSymbol] = useState<string | null>(null);
  const [activeSymbols, setActiveSymbols] = useState<Set<string>>(new Set());
  const [bootstrapLoading, setBootstrapLoading] = useState<Record<string, boolean>>({});
  const [bootstrapError, setBootstrapError] = useState<Record<string, string>>({});
  const [collapsedCats, setCollapsedCats] = useState<Record<string, boolean>>(loadCollapsedFromStorage);

  const totalUniverse = setups.length;
  const selectedCount = activeSymbols.size;
  const notSelectedCount = Math.max(0, totalUniverse - selectedCount);
  const placeholderRowCount = useMemo(
    () => setups.filter((s) => s.setup_id == null).length,
    [setups],
  );
  const activeSymbolsList = useMemo(() => Array.from(activeSymbols), [activeSymbols]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const k of UNIVERSE_CATEGORY_ORDER) counts[k] = 0;
    for (const s of setups) {
      const k = normalizeUniverseCategory(s.category);
      counts[k] = (counts[k] ?? 0) + 1;
    }
    return counts;
  }, [setups]);

  const distributionChartData = useMemo(() => buildMarketDistributionRows(setups), [setups]);

  const grouped = useMemo(
    () =>
      setups.reduce<Record<string, Setup[]>>((acc, setup) => {
        const key = normalizeUniverseCategory(setup.category);
        if (!acc[key]) acc[key] = [];
        acc[key].push(setup);
        return acc;
      }, {}),
    [setups],
  );

  const sortedCategoryEntries = useMemo(() => {
    const keys = Object.keys(grouped);
    const ordered = UNIVERSE_CATEGORY_ORDER.filter((k) => keys.includes(k));
    const orderSet = new Set<string>(UNIVERSE_CATEGORY_ORDER);
    const rest = keys.filter((k) => !orderSet.has(k)).sort();
    return [...ordered, ...rest].map((k) => [k, grouped[k]!] as const);
  }, [grouped]);

  const allHeatmapCategoryKeys = useMemo(() => sortedCategoryEntries.map(([k]) => k), [sortedCategoryEntries]);

  useEffect(() => {
    let cancelled = false;
    api
      .getActiveList()
      .then((data) => {
        if (cancelled) return;
        const values = (data?.symbols ?? []).map((s) => String(s).toUpperCase());
        setActiveSymbols(new Set(values));
      })
      .catch(() => {
        if (!cancelled) {
          setActiveSymbols(new Set());
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function persistCollapsed(catKey: string, collapsed: boolean) {
    try {
      localStorage.setItem(`${HEATMAP_COLLAPSE_PREFIX}${catKey}`, String(collapsed));
    } catch {
      /* ignore */
    }
  }

  function setCategoryCollapsed(catKey: string, collapsed: boolean) {
    persistCollapsed(catKey, collapsed);
    setCollapsedCats((prev) => ({ ...prev, [catKey]: collapsed }));
  }

  function collapseAllHeatmap() {
    const next: Record<string, boolean> = { ...collapsedCats };
    for (const k of allHeatmapCategoryKeys) {
      next[k] = true;
      persistCollapsed(k, true);
    }
    setCollapsedCats(next);
  }

  function expandAllHeatmap() {
    const next: Record<string, boolean> = { ...collapsedCats };
    for (const k of allHeatmapCategoryKeys) {
      next[k] = false;
      persistCollapsed(k, false);
    }
    setCollapsedCats(next);
  }

  return (
    <div className="flex h-full flex-1 flex-col overflow-auto bg-background-surface p-4 text-text-primary">
      <div className="mb-4 border-b border-border-strong pb-3">
        <h1 className="text-sm font-bold uppercase tracking-[0.16em] text-text-primary">UNIVERSE</h1>
        <p style={{ marginTop: 4, fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", letterSpacing: "0.08em", textTransform: "uppercase" }}>MARKET BREADTH DASHBOARD</p>
        {lastRankedIso ? (
          <p style={{ marginTop: 4, fontFamily: "var(--font-sans)", fontSize: 11, color: "var(--text-dim)" }}>
            Last ranked:{" "}
            <RelativeTimeWithTooltip iso={lastRankedIso} className="uppercase tracking-[0.1em]" />
          </p>
        ) : null}
      </div>

      <section className="mb-4 grid grid-cols-4 gap-1 bg-background-base pt-1">
        <StatCard label="TOTAL MONITORED" value={formatLocaleInt(stats.total_monitored)} highlight />
        <div className="flex-1 border border-[var(--border-default)] border-t border-t-[var(--border-default)] bg-[var(--bg-surface)] px-[18px] py-[14px]">
          <div style={{ marginBottom: 8, fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>CATEGORY BREAKDOWN</div>
          <div className="mt-3 space-y-2">
            {UNIVERSE_CATEGORY_ORDER.map((category) => {
              const count = categoryCounts[category] ?? 0;
              const ratio = totalUniverse > 0 ? (count / totalUniverse) * 100 : 0;
              return (
                <div key={category}>
                  <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.08em]">
                    <span style={{ color: "var(--text-secondary)" }}>{formatUniverseCategoryLabel(category)}</span>
                    <span className="text-text-primary">{formatLocaleInt(count)}</span>
                  </div>
                  <div className="h-[3px] w-full bg-[var(--border-subtle)]">
                    <div className="h-[3px] bg-[#F5A623]" style={{ width: `${ratio}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <Tooltip content="Markets in confirmed prime retracement">
          <span style={{ display: "block", flex: 1, cursor: "help" }}>
            <StatCard label="IN RETRACEMENT" value={formatLocaleInt(stats.by_phase.retracement)} sub="entry zones active" />
          </span>
        </Tooltip>
        <Tooltip content="Markets where walker found this depth level">
          <span style={{ display: "block", flex: 1, cursor: "help" }}>
            <StatCard label="DEPTH 3 CONFIRMED" value={formatLocaleInt(stats.by_depth.depth_3)} sub="highest conviction" highlight />
          </span>
        </Tooltip>
      </section>

      <section className="mb-4 border border-border-strong bg-background-elevated p-4">
        <div style={{ borderBottom: "1px solid var(--border-strong)", paddingBottom: 12, fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          MARKET DISTRIBUTION
        </div>
        <p style={{ marginTop: 8, fontFamily: "var(--font-sans)", fontSize: 9, lineHeight: 1.6, letterSpacing: "0.08em", color: "var(--text-dim)" }}>
          By category and readiness (full / partial / error / unscanned)
        </p>
        <div className="mt-3 h-[220px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              layout="vertical"
              data={distributionChartData}
              margin={{ top: 4, right: 8, left: 4, bottom: 4 }}
              barCategoryGap={6}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" horizontal={false} />
              <XAxis type="number" stroke="var(--text-muted)" tick={{ fill: "var(--text-dim)", fontSize: 9 }} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="label"
                width={72}
                stroke="var(--text-dim)"
                tick={{ fill: "var(--text-dim)", fontSize: 9 }}
              />
              <RechartsTooltip
                contentStyle={{
                  background: "var(--bg-base)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: 0,
                  fontSize: 10,
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
                labelStyle={{ color: "var(--text-primary)" }}
              />
              <Legend
                wrapperStyle={{ fontSize: 9, fontFamily: "'IBM Plex Mono', monospace", color: "var(--text-dim)" }}
              />
              {(["FULL", "PARTIAL", "ERROR", "UNSCANNED"] as ReadinessStackKey[]).map((key) => (
                <Bar
                  key={key}
                  dataKey={key}
                  stackId="readiness"
                  fill={MARKET_DIST_READINESS_COLORS[key]}
                  name={key}
                  radius={[0, 0, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="mb-4 border border-border-strong bg-background-elevated p-4">
        <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, color: "var(--text-secondary)", letterSpacing: "0.06em", textTransform: "uppercase" }}>SCAN COVERAGE</div>
        <div style={{ marginTop: 4, fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-dim)" }}>
          Top 350 Binance + all Deriv · readiness dot: full / partial / error / unscanned
        </div>
        <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
          {[
            { label: "TOTAL IN UNIVERSE", value: totalUniverse },
            { label: "IN TOP 350", value: selectedCount },
            { label: "NOT SELECTED", value: notSelectedCount },
            { label: "NO SETUP ROW", value: placeholderRowCount },
          ].map((item) => (
            <div key={item.label} style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)", padding: "10px 8px", textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1 }}>
                {item.value}
              </div>
              <div style={{ marginTop: 6, fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-secondary)", letterSpacing: "0.08em" }}>
                {item.label}
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 8, fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-muted)", textAlign: "center" }}>
          Click SCAN ALL on the Scanner page to refresh the full universe
        </div>
      </section>

      <section className="border border-border-strong bg-background-elevated p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-[10px] uppercase tracking-[0.12em] text-text-dim">Category Heatmap</div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={collapseAllHeatmap}
              className="font-mono text-[9px] uppercase tracking-[0.08em] hover:text-text-dim"
              style={{ border: "1px solid var(--border-default)", background: "transparent", padding: "2px 8px", cursor: "pointer", color: "var(--text-dim)" }}
            >
              COLLAPSE ALL
            </button>
            <button
              type="button"
              onClick={expandAllHeatmap}
              className="font-mono text-[9px] uppercase tracking-[0.08em] hover:text-text-dim"
              style={{ border: "1px solid var(--border-default)", background: "transparent", padding: "2px 8px", cursor: "pointer", color: "var(--text-dim)" }}
            >
              EXPAND ALL
            </button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
          {["ALL PHASES", "RETRACEMENT", "IMPULSE"].map((opt) => (
            <Tooltip key={opt} content={`Filter heatmap by ${opt.toLowerCase()}`}>
              <button
                onClick={() => setPhaseFilter(opt)}
                style={{
                  fontSize: 9,
                  padding: "2px 8px",
                  border: "1px solid var(--border-default)",
                  borderRadius: 0,
                  background: phaseFilter === opt ? "#F5A623" : "transparent",
                  color: phaseFilter === opt ? "var(--bg-base)" : "var(--text-dim)",
                  cursor: "pointer",
                  fontFamily: "'IBM Plex Mono', monospace",
                  letterSpacing: "0.08em",
                }}
              >
                {opt}
              </button>
            </Tooltip>
          ))}
          <span style={{ color: "var(--border-default)", fontSize: 9, margin: "0 4px" }}>|</span>
          <Tooltip content="Sort universe heatmap cards">
            <select
              value={heatmapSort}
              onChange={(e) => setHeatmapSort(e.target.value)}
              style={{
                background: "var(--bg-surface)",
                color: "var(--text-dim)",
                border: "1px solid var(--border-default)",
                borderRadius: 0,
                fontSize: 9,
                padding: "2px 8px",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.08em",
                cursor: "pointer",
                appearance: "none",
                outline: "none",
              }}
            >
              {["SCORE \u2193", "SCORE \u2191", "SYMBOL A-Z", "DEPTH \u2193"].map((opt) => (
                <option key={opt} value={opt} style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}>
                  {opt}
                </option>
              ))}
            </select>
          </Tooltip>
          <span style={{ color: "var(--border-default)", fontSize: 9, margin: "0 4px" }}>|</span>
          {["ALL DEPTHS", "1", "2", "3"].map((opt) => (
            <Tooltip key={opt} content={`Filter by depth ${opt}`}>
              <button
                onClick={() => setDepthFilter(opt)}
                style={{
                  fontSize: 9,
                  padding: "2px 8px",
                  border: "1px solid var(--border-default)",
                  borderRadius: 0,
                  background: depthFilter === opt ? "#F5A623" : "transparent",
                  color: depthFilter === opt ? "var(--bg-base)" : "var(--text-dim)",
                  cursor: "pointer",
                  fontFamily: "'IBM Plex Mono', monospace",
                  letterSpacing: "0.08em",
                }}
              >
                {opt}
              </button>
            </Tooltip>
          ))}
        </div>
        <div className="space-y-4">
          {sortedCategoryEntries.map(([category, rows]) => {
            const filteredRows = rows
              .filter((s) => phaseFilter === "ALL PHASES" || s.current_phase.toUpperCase() === phaseFilter)
              .filter((s) => depthFilter === "ALL DEPTHS" || String(s.pullback_depth) === depthFilter)
              .sort((a, b) => {
                if (heatmapSort === "SCORE \u2193") return b.trend_score - a.trend_score;
                if (heatmapSort === "SCORE \u2191") return a.trend_score - b.trend_score;
                if (heatmapSort === "SYMBOL A-Z") return String(a.symbol).localeCompare(String(b.symbol));
                if (heatmapSort === "DEPTH \u2193") return b.pullback_depth - a.pullback_depth;
                return 0;
              });
            if (filteredRows.length === 0) return null;
            const collapsed = Boolean(collapsedCats[category]);
            return (
              <div key={category}>
                <button
                  type="button"
                  onClick={() => setCategoryCollapsed(category, !collapsed)}
                  className="mb-2 flex w-full items-center gap-1 text-left text-[10px] uppercase tracking-[0.12em] text-text-dim hover:text-text-primary"
                >
                  {collapsed ? (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  )}
                  <span>{formatUniverseCategoryLabel(category)}</span>
                  <span className="ml-auto font-mono text-[9px]" style={{ color: "var(--text-dim)" }}>({filteredRows.length})</span>
                </button>
                {!collapsed ? (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-3">
                    {filteredRows.map((setup, index) => {
                      const symbolU = String(setup.symbol || "").toUpperCase();
                      const rank = rankDisplay(setup);
                      const basisBadge = basisBadgeLabel(setup.timeframe_basis);
                      const loadingBootstrap = Boolean(bootstrapLoading[symbolU]);
                      const errMsg = bootstrapError[symbolU];
                      const isActive = activeSymbols.has(symbolU);
                      const isPlaceholder = setup.setup_id == null;

                      return (
                        <div
                          key={setupCardKey(setup, index)}
                          className="border border-border-default bg-[var(--bg-surface)] p-3"
                          onMouseEnter={() => setHoveredSymbol(setup.symbol)}
                          onMouseLeave={() => setHoveredSymbol(null)}
                          onClick={() =>
                            router.push(`/market?symbol=${encodeURIComponent(setup.symbol)}&timeframe=1h`)
                          }
                          style={{
                            borderLeft: setup.current_phase === "retracement" ? "2px solid #F5A623" : "1px solid var(--border-default)",
                            borderStyle: isPlaceholder ? "dashed" : "solid",
                            cursor: "pointer",
                            background: hoveredSymbol === setup.symbol ? "var(--bg-hover)" : "var(--bg-surface)",
                            transition: "background 0.12s ease",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
                              justifyContent: "space-between",
                              marginBottom: 6,
                              gap: 8,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 700,
                                color: rank.color,
                                fontFamily: "'IBM Plex Mono', monospace",
                                letterSpacing: "0.04em",
                              }}
                            >
                              {rank.text}
                            </span>
                            {basisBadge ? (
                              <span
                                style={{
                                  fontSize: 8,
                                  padding: "1px 5px",
                                  border: "1px solid var(--border-subtle)",
                                  color: "var(--text-dim)",
                                  letterSpacing: "0.1em",
                                  fontFamily: "'IBM Plex Mono', monospace",
                                }}
                              >
                                {basisBadge}
                              </span>
                            ) : (
                              <span style={{ width: 1, height: 1 }} aria-hidden />
                            )}
                          </div>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="flex items-center gap-1 text-[12px] font-semibold text-text-primary">
                                <span
                                  title={
                                    setup.readiness_state
                                      ? `${setup.readiness_state}${setup.readiness_coverage?.missing?.length ? ` · missing: ${setup.readiness_coverage.missing.join(", ")}` : ""}`
                                      : "UNSCANNED"
                                  }
                                  className="inline-block h-2 w-2 shrink-0 rounded-full"
                                  style={{ background: readinessDotColor(setup.readiness_state) }}
                                />
                                <span>{setup.symbol}</span>
                                {setup.fsm_state === "MONITORING" && <span style={{ color: "#F5A623" }}>●</span>}
                              </div>
                              <div className="mt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                                {setup.timeframe}
                                {isPlaceholder ? (
                                  <span className="ml-1" style={{ color: "var(--text-dim)" }}>· PLACEHOLDER</span>
                                ) : null}
                              </div>
                              {setup.readiness_state === "PARTIAL" && setup.readiness_coverage?.available?.length ? (
                                <div style={{ marginTop: 2, fontSize: 9, color: "var(--text-secondary)", fontFamily: "'IBM Plex Mono', monospace" }}>
                                  {setup.readiness_coverage.available.join(" · ")}
                                </div>
                              ) : null}
                            </div>
                            <div className="h-3 w-3 rounded-full" style={{ background: trendTone(setup.trend) }} />
                          </div>
                          <div className="mt-3 flex items-center justify-between text-[10px] uppercase tracking-[0.08em]">
                            <span className="text-text-dim">Trend</span>
                            <span style={{ color: trendTone(setup.trend) }}>{setup.trend}</span>
                          </div>
                          <div className="mt-2 text-right text-[10px]" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>{formatScore(setup.trend_score)}</div>
                          {loadingBootstrap ? (
                            <div style={{ marginTop: 8, display: "flex", justifyContent: "flex-end" }}>
                              <div
                                style={{
                                  width: 14,
                                  height: 14,
                                  borderRadius: "50%",
                                  border: "2px solid var(--border-default)",
                                  borderTopColor: "#F5A623",
                                  animation: "scanner-spin 0.8s linear infinite",
                                }}
                              />
                            </div>
                          ) : null}
                          {errMsg ? (
                            <div style={{ marginTop: 6, fontSize: 8, color: "#E05A5A", lineHeight: 1.35 }}>{errMsg}</div>
                          ) : null}
                          <div style={{ marginTop: 8, display: "flex", justifyContent: "flex-end" }}>
                            <button
                              type="button"
                              disabled={loadingBootstrap}
                              onClick={async (event) => {
                                event.stopPropagation();
                                const symbol = symbolU;
                                if (!symbol) return;
                                const next = new Set(activeSymbolsList);
                                try {
                                  if (next.has(symbol)) {
                                    await api.removeActiveSymbol(symbol);
                                    next.delete(symbol);
                                    setActiveSymbols(next);
                                    return;
                                  }

                                  await api.addActiveSymbol(symbol);
                                  next.add(symbol);
                                  setActiveSymbols(next);

                                  if (isOutsideTop50(setup) && onSetupMerged) {
                                    setBootstrapLoading((m) => ({ ...m, [symbol]: true }));
                                    setBootstrapError((m) => {
                                      const { [symbol]: _removed, ...rest } = m;
                                      return rest;
                                    });
                                    try {
                                      const refreshed = await api.getSetup(symbol);
                                      onSetupMerged(refreshed);
                                    } catch (e) {
                                      const msg = e instanceof Error ? e.message : "Bootstrap failed";
                                      setBootstrapError((m) => ({ ...m, [symbol]: msg }));
                                      window.setTimeout(() => {
                                        setBootstrapError((m) => {
                                          const { [symbol]: _r, ...rest } = m;
                                          return rest;
                                        });
                                      }, 5000);
                                    } finally {
                                      setBootstrapLoading((m) => {
                                        const { [symbol]: _l, ...rest } = m;
                                        return rest;
                                      });
                                    }
                                  }
                                } catch {
                                  // active-list failed; leave state unchanged
                                }
                              }}
                              style={{
                                fontSize: 9,
                                padding: "2px 6px",
                                border: "1px solid var(--border-subtle)",
                                background: isActive ? "#F5A623" : "transparent",
                                color: isActive ? "var(--bg-base)" : "var(--text-dim)",
                                letterSpacing: "0.08em",
                                fontFamily: "'IBM Plex Mono', monospace",
                                cursor: loadingBootstrap ? "wait" : "pointer",
                                opacity: loadingBootstrap ? 0.65 : 1,
                              }}
                            >
                              {isActive ? "ACTIVE" : "ADD TO ACTIVE"}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
