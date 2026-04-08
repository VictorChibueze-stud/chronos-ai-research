"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import {
  pickCoreParams,
  type AnalysisCoreParams,
} from "@/lib/analysis-params-storage";
import { formatScore } from "@/lib/format-display";
import { PanelEdgeCollapseToggle } from "@/components/ui/panel-edge-collapse-toggle";
import { Tooltip } from "@/components/ui/tooltip";
import type {
  AnalysisDevParams,
  AnalysisResponse,
  CandleBar,
  Setup,
  SignalHistoryItem,
  TrendLeg,
  TrendWindowStructure,
} from "@/lib/types";
import { STRUCTURE_CANDIDATE_MOVE } from "@/lib/structure-colors";
import { MarketContextPanel } from "@/components/market-context-panel";

const CandleChart = dynamic(() => import("@/components/candle-chart"), { ssr: false });

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface MarketCockpitProps {
  setup: Setup;
  candles: CandleBar[];
  analysisData?: AnalysisResponse;
  /** False while the Market page is still fetching analysis for the active symbol/TF (candles already loaded). */
  analysisOverlaysReady?: boolean;
  /** Full universe for grouped market picker (from `getSetupsUniverse`). */
  universeMarkets?: Setup[];
  activeTimeframe: string;
  onTimeframeChange: (tf: string) => void;
  onNavigate: (symbol: string) => void;
  candlesLoading?: boolean;
  isSwitchingTimeframe?: boolean;
  tfError?: string | null;
  signalHistory?: SignalHistoryItem[];
  analysisDevParams: AnalysisDevParams;
  /** Serialized debug query keys for GET /api/analysis. */
  analysisQueryForApi: Record<string, string | number | boolean>;
  onAnalysisDevParamsChange: (next: AnalysisDevParams) => void;
  onApplyCoreAnalysisParams: (core: AnalysisCoreParams) => void;
  onResetAnalysisParams: () => void;
  /** Back control above chart; omitted on empty market route. */
  onBack?: () => void;
}

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"] as const;

const algoInputStyle: CSSProperties = {
  background: "#131722",
  border: "1px solid #2A2E39",
  color: "#D1D4DC",
  padding: "6px 8px",
  fontSize: 11,
  fontFamily: '"IBM Plex Mono", monospace',
};

type TrendStartOverlayPayload = {
  start_timestamp: string;
  start_price: number;
  current_timestamp: string;
  current_price: number;
  trend: string;
};

const STRUCTURAL_LAYER_DESCRIPTIONS: Record<number, string> = {
  1: "First internal impulse inside retracement",
  2: "Response move after BOS crossed at layer 1",
  3: "Response move after BOS crossed at layer 2",
};

function structuralLayerDescription(depth: number): string {
  return STRUCTURAL_LAYER_DESCRIPTIONS[depth] ?? STRUCTURAL_LAYER_DESCRIPTIONS[3]!;
}

/** Last confirmed retracement end → current bar (white dotted developing path). */
function provisionalDevelopingFromLegs(legs: TrendLeg[]): { start_timestamp: string; start_price: number } | null {
  for (let i = legs.length - 1; i >= 0; i--) {
    const L = legs[i]!;
    if (L.confirmed && L.type === "retracement" && L.end_timestamp) {
      const ep = L.end_price;
      if (ep === null || ep === undefined) {
        return null;
      }
      return { start_timestamp: L.end_timestamp, start_price: ep };
    }
  }
  return null;
}

function timeframeLabel(tf: string): string {
  if (tf === "1w") return "1W";
  if (tf === "1mo") return "1M";
  return tf.toUpperCase();
}

function formatPrice(value: number): string {
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (Math.abs(value) >= 10) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

function firstConfirmedLeg(legs: TrendLeg[]): TrendLeg | null {
  return legs.find((l) => l.confirmed) ?? null;
}

function lastConfirmedImpulse(legs: TrendLeg[]): TrendLeg | null {
  const imp = legs.filter((l) => l.confirmed && l.type === "impulse");
  return imp[imp.length - 1] ?? null;
}

function formatTrendDateUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function trendColor(trend: string): string {
  const t = String(trend ?? "").toLowerCase();
  if (t === "up") return "#00C853";
  if (t === "down") return "#FF1744";
  return "#787B86";
}

const MARKET_CATEGORY_GROUPS = ["crypto", "forex", "synthetic", "commodity", "other"] as const;
type MarketCategoryGroup = (typeof MARKET_CATEGORY_GROUPS)[number];

const GROUP_HEADING: Record<MarketCategoryGroup, string> = {
  crypto: "Crypto",
  forex: "Forex",
  synthetic: "Synthetic",
  commodity: "Commodity",
  other: "Other",
};

function marketCategoryGroup(category: string | undefined): MarketCategoryGroup {
  const c = String(category ?? "").toUpperCase();
  if (c === "CRYPTO") return "crypto";
  if (c === "FOREX") return "forex";
  if (c === "SYNTHETIC" || c === "INDICES") return "synthetic";
  if (c === "COMMODITIES" || c === "COMMODITY") return "commodity";
  return "other";
}

function dedupeUniverseBySymbol(rows: Setup[]): Setup[] {
  const map = new Map<string, Setup>();
  for (const row of rows) {
    const sym = String(row.symbol ?? "").trim().toUpperCase();
    if (!sym || map.has(sym)) continue;
    map.set(sym, row);
  }
  return Array.from(map.values()).sort((a, b) => a.symbol.localeCompare(b.symbol));
}

function phaseTone(phase: Setup["current_phase"]): string {
  return phase === "retracement" ? "#F5A623" : "#787B86";
}

function structureBadgeLabel(setup: Setup): string {
  if (!setup.active_bos) {
    return "NO BREAK";
  }

  if (setup.active_bos.break_type === "true") return "TRUE BREAK";
  if (setup.active_bos.break_type === "false") return "FALSE BREAK";
  if (setup.active_bos.break_type === "broken") return "BROKEN";
  return "PENDING";
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function ValueText({ children, color = "#D1D4DC" }: { children: React.ReactNode; color?: string }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 700, color, fontFamily: '"IBM Plex Mono", monospace' }}>{children}</div>
  );
}

function renderEmaStatus(setup: Setup) {
  if (setup.ema_signal === "LONG") {
    return {
      color: "#4CAF7D",
      text: "EMA 9 × EMA 21 — LONG SIGNAL",
    };
  }

  if (setup.ema_signal === "SHORT") {
    return {
      color: "#E05A5A",
      text: "EMA 9 × EMA 21 — SHORT SIGNAL",
    };
  }

  return null;
}

export function MarketCockpit({
  setup,
  candles,
  analysisData,
  analysisOverlaysReady = true,
  universeMarkets = [],
  activeTimeframe,
  onTimeframeChange,
  onNavigate,
  candlesLoading: _candlesLoading = false,
  isSwitchingTimeframe = false,
  tfError = null,
  signalHistory = [],
  analysisDevParams,
  analysisQueryForApi,
  onAnalysisDevParamsChange,
  onApplyCoreAnalysisParams,
  onResetAnalysisParams,
  onBack,
}: MarketCockpitProps) {
  const [trendStartOverlay, setTrendStartOverlay] = useState<TrendStartOverlayPayload | null>(null);
  const [allTrendTimeframes, setAllTrendTimeframes] = useState<Record<string, TrendStartOverlayPayload> | null>(null);
  const [marketPickerOpen, setMarketPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  const marketPickerRef = useRef<HTMLDivElement | null>(null);
  const [showBOS, setShowBOS] = useState(true);
  const [showCHoCH, setShowCHoCH] = useState(true);
  const [showImpulseLines, setShowImpulseLines] = useState(true);
  const [infoPanelCollapsed, setInfoPanelCollapsed] = useState(false);
  const [globalStructureOpen, setGlobalStructureOpen] = useState(false);
  const [primeImpulseOpen, setPrimeImpulseOpen] = useState(false);
  const [candidateImpulseOpen, setCandidateImpulseOpen] = useState(false);
  const [analysisParamsOpen, setAnalysisParamsOpen] = useState(false);
  const [advancedOverridesOpen, setAdvancedOverridesOpen] = useState(false);
  const [coreDraft, setCoreDraft] = useState<AnalysisCoreParams>(() => pickCoreParams(analysisDevParams));
  const coreCommittedSnapRef = useRef("");
  const [trendWindowStructure, setTrendWindowStructure] = useState<TrendWindowStructure | null>(null);
  const [marketContextOpen, setMarketContextOpen] = useState(true);

  function patchAnalysisDevParams(partial: Partial<AnalysisDevParams>) {
    onAnalysisDevParamsChange({ ...analysisDevParams, ...partial });
  }

  useEffect(() => {
    coreCommittedSnapRef.current = "";
  }, [setup.symbol]);

  useEffect(() => {
    const snap = JSON.stringify(pickCoreParams(analysisDevParams));
    if (snap === coreCommittedSnapRef.current) return;
    coreCommittedSnapRef.current = snap;
    setCoreDraft(pickCoreParams(analysisDevParams));
  }, [analysisDevParams]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("ikenga.marketInfoCollapsed");
      if (stored !== null) {
        setInfoPanelCollapsed(stored === "true");
      }
    } catch {
      // no-op
    }
  }, []);

  const toggleInfoPanel = () => {
    setInfoPanelCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem("ikenga.marketInfoCollapsed", String(next));
      } catch {
        // no-op
      }
      return next;
    });
  };

  useEffect(() => {
    if (!marketPickerOpen) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const el = marketPickerRef.current;
      if (el && !el.contains(e.target as Node)) {
        setMarketPickerOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [marketPickerOpen]);

  useEffect(() => {
    if (!setup.symbol) return;
    const tfs = ["1h", "4h", "1d", "1w", "1mo"];
    if (!tfs.includes(activeTimeframe)) return;
    fetch(`${API_BASE}/api/trend-visual/${setup.symbol}/structure?timeframe=${activeTimeframe}`)
      .then((r) => r.json())
      .then((d: TrendWindowStructure) => {
        if (d.trend) setTrendWindowStructure(d);
        else setTrendWindowStructure(null);
      })
      .catch(() => setTrendWindowStructure(null));
  }, [setup.symbol, activeTimeframe]);

  useEffect(() => {
    if (!setup.symbol) {
      setAllTrendTimeframes(null);
      setTrendStartOverlay(null);
      return;
    }
    setAllTrendTimeframes(null);
    fetch(`${API_BASE}/api/trend-visual/${setup.symbol}`)
      .then((r) => r.json())
      .then((d: { timeframes?: Record<string, TrendStartOverlayPayload> }) => {
        setAllTrendTimeframes(d.timeframes ?? null);
      })
      .catch(() => {
        setAllTrendTimeframes(null);
      });
  }, [setup.symbol]);

  useEffect(() => {
    const tfResult = allTrendTimeframes?.[activeTimeframe];
    if (tfResult?.trend) {
      setTrendStartOverlay(tfResult);
    } else {
      setTrendStartOverlay(null);
    }
  }, [activeTimeframe, allTrendTimeframes]);

  const structuralState = analysisData?.structural_state ?? setup.structural_state_json;
  const structuralLevels = structuralState?.levels ?? [];
  /** Canonical Market View direction: analysis `global_trend` once overlays are ready, else setup until analysis arrives. */
  const trendSourceRaw =
    analysisOverlaysReady && analysisData != null
      ? (analysisData.global_trend ?? setup.trend)
      : setup.trend;
  const canonicalTrend = String(trendSourceRaw ?? "range").toLowerCase();
  const chartTrendProp = canonicalTrend === "down" ? "down" : canonicalTrend === "up" ? "up" : "range";

  const legs = analysisOverlaysReady ? (analysisData?.legs ?? []) : [];
  const bosLevels = analysisOverlaysReady ? (analysisData?.bos_levels ?? []) : [];
  const chochLevel = analysisOverlaysReady ? (analysisData?.choch_level ?? null) : null;
  const globalChochZone = analysisOverlaysReady ? (analysisData?.global_choch_zone ?? null) : null;
  const internalChochZone = analysisOverlaysReady ? (analysisData?.internal_choch_zone ?? null) : null;
  const chochZonesFromAnalysis = analysisOverlaysReady ? (analysisData?.choch_zones ?? []) : [];
  const candidateMove = analysisOverlaysReady ? (analysisData?.candidate_move ?? null) : null;
  const provisionalDeveloping = analysisOverlaysReady
    ? (() => {
        const cm = analysisData?.candidate_move;
        if (
          cm &&
          typeof cm.move_start_timestamp === "string" &&
          typeof cm.pivot_price === "number"
        ) {
          return { start_timestamp: cm.move_start_timestamp, start_price: cm.pivot_price };
        }
        return provisionalDevelopingFromLegs(legs);
      })()
    : null;
  const candidateMoveTealStructure = candidateMove?.teal_structure ?? null;
  /** Prefer GET /api/analysis overlays; avoid duplicating legs/BOS/CHoCH from trend-visual. */
  const trendWindowStructureForChart =
    analysisOverlaysReady && (analysisData?.legs?.length ?? 0) > 0 ? null : trendWindowStructure;

  const isDownTrend = canonicalTrend === "down";
  const isRangeTrend = canonicalTrend !== "up" && canonicalTrend !== "down";
  const zoneMapColor = isRangeTrend ? "#787B86" : isDownTrend ? "#EF5350" : "#26A69A";
  const zoneMapLabel = isRangeTrend ? "RANGE" : isDownTrend ? "DOWN ↓" : "UP ↑";
  const depthValue = analysisData?.max_depth_reached ?? setup.pullback_depth;
  const mitigationValue = analysisData?.total_mitigation_count ?? setup.total_mitigation_count;
  const waitingForText = analysisData?.waiting_for ?? setup.waiting_for;

  const firstConfirmed = firstConfirmedLeg(legs);
  const lastImpulseLeg = lastConfirmedImpulse(legs);
  const refTfRaw = analysisOverlaysReady ? analysisData?.reference_timeframe : undefined;

  const globalPanelDirection =
    canonicalTrend === "up" ? "UP" : canonicalTrend === "down" ? "DOWN" : "—";
  const globalPanelSource = (() => {
    const r = String(refTfRaw ?? "").toLowerCase();
    if (r === "daily") return "DAILY";
    if (r === "weekly") return "WEEKLY";
    return "—";
  })();
  const globalPanelLegCount =
    analysisOverlaysReady ? String(legs.filter((l) => l.confirmed).length) : "—";
  const globalPanelStartPrice =
    analysisOverlaysReady && firstConfirmed != null ? formatPrice(firstConfirmed.start_price) : "—";
  const globalPanelFromDate =
    analysisOverlaysReady ? formatTrendDateUtc(firstConfirmed?.start_timestamp ?? null) : "—";
  const currentExtremeLabel =
    canonicalTrend === "up" ? "IMPULSE HIGH" : canonicalTrend === "down" ? "IMPULSE LOW" : "IMPULSE";
  const globalPanelCurrentExtreme =
    analysisOverlaysReady && lastImpulseLeg?.end_price != null
      ? formatPrice(lastImpulseLeg.end_price)
      : "—";
  const globalPanelChoch =
    analysisOverlaysReady &&
    globalChochZone &&
    typeof globalChochZone.lower_boundary === "number" &&
    typeof globalChochZone.upper_boundary === "number"
      ? `${formatPrice(globalChochZone.lower_boundary)} — ${formatPrice(globalChochZone.upper_boundary)}`
      : "—";
  const globalPanelBos =
    analysisOverlaysReady && lastImpulseLeg?.end_price != null
      ? formatPrice(lastImpulseLeg.end_price)
      : "—";

  const primeResolvedOn =
    analysisOverlaysReady && lastImpulseLeg?.internal_tf_used
      ? timeframeLabel(String(lastImpulseLeg.internal_tf_used).toLowerCase())
      : "—";
  const primeInternalLegsDisplay =
    !analysisOverlaysReady || !lastImpulseLeg
      ? "—"
      : String(lastImpulseLeg.internal_legs?.filter((il) => il.confirmed).length ?? 0);
  const primeRange =
    analysisOverlaysReady &&
    lastImpulseLeg &&
    typeof lastImpulseLeg.start_price === "number" &&
    lastImpulseLeg.end_price != null
      ? `${formatPrice(lastImpulseLeg.start_price)} — ${formatPrice(lastImpulseLeg.end_price)}`
      : "—";
  const primeIchoch =
    analysisOverlaysReady &&
    internalChochZone &&
    typeof internalChochZone.lower_boundary === "number" &&
    typeof internalChochZone.upper_boundary === "number"
      ? `${formatPrice(internalChochZone.lower_boundary)} — ${formatPrice(internalChochZone.upper_boundary)}`
      : "—";

  const candState = candidateMove != null ? "ACTIVE" : "NONE";
  const candFrom =
    candidateMove != null && typeof candidateMove.pivot_price === "number"
      ? formatPrice(candidateMove.pivot_price)
      : "—";
  const candTargetBos =
    candidateMove != null && candidateMove.reference_bos_price != null
      ? formatPrice(candidateMove.reference_bos_price)
      : "—";
  const candBroken =
    candidateMove?.structure_broken === true
      ? "YES"
      : candidateMove?.structure_broken === false
        ? "NO"
        : "—";
  const candTealIchoch = candidateMove?.teal_structure?.internal_choch_zone;
  const candIchoch =
    candTealIchoch &&
    typeof candTealIchoch.lower_boundary === "number" &&
    typeof candTealIchoch.upper_boundary === "number"
      ? `${formatPrice(candTealIchoch.lower_boundary)} — ${formatPrice(candTealIchoch.upper_boundary)}`
      : "—";

  const candIchochReachedText =
    candidateMove?.candidate_ichoch_reached === true
      ? "YES"
      : candidateMove?.candidate_ichoch_reached === false
        ? "NO"
        : "—";
  const candIchochReachedColor =
    candidateMove?.candidate_ichoch_reached === true
      ? "#F5A623"
      : candidateMove?.candidate_ichoch_reached === false
        ? "#787B86"
        : "#D1D4DC";
  const candNewMoveText =
    candidateMove?.candidate_new_move_active === true ? "ACTIVE" : "WAITING";
  const candNewMoveColor =
    candidateMove?.candidate_new_move_active === true ? "#F5A623" : "#787B86";

  const panelRowLabel: CSSProperties = {
    fontSize: 9,
    color: "#787B86",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  };
  const panelRowValue: CSSProperties = {
    fontSize: 11,
    fontWeight: 700,
    color: "#D1D4DC",
    textAlign: "right" as const,
  };

  const universeDeduped = dedupeUniverseBySymbol(universeMarkets);
  const pickerQuery = pickerSearch.trim().toUpperCase();
  const filteredUniverse = pickerQuery
    ? universeDeduped.filter((u) => String(u.symbol).toUpperCase().includes(pickerQuery))
    : universeDeduped;
  const groupedByCategory: Record<MarketCategoryGroup, Setup[]> = {
    crypto: [],
    forex: [],
    synthetic: [],
    commodity: [],
    other: [],
  };
  for (const row of filteredUniverse) {
    groupedByCategory[marketCategoryGroup(row.category)].push(row);
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        height: "100%",
        padding: 10,
        background: "#0D0F14",
        color: "#D1D4DC",
        fontFamily: '"IBM Plex Mono", monospace',
      }}
    >
      <div ref={marketPickerRef} style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid #1C1E24", background: "#111318", padding: "6px 8px", position: "relative" }}>
        <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.1em", textTransform: "uppercase" }}>Market</span>
        <Tooltip content="Open market picker">
          <button
            type="button"
            onClick={() => {
              setMarketPickerOpen((o) => !o);
              if (!marketPickerOpen) setPickerSearch("");
            }}
            style={{
              minWidth: 140,
              fontSize: 11,
              background: "#0B0D11",
              border: "1px solid #1E222D",
              color: "#D1D4DC",
              padding: "6px 10px",
              fontFamily: '"IBM Plex Mono", monospace',
              cursor: "pointer",
              textAlign: "left",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
            }}
          >
            <span style={{ fontWeight: 700 }}>{setup.symbol}</span>
            <span style={{ fontSize: 9, color: "#787B86" }}>{marketPickerOpen ? "▲" : "▼"}</span>
          </button>
        </Tooltip>
        {marketPickerOpen ? (
          <div
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              marginTop: 4,
              width: 320,
              maxHeight: 420,
              border: "1px solid #1C1E24",
              background: "#111318",
              zIndex: 20,
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
            }}
          >
            <div style={{ padding: 8, borderBottom: "1px solid #1C1E24" }}>
              <input
                type="text"
                placeholder="Filter symbols..."
                value={pickerSearch}
                onChange={(e) => setPickerSearch(e.target.value)}
                autoFocus
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  fontSize: 11,
                  background: "#0B0D11",
                  border: "1px solid #1E222D",
                  color: "#D1D4DC",
                  padding: "6px 10px",
                  fontFamily: '"IBM Plex Mono", monospace',
                  outline: "none",
                }}
              />
            </div>
            <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
              {universeDeduped.length === 0 ? (
                <div style={{ padding: 12, fontSize: 10, color: "#787B86" }}>Loading universe…</div>
              ) : filteredUniverse.length === 0 ? (
                <div style={{ padding: 12, fontSize: 10, color: "#787B86" }}>No matches</div>
              ) : (
                MARKET_CATEGORY_GROUPS.map((groupKey) => {
                  const rows = groupedByCategory[groupKey];
                  if (rows.length === 0) return null;
                  return (
                    <div key={groupKey}>
                      <div
                        style={{
                          position: "sticky",
                          top: 0,
                          padding: "6px 10px",
                          fontSize: 9,
                          letterSpacing: "0.12em",
                          color: "#F5A623",
                          textTransform: "uppercase",
                          background: "#0D0F14",
                          borderBottom: "1px solid #1C1E24",
                        }}
                      >
                        {GROUP_HEADING[groupKey]}
                      </div>
                      {rows.map((row) => {
                        const sym = String(row.symbol).toUpperCase();
                        const active = sym === String(setup.symbol).toUpperCase();
                        return (
                          <button
                            key={sym}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                              setMarketPickerOpen(false);
                              setPickerSearch("");
                              onNavigate(sym);
                            }}
                            style={{
                              width: "100%",
                              padding: "8px 10px",
                              textAlign: "left",
                              border: "none",
                              borderBottom: "1px solid #1C1E24",
                              background: active ? "rgba(245,166,35,0.12)" : "transparent",
                              color: active ? "#F5A623" : "#D1D4DC",
                              fontSize: 11,
                              cursor: "pointer",
                              fontFamily: '"IBM Plex Mono", monospace',
                            }}
                          >
                            {sym}
                            <span style={{ marginLeft: 8, fontSize: 9, color: "#787B86" }}>{row.category}</span>
                          </button>
                        );
                      })}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        ) : null}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: infoPanelCollapsed ? "minmax(0, 1fr)" : "minmax(0, 3fr) minmax(360px, 2fr)",
          gap: 16,
          minHeight: 0,
          flex: 1,
          transition: "grid-template-columns 220ms ease",
        }}
      >
      <section style={{ display: "flex", minHeight: 0, flexDirection: "column", border: "1px solid #1C1E24", background: "#111318", position: "relative" }}>
        <Tooltip content={infoPanelCollapsed ? "Show info panel" : "Hide info panel"}>
          <span style={{ position: "absolute", right: -12, top: 12, zIndex: 20 }}>
            <PanelEdgeCollapseToggle
              variant="vertical"
              expanded={!infoPanelCollapsed}
              onClick={toggleInfoPanel}
              aria-label={infoPanelCollapsed ? "Show info panel" : "Hide info panel"}
              title={infoPanelCollapsed ? "Show info panel" : "Hide info panel"}
            />
          </span>
        </Tooltip>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #1C1E24", padding: "8px 12px" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.04em", color: "#D1D4DC" }}>{setup.symbol}</div>
            <div style={{ marginTop: 4, fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>
              {setup.category} · {activeTimeframe} · {setup.broker}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>Zone Map</div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <Tooltip content="Toggle BOS overlays">
                  <button
                    type="button"
                    onClick={() => setShowBOS((prev) => !prev)}
                    style={{
                      fontSize: 8,
                      padding: "2px 6px",
                      border: "1px solid #1E222D",
                      background: showBOS ? "#1E222D" : "transparent",
                      color: showBOS ? "#D1D4DC" : "#2A2E39",
                      cursor: "pointer",
                      textTransform: "uppercase",
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}
                  >
                    BOS
                  </button>
                </Tooltip>
                <Tooltip content="Toggle CHoCH overlays">
                  <button
                    type="button"
                    onClick={() => setShowCHoCH((prev) => !prev)}
                    style={{
                      fontSize: 8,
                      padding: "2px 6px",
                      border: "1px solid #1E222D",
                      background: showCHoCH ? "#1E222D" : "transparent",
                      color: showCHoCH ? "#D1D4DC" : "#2A2E39",
                      cursor: "pointer",
                      textTransform: "uppercase",
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}
                  >
                    CHoCH
                  </button>
                </Tooltip>
                <Tooltip content="Toggle trend leg lines">
                  <button
                    type="button"
                    onClick={() => setShowImpulseLines((prev) => !prev)}
                    style={{
                      fontSize: 8,
                      padding: "2px 6px",
                      border: "1px solid #1E222D",
                      background: showImpulseLines ? "#1E222D" : "transparent",
                      color: showImpulseLines ? "#D1D4DC" : "#2A2E39",
                      cursor: "pointer",
                      textTransform: "uppercase",
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}
                  >
                    LINES
                  </button>
                </Tooltip>
              </div>
            </div>
            <div style={{ marginTop: 4, fontSize: 13, fontWeight: 700, color: zoneMapColor }}>
              {zoneMapLabel}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", padding: "6px 16px", borderBottom: "1px solid #1C1E24", gap: 4 }}>
          {TIMEFRAMES.map((tf) => {
            const isActive = activeTimeframe === tf;
            return (
              <Tooltip key={tf} content={`Switch to ${timeframeLabel(tf)} timeframe`}>
                <button
                  type="button"
                  style={{
                    padding: "3px 8px",
                    fontSize: 10,
                    fontFamily: '"IBM Plex Mono", monospace',
                    letterSpacing: "0.06em",
                    background: isActive ? "#F5A623" : "transparent",
                    color: isActive ? "#0D0F14" : "#4A4D58",
                    border: isActive ? "1px solid #F5A623" : "1px solid #1C1E24",
                    borderRadius: 2,
                    cursor: "pointer",
                  }}
                  onClick={() => onTimeframeChange(tf)}
                >
                  {timeframeLabel(tf)}
                </button>
              </Tooltip>
            );
          })}
        </div>
        {tfError ? (
          <div style={{ padding: "0 16px 6px", fontSize: 9, color: "#EF5350" }}>{tfError}</div>
        ) : null}

        <div
          style={{
            flex: 1,
            minHeight: 0,
            padding: 16,
            position: "relative",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              aria-label="Back"
              onMouseEnter={(e) => {
                e.currentTarget.style.color = "#D1D4DC";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "#787B86";
              }}
              style={{
                alignSelf: "flex-start",
                marginBottom: 8,
                padding: 0,
                border: "none",
                background: "transparent",
                fontFamily: '"IBM Plex Mono", monospace',
                fontSize: 10,
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "#787B86",
                cursor: "pointer",
              }}
            >
              ← BACK
            </button>
          ) : null}
          <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
            {isSwitchingTimeframe && (
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  right: 0,
                  height: 2,
                  overflow: "hidden",
                  pointerEvents: "none",
                  zIndex: 8,
                }}
              >
                <div
                  style={{
                    width: "40%",
                    height: "100%",
                    background: "linear-gradient(90deg, transparent, #F5A623, transparent)",
                    animation: "tf-loading 0.8s ease-in-out infinite",
                  }}
                />
              </div>
            )}
            <CandleChart
              candles={candles}
              trend={chartTrendProp}
              legs={legs}
              bosLevels={bosLevels}
              chochLevel={chochLevel}
              chochZones={chochZonesFromAnalysis}
              globalChochZone={globalChochZone}
              internalChochZone={internalChochZone}
              candidateMoveTealStructure={candidateMoveTealStructure}
              provisionalDeveloping={provisionalDeveloping}
              trendStartOverlay={analysisOverlaysReady ? trendStartOverlay : null}
              trendWindowStructure={analysisOverlaysReady ? trendWindowStructureForChart : null}
              showBOS={showBOS}
              showCHoCH={showCHoCH}
              showLines={showImpulseLines}
              showAnalysisOverlays={analysisOverlaysReady}
              isSwitchingTimeframe={isSwitchingTimeframe}
            />
          </div>
        </div>
      </section>

      <aside
        style={{
          display: infoPanelCollapsed ? "none" : "flex",
          minHeight: 0,
          flexDirection: "column",
          gap: 8,
          overflowY: "auto",
          opacity: infoPanelCollapsed ? 0 : 1,
          transform: infoPanelCollapsed ? "translateX(10px)" : "translateX(0)",
          transition: "opacity 220ms ease, transform 220ms ease",
        }}
      >
        {/* MARKET CONTEXT */}
        <section
          style={{
            border: "1px solid #2A2E39",
            background: "#0E1014",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setMarketContextOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "#787B86",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>MARKET CONTEXT</span>
            <span style={{ color: "#434651" }}>{marketContextOpen ? "−" : "+"}</span>
          </button>
          {marketContextOpen && (
            <div
              style={{
                borderTop: "1px solid #2A2E39",
                padding: "10px 12px 14px",
              }}
            >
              <MarketContextPanel symbol={setup.symbol} />
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Trend Summary</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Trend</div>
              <ValueText color={trendColor(canonicalTrend)}>{canonicalTrend.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Phase</div>
              <ValueText color={phaseTone(setup.current_phase)}>{setup.current_phase.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>FSM State</div>
              <ValueText>{setup.fsm_state}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Score</div>
              <ValueText>{formatScore(setup.trend_score)}</ValueText>
            </div>
            {candidateMove != null && candidateMove.structure_broken != null ? (
              <div style={{ gridColumn: "1 / -1" }}>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    color: "#787B86",
                    textTransform: "uppercase",
                  }}
                >
                  Candidate move vs ref BOS
                </div>
                <ValueText
                  color={
                    candidateMove.structure_broken ? "#EF5350" : STRUCTURE_CANDIDATE_MOVE
                  }
                >
                  {candidateMove.structure_broken ? "STRUCTURE BROKEN" : "HOLDING"}
                </ValueText>
              </div>
            ) : null}
          </div>
        </section>

        <section
          style={{
            border: "1px solid #2A2E39",
            background: "#0E1014",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setGlobalStructureOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "#787B86",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>GLOBAL STRUCTURE</span>
            <span style={{ color: "#434651" }}>{globalStructureOpen ? "−" : "+"}</span>
          </button>
          {globalStructureOpen && (
            <div
              style={{
                borderTop: "1px solid #2A2E39",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 8,
                color: "#9CA3AF",
              }}
            >
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>DIRECTION</span>
                <span style={panelRowValue}>{globalPanelDirection}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>SOURCE</span>
                <span style={panelRowValue}>{globalPanelSource}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>LEGS</span>
                <span style={panelRowValue}>{globalPanelLegCount}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>START</span>
                <span style={panelRowValue}>{globalPanelStartPrice}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>FROM</span>
                <span style={panelRowValue}>{globalPanelFromDate}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>{currentExtremeLabel}</span>
                <span style={panelRowValue}>{globalPanelCurrentExtreme}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>CHOCH</span>
                <span style={panelRowValue}>{globalPanelChoch}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>PRIME HIGH</span>
                <span style={panelRowValue}>{globalPanelBos}</span>
              </div>
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Retracement Analysis</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                <span style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Layers confirmed</span>
                <span style={{ fontSize: 7, color: "#2A2E39" }}>internal structural layers inside retracement</span>
              </div>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#D1D4DC", flexShrink: 0 }}>{depthValue}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Mitigations</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>{mitigationValue}</span>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Waiting For</div>
              <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.6, color: "#D1D4DC" }}>{waitingForText}</div>
            </div>
          </div>
        </section>

        <section
          style={{
            border: "1px solid #2A2E39",
            background: "#0E1014",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setPrimeImpulseOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "#787B86",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>PRIME IMPULSE</span>
            <span style={{ color: "#434651" }}>{primeImpulseOpen ? "−" : "+"}</span>
          </button>
          {primeImpulseOpen && (
            <div
              style={{
                borderTop: "1px solid #2A2E39",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 8,
                color: "#9CA3AF",
              }}
            >
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>RESOLVED ON</span>
                <span style={panelRowValue}>{primeResolvedOn}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>INTERNAL LEGS</span>
                <span style={panelRowValue}>{primeInternalLegsDisplay}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>FROM — TO</span>
                <span style={panelRowValue}>{primeRange}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>ICHOCH</span>
                <span style={panelRowValue}>{primeIchoch}</span>
              </div>
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Structural Layers</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {structuralLevels.map((level, index) => {
              const levelLower = level.choch_zone?.lower_boundary;
              const levelUpper = level.choch_zone?.upper_boundary;
              const activeLower = setup.active_choch_zone?.lower_boundary;
              const activeUpper = setup.active_choch_zone?.upper_boundary;
              const isActiveLevel =
                typeof levelLower === "number" &&
                typeof levelUpper === "number" &&
                levelLower === activeLower &&
                levelUpper === activeUpper;

              const depthColor = level.depth === 1
                ? "#3A6BFF"
                : level.depth === 2
                  ? "#4CAF7D"
                  : level.depth === 3
                    ? "#9B59B6"
                    : "#D1D4DC";

              return (
                <div
                  key={`depth-level-${level.depth}-${index}`}
                  style={{
                    border: "1px solid #1C1E24",
                    borderLeft: isActiveLevel ? "3px solid #F5A623" : "1px solid #1C1E24",
                    background: "#131722",
                    padding: 12,
                    boxShadow: isActiveLevel ? "0 0 12px rgba(245,166,35,0.25)" : "none",
                    animation: isActiveLevel ? "border-pulse-amber 3s ease-in-out infinite" : undefined,
                    position: "relative",
                    overflow: "hidden",
                  }}
                >
                  {isActiveLevel && (
                    <div
                      style={{
                        position: "absolute",
                        top: 8,
                        right: 8,
                        fontSize: 8,
                        color: "#F5A623",
                        letterSpacing: "0.14em",
                      }}
                    >
                      ACTIVE
                    </div>
                  )}
                  {!isActiveLevel && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: 0,
                        bottom: 0,
                        width: 2,
                        background: depthColor,
                        opacity: 0.3,
                      }}
                    />
                  )}
                  <div style={{ fontSize: 11, fontWeight: 700, color: depthColor, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    DEPTH {level.depth}
                  </div>
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 8,
                      color: "#2A2E39",
                      fontStyle: "italic",
                      lineHeight: 1.35,
                    }}
                  >
                    {structuralLayerDescription(level.depth)}
                  </div>

                  <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>CHoCH Zone</div>
                      <div style={{ marginTop: 4, fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>
                        {typeof levelLower === "number" && typeof levelUpper === "number"
                          ? `${formatPrice(levelLower)} - ${formatPrice(levelUpper)}`
                          : "N/A"}
                      </div>
                    </div>

                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>BOS Structural Level</div>
                      <div style={{ marginTop: 4, fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>
                        {typeof level.structural_level?.price === "number" ? formatPrice(level.structural_level.price) : "N/A"}
                      </div>
                    </div>

                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Termination</div>
                      <div style={{ marginTop: 4, fontSize: 11, color: "#787B86" }}>
                        {level.termination_reason || "N/A"}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            {structuralLevels.length === 0 && (
              <div
                style={{
                  border: "1px solid #1C1E24",
                  background: "#131722",
                  padding: 20,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                }}
              >
                <div style={{ fontSize: 20, color: "#2A2E39", lineHeight: 1 }}>-</div>
                <div style={{ fontSize: 9, color: "#2A2E39", letterSpacing: "0.14em" }}>NO STRUCTURAL DATA</div>
                <div style={{ fontSize: 9, color: "#1E222D" }}>MARKET IN IMPULSE PHASE</div>
              </div>
            )}
            <div style={{ border: "1px solid #1C1E24", background: "#131722", padding: 12 }}>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Break Type</div>
              <div style={{ marginTop: 8 }}>
                <span style={{ background: "#2A2E39", color: "#D1D4DC", border: "1px solid #363A45", padding: "4px 8px", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                  {structureBadgeLabel(setup)}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section
          style={{
            border: "1px solid #2A2E39",
            background: "#0E1014",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setCandidateImpulseOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "#787B86",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>CANDIDATE IMPULSE</span>
            <span style={{ color: "#434651" }}>{candidateImpulseOpen ? "−" : "+"}</span>
          </button>
          {candidateImpulseOpen && (
            <div
              style={{
                borderTop: "1px solid #2A2E39",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 8,
                color: "#9CA3AF",
              }}
            >
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>STATE</span>
                <span style={panelRowValue}>{candState}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>FROM</span>
                <span style={panelRowValue}>{candFrom}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>TARGET BOS</span>
                <span style={panelRowValue}>{candTargetBos}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>BOS BROKEN</span>
                <span style={panelRowValue}>{candBroken}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>ICHOCH</span>
                <span style={panelRowValue}>{candIchoch}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>ICHOCH REACHED</span>
                <span style={{ ...panelRowValue, color: candIchochReachedColor }}>{candIchochReachedText}</span>
              </div>
              {/* TODO: editable in next phase */}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>NEW MOVE</span>
                <span style={{ ...panelRowValue, color: candNewMoveColor }}>{candNewMoveText}</span>
              </div>
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>EMA Status</SectionLabel>
          {renderEmaStatus(setup) ? (
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: renderEmaStatus(setup)?.color,
                  animation: "live-pulse 1.5s ease-in-out infinite",
                  flexShrink: 0,
                }}
              />
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: renderEmaStatus(setup)?.color,
                }}
              >
                {renderEmaStatus(setup)?.text}
              </div>
            </div>
          ) : (
            <div style={{ marginTop: 12, display: "grid", gap: 6 }}>
              <div style={{ fontSize: 11, color: "#4A4D58" }}>Watching for EMA 9 / EMA 21 crossover</div>
              <div style={{ fontSize: 10, color: "#3A3D48" }}>Conditions: depth ≥ 1, active CHoCH zone</div>
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Signal History</SectionLabel>
          {signalHistory.length === 0 ? (
            <div style={{ marginTop: 12, fontSize: 10, color: "#434651" }}>No historical signals yet.</div>
          ) : (
            <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
              {signalHistory.slice(0, 8).map((item) => {
                const isLong = String(item.signal).toUpperCase() === "LONG";
                const tone = isLong ? "#4CAF7D" : "#E05A5A";
                const timestamp = item.emitted_at ? new Date(item.emitted_at).toUTCString().slice(5, 22) : "N/A";
                return (
                  <div
                    key={item.id}
                    style={{
                      border: "1px solid #1C1E24",
                      background: "#131722",
                      padding: "6px 8px",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 10,
                    }}
                  >
                    <div style={{ fontSize: 10, color: tone, fontWeight: 700 }}>{item.signal}</div>
                    <div style={{ fontSize: 9, color: "#787B86" }}>{item.timeframe.toUpperCase()}</div>
                    <div style={{ fontSize: 9, color: "#434651", marginLeft: "auto" }}>{timestamp} UTC</div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section
          style={{
            border: "1px solid #2A2E39",
            background: "#0E1014",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setAnalysisParamsOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "#787B86",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>ANALYSIS PARAMETERS</span>
            <span style={{ color: "#434651" }}>{analysisParamsOpen ? "−" : "+"}</span>
          </button>
          {analysisParamsOpen && (
            <div
              style={{
                borderTop: "1px solid #2A2E39",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 10,
                color: "#9CA3AF",
              }}
            >
              <div style={{ fontSize: 9, color: "#434651", lineHeight: 1.4 }}>
                Overrides for GET /api/analysis for this symbol. Apply to refetch overlays; values persist in this browser.
              </div>
              <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span>Parent relative filter</span>
                <input
                  type="checkbox"
                  checked={coreDraft.use_parent_relative_filter}
                  onChange={(e) =>
                    setCoreDraft((d) => ({ ...d, use_parent_relative_filter: e.target.checked }))
                  }
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 9, color: "#434651" }}>Min impulse parent ratio</span>
                <input
                  type="number"
                  step={0.01}
                  min={0.001}
                  max={5}
                  value={coreDraft.min_impulse_parent_ratio}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) setCoreDraft((d) => ({ ...d, min_impulse_parent_ratio: v }));
                  }}
                  style={algoInputStyle}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span>Momentum filter</span>
                <input
                  type="checkbox"
                  checked={coreDraft.use_momentum_filter}
                  onChange={(e) =>
                    setCoreDraft((d) => ({ ...d, use_momentum_filter: e.target.checked }))
                  }
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 9, color: "#434651" }}>Min momentum ratio</span>
                <input
                  type="number"
                  step={0.1}
                  min={0.001}
                  max={5}
                  value={coreDraft.min_momentum_ratio}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) setCoreDraft((d) => ({ ...d, min_momentum_ratio: v }));
                  }}
                  style={algoInputStyle}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <span>Dominance filter</span>
                <input
                  type="checkbox"
                  checked={coreDraft.use_dominance_filter}
                  onChange={(e) =>
                    setCoreDraft((d) => ({ ...d, use_dominance_filter: e.target.checked }))
                  }
                />
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 9, color: "#434651" }}>Min dominance ratio</span>
                <input
                  type="number"
                  step={0.1}
                  min={0.001}
                  max={5}
                  value={coreDraft.min_dominance_ratio}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) setCoreDraft((d) => ({ ...d, min_dominance_ratio: v }));
                  }}
                  style={algoInputStyle}
                />
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => onApplyCoreAnalysisParams(coreDraft)}
                  style={{
                    padding: "6px 12px",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    background: "#F5A623",
                    border: "1px solid #F5A623",
                    color: "#0B0D11",
                    cursor: "pointer",
                    fontFamily: '"IBM Plex Mono", monospace',
                    fontWeight: 700,
                  }}
                >
                  APPLY
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onResetAnalysisParams();
                  }}
                  style={{
                    padding: "6px 12px",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    background: "#1E222D",
                    border: "1px solid #363A45",
                    color: "#D1D4DC",
                    cursor: "pointer",
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  RESET TO DEFAULTS
                </button>
              </div>

              <button
                type="button"
                onClick={() => setAdvancedOverridesOpen((o) => !o)}
                style={{
                  marginTop: 4,
                  width: "100%",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "8px 0 0",
                  background: "transparent",
                  border: "none",
                  borderTop: "1px solid #2A2E39",
                  color: "#434651",
                  cursor: "pointer",
                  fontSize: 9,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  fontFamily: '"IBM Plex Mono", monospace',
                }}
              >
                <span>Additional analysis overrides</span>
                <span>{advancedOverridesOpen ? "−" : "+"}</span>
              </button>
              {advancedOverridesOpen && (
                <div style={{ display: "grid", gap: 10, paddingTop: 8 }}>
                  <div style={{ fontSize: 9, color: "#434651", lineHeight: 1.4 }}>
                    Changing a value refetches overlays immediately (candles unchanged).
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontSize: 9, color: "#434651" }}>max_walk_depth (omit if empty)</span>
                      <input
                        type="number"
                        step={1}
                        min={1}
                        max={10}
                        value={analysisDevParams.max_walk_depth ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value.trim();
                          if (raw === "") patchAnalysisDevParams({ max_walk_depth: null });
                          else {
                            const v = parseInt(raw, 10);
                            if (!Number.isNaN(v)) patchAnalysisDevParams({ max_walk_depth: v });
                          }
                        }}
                        style={algoInputStyle}
                      />
                    </label>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontSize: 9, color: "#434651" }}>min_swing_candles (optional)</span>
                      <input
                        type="number"
                        step={1}
                        min={1}
                        max={20}
                        value={analysisDevParams.min_swing_candles ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value.trim();
                          if (raw === "") patchAnalysisDevParams({ min_swing_candles: null });
                          else {
                            const v = parseInt(raw, 10);
                            if (!Number.isNaN(v)) patchAnalysisDevParams({ min_swing_candles: v });
                          }
                        }}
                        style={algoInputStyle}
                      />
                    </label>
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontSize: 9, color: "#434651" }}>trend_confirmation_pct (optional)</span>
                      <input
                        type="number"
                        step={0.001}
                        min={0.0001}
                        max={0.5}
                        value={analysisDevParams.trend_confirmation_pct ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value.trim();
                          if (raw === "") patchAnalysisDevParams({ trend_confirmation_pct: null });
                          else {
                            const v = parseFloat(raw);
                            if (!Number.isNaN(v)) patchAnalysisDevParams({ trend_confirmation_pct: v });
                          }
                        }}
                        style={algoInputStyle}
                      />
                    </label>
                  </div>
                  <div style={{ fontSize: 9, color: "#434651", letterSpacing: "0.06em" }}>RMT subtree (optional)</div>
                  <div style={{ display: "grid", gap: 8 }}>
                    {(
                      [
                        ["rmt_use_parent_relative_filter", "RMT parent-relative"] as const,
                        ["rmt_use_momentum_filter", "RMT momentum"] as const,
                        ["rmt_use_dominance_filter", "RMT dominance"] as const,
                      ] as const
                    ).map(([key, label]) => {
                      const tri = analysisDevParams[key];
                      return (
                        <label
                          key={key}
                          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}
                        >
                          <span>{label}</span>
                          <select
                            value={tri === null ? "default" : tri ? "on" : "off"}
                            onChange={(e) => {
                              const v = e.target.value;
                              patchAnalysisDevParams({
                                [key]: v === "default" ? null : v === "on",
                              } as Partial<AnalysisDevParams>);
                            }}
                            style={{ ...algoInputStyle, maxWidth: 120 }}
                          >
                            <option value="default">default</option>
                            <option value="on">on</option>
                            <option value="off">off</option>
                          </select>
                        </label>
                      );
                    })}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    {(
                      [
                        ["rmt_min_impulse_parent_ratio", "rmt_min_impulse_parent_ratio"] as const,
                        ["rmt_min_momentum_ratio", "rmt_min_momentum_ratio"] as const,
                        ["rmt_min_dominance_ratio", "rmt_min_dominance_ratio"] as const,
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ fontSize: 8, color: "#434651" }}>{label}</span>
                        <input
                          type="number"
                          step={0.01}
                          min={0.001}
                          max={5}
                          value={analysisDevParams[key] ?? ""}
                          onChange={(e) => {
                            const raw = e.target.value.trim();
                            if (raw === "") patchAnalysisDevParams({ [key]: null } as Partial<AnalysisDevParams>);
                            else {
                              const v = parseFloat(raw);
                              if (!Number.isNaN(v)) patchAnalysisDevParams({ [key]: v } as Partial<AnalysisDevParams>);
                            }
                          }}
                          style={algoInputStyle}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      </aside>
      </div>
    </div>
  );
}