"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import {
  pickCoreParams,
  type AnalysisCoreParams,
} from "@/lib/analysis-params-storage";
import { formatScore } from "@/lib/format-display";
import { MarketStateBadge } from "@/components/market-state-badge";
import { PanelEdgeCollapseToggle } from "@/components/ui/panel-edge-collapse-toggle";
import { Tooltip } from "@/components/ui/tooltip";
import type {
  AnalysisDevParams,
  AnalysisResponse,
  CandleBar,
  LayerCacheTimestamps,
  ManualRecomputeLayer,
  ManualOverride,
  Setup,
  SignalHistoryItem,
  TrendLeg,
  TrendWindowStructure,
  WalkerLevel,
} from "@/lib/types";
import { api } from "@/lib/api";
import { STRUCTURE_CANDIDATE_MOVE } from "@/lib/structure-colors";
import { MarketContextPanel } from "@/components/market-context-panel";

const CandleChart = dynamic(() => import("@/components/candle-chart"), { ssr: false });

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface MarketCockpitProps {
  setup: Setup;
  candles: CandleBar[];
  analysisData?: AnalysisResponse;
  onAnalysisDataChange?: (next: AnalysisResponse | null) => void;
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
  onResetServerDefaults: () => void;
  isRecomputingParams?: boolean;
  /** Back control above chart; omitted on empty market route. */
  onBack?: () => void;
}

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"] as const;

const WALKER_DEPTH_COLORS: Record<number, string> = {
  1: "#2196F3",
  2: "#4CAF50",
  3: "#9C27B0",
};

const algoInputStyle: CSSProperties = {
  background: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  color: "var(--text-primary)",
  padding: "6px 8px",
  fontSize: 11,
  fontFamily: '"IBM Plex Mono", monospace',
};

const trendDetectionTooltipText = {
  parent: "Requires each impulse to be at least this fraction of the total chart range. Higher values ignore small moves. Default: 0.15 (15% of total range).",
  momentum:
    "Requires each impulse to be at least this fraction of the size of the previous impulse. Prevents the system from treating a weakening trend as a continuation. Default: 0.5 (each impulse must be 50% as large as the last).",
  dominance:
    "Requires each impulse to be larger than the retracement that came before it by this multiplier. Ensures the trend is genuinely directional. Default: 1.5 (impulse must be 1.5x the prior retracement).",
} as const;

const trendToggleButtonBase: CSSProperties = {
  padding: "4px 12px",
  fontSize: 10,
  letterSpacing: "0.08em",
  fontFamily: '"IBM Plex Mono", monospace',
  borderRadius: 0,
  cursor: "pointer",
  textTransform: "uppercase",
};

const trendQuestionIconStyle: CSSProperties = {
  width: 14,
  height: 14,
  borderRadius: "50%",
  border: "1px solid var(--border-strong)",
  color: "#9CA3AF",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 9,
  lineHeight: 1,
  cursor: "help",
  flexShrink: 0,
};

type TrendStartOverlayPayload = {
  start_timestamp: string;
  start_price: number;
  current_timestamp: string;
  current_price: number;
  trend: string;
};

const STATE_BASE_SCORES: Record<string, number> = {
  WAITING: 5,
  RETRACEMENT: 25,
  DEPTH_BUILDING: 30,
  CHOCH_ZONE_ACTIVE: 35,
  CHOCH_TESTED: 40,
  CANDIDATE_ACTIVE: 45,
  CANDIDATE_CHOCH_TESTED: 48,
  ENTRY_ZONE: 50,
  CANDIDATE_CONFIRMED: 20,
  STRUCTURE_BROKEN: 5,
};

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
  return "var(--text-dim)";
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
  return phase === "retracement" ? "#F5A623" : "var(--text-dim)";
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--text-dim)", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function ValueText({ children, color = "var(--text-primary)" }: { children: React.ReactNode; color?: string }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 700, color, fontFamily: '"IBM Plex Mono", monospace' }}>{children}</div>
  );
}

function TrendDetectionLabel({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
      <span>{label}</span>
      <Tooltip
        content={tooltip}
        multiline
        bubbleStyle={{
          whiteSpace: "normal",
          minWidth: 200,
          maxWidth: 280,
          wordWrap: "break-word",
        }}
      >
        <span aria-label={`${label} explanation`} style={trendQuestionIconStyle}>
          ?
        </span>
      </Tooltip>
    </div>
  );
}

function OverrideForm({
  overrideType,
  existing,
  onSave,
  onReset,
  onClose,
  saving,
}: {
  overrideType: string;
  existing?: ManualOverride | null;
  onSave: (data: Partial<ManualOverride>) => void;
  onReset: () => void;
  onClose: () => void;
  saving: boolean;
}) {
  const isTrendBounds = overrideType === "trend_bounds";
  const [lower, setLower] = useState(
    existing?.lower_boundary != null ? String(existing.lower_boundary) : "",
  );
  const [upper, setUpper] = useState(
    existing?.upper_boundary != null ? String(existing.upper_boundary) : "",
  );
  const [trendStart, setTrendStart] = useState(
    existing?.trend_start_timestamp?.slice(0, 10) ?? "",
  );
  const [trendEnd, setTrendEnd] = useState(
    existing?.trend_end_timestamp?.slice(0, 10) ?? "",
  );
  const [notes, setNotes] = useState(existing?.notes ?? "");

  const inputStyle: CSSProperties = {
    background: "var(--bg-base)",
    border: "1px solid var(--border-default)",
    color: "var(--text-primary)",
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: 10,
    padding: "4px 6px",
    width: "100%",
    borderRadius: 2,
    outline: "none",
    marginBottom: 4,
    boxSizing: "border-box",
  };

  const labelStyle: CSSProperties = {
    fontFamily: "'IBM Plex Mono', monospace",
    fontSize: 8,
    color: "var(--text-muted)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    display: "block",
    marginBottom: 2,
    marginTop: 6,
  };

  const handleSubmit = () => {
    const payload: Partial<ManualOverride> = {
      override_type: overrideType as ManualOverride["override_type"],
      notes: notes || undefined,
    };
    if (!isTrendBounds) {
      payload.lower_boundary = lower ? parseFloat(lower) : undefined;
      payload.upper_boundary = upper ? parseFloat(upper) : undefined;
    }
    if (isTrendBounds) {
      payload.trend_start_timestamp = trendStart
        ? `${trendStart}T00:00:00Z`
        : undefined;
      payload.trend_end_timestamp = trendEnd
        ? `${trendEnd}T00:00:00Z`
        : undefined;
    }
    onSave(payload);
  };

  return (
    <div
      style={{
        background: "var(--bg-base)",
        border: "1px solid #F5A62340",
        borderRadius: 2,
        padding: "10px 12px",
        margin: "4px 8px 8px 8px",
      }}
    >
      {!isTrendBounds && (
        <>
          <label style={labelStyle}>LOWER BOUNDARY</label>
          <input
            style={inputStyle}
            type="number"
            step="any"
            placeholder="e.g. 110.000"
            value={lower}
            onChange={(e) => setLower(e.target.value)}
          />
          <label style={labelStyle}>UPPER BOUNDARY</label>
          <input
            style={inputStyle}
            type="number"
            step="any"
            placeholder="e.g. 112.500"
            value={upper}
            onChange={(e) => setUpper(e.target.value)}
          />
        </>
      )}

      {isTrendBounds && (
        <>
          <label style={labelStyle}>TREND START DATE</label>
          <input
            style={inputStyle}
            type="date"
            value={trendStart}
            onChange={(e) => setTrendStart(e.target.value)}
          />
          <label style={labelStyle}>TREND END DATE</label>
          <input
            style={inputStyle}
            type="date"
            value={trendEnd}
            onChange={(e) => setTrendEnd(e.target.value)}
          />
        </>
      )}

      <label style={labelStyle}>NOTES</label>
      <input
        style={inputStyle}
        type="text"
        placeholder="optional note"
        value={notes ?? ""}
        onChange={(e) => setNotes(e.target.value)}
      />

      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={saving}
          style={{
            flex: 1,
            padding: "5px 0",
            background: "#F5A623",
            color: "var(--bg-base)",
            border: "none",
            borderRadius: 2,
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 9,
            letterSpacing: "0.08em",
            cursor: saving ? "not-allowed" : "pointer",
            textTransform: "uppercase",
          }}
        >
          {saving ? "SAVING..." : "SAVE"}
        </button>

        {existing?.is_active && (
          <button
            type="button"
            onClick={onReset}
            disabled={saving}
            style={{
              flex: 1,
              padding: "5px 0",
              background: "transparent",
              color: "#EF5350",
              border: "1px solid #EF535040",
              borderRadius: 2,
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 9,
              letterSpacing: "0.08em",
              cursor: saving ? "not-allowed" : "pointer",
              textTransform: "uppercase",
            }}
          >
            RESET
          </button>
        )}

        <button
          type="button"
          onClick={onClose}
          style={{
            padding: "5px 8px",
            background: "transparent",
            color: "var(--text-muted)",
            border: "1px solid var(--border-default)",
            borderRadius: 2,
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 9,
            cursor: "pointer",
          }}
        >
          ×
        </button>
      </div>
    </div>
  );
}

const overrideEditButtonStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 8,
  letterSpacing: "0.08em",
  cursor: "pointer",
  padding: "2px 4px",
};

const overrideActiveTagStyle: CSSProperties = {
  margin: "0 8px 4px 8px",
  padding: "3px 8px",
  background: "#F5A62308",
  border: "1px solid #F5A62330",
  borderRadius: 2,
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 8,
  color: "#F5A623",
  letterSpacing: "0.08em",
};

const sectionHeaderBadgeStyle: CSSProperties = {
  padding: "2px 6px",
  border: "1px solid #F5A62330",
  background: "#F5A62308",
  color: "#F5A623",
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 8,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
};

const sectionStatusSlotStyle: CSSProperties = {
  minWidth: 102,
  textAlign: "right",
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 8,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const ALL_RECOMPUTE_LAYERS: ManualRecomputeLayer[] = ["global", "prime", "walker", "candidate"];

const SECTION_OVERRIDE_TYPES: Record<ManualRecomputeLayer, ManualOverride["override_type"][]> = {
  global: ["global_choch", "trend_bounds"],
  prime: ["ichoch"],
  walker: ["depth_choch"],
  candidate: ["candidate_choch", "candidate_ichoch"],
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function hasTimestampAdvanced(previous: string | null | undefined, next: string | null | undefined): boolean {
  if (!next) return false;
  if (!previous) return true;
  const previousMs = Date.parse(previous);
  const nextMs = Date.parse(next);
  if (Number.isNaN(previousMs) || Number.isNaN(nextMs)) {
    return previous !== next;
  }
  return nextMs > previousMs;
}

function normalizeOverrideMap(overrides: Record<string, ManualOverride> | null | undefined): Record<string, ManualOverride> {
  if (!overrides) return {};
  return Object.fromEntries(
    Object.entries(overrides).filter(([, value]) => value && value.is_active !== false),
  );
}

function sectionHasActiveOverride(
  overrides: Record<string, ManualOverride>,
  layer: ManualRecomputeLayer,
): boolean {
  return SECTION_OVERRIDE_TYPES[layer].some((overrideType) => overrides[overrideType]?.is_active);
}

export function MarketCockpit({
  setup,
  candles,
  analysisData,
  onAnalysisDataChange,
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
  onResetServerDefaults,
  isRecomputingParams = false,
  onBack,
}: MarketCockpitProps) {
  const [trendStartOverlay, setTrendStartOverlay] = useState<TrendStartOverlayPayload | null>(null);
  const [allTrendTimeframes, setAllTrendTimeframes] = useState<Record<string, TrendStartOverlayPayload> | null>(null);
  const [marketPickerOpen, setMarketPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  const marketPickerRef = useRef<HTMLDivElement | null>(null);
  const overlayGroupsRef = useRef<HTMLDivElement | null>(null);
  const [overlayState, setOverlayState] = useState({
    // GLOBAL
    globalLegs: true,
    globalBos: true,
    globalChochZone: true,
    globalIchochZone: true,
    // PRIME
    primeLegs: true,
    primeIchochZone: true,
    // WALKER
    walkerDepthRects: true,
    walkerBosLines: true,
    // CANDIDATE
    candidateLegs: true,
    candidateChochZone: true,
    candidateIchochZone: true,
    candidatePrimeLegs: true,
    candidatePrimeChoch: true,
    paperTradeOverlays: false,
  });
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [infoPanelCollapsed, setInfoPanelCollapsed] = useState(false);
  const [globalStructureOpen, setGlobalStructureOpen] = useState(false);
  const [primeImpulseOpen, setPrimeImpulseOpen] = useState(false);
  const [walkerOpen, setWalkerOpen] = useState(true);
  const [candidateImpulseOpen, setCandidateImpulseOpen] = useState(false);
  const [analysisParamsOpen, setAnalysisParamsOpen] = useState(false);
  const [advancedOverridesOpen, setAdvancedOverridesOpen] = useState(false);
  const [coreDraft, setCoreDraft] = useState<AnalysisCoreParams>(() => pickCoreParams(analysisDevParams));
  const coreCommittedSnapRef = useRef("");
  const [trendWindowStructure, setTrendWindowStructure] = useState<TrendWindowStructure | null>(null);
  const [marketContextOpen, setMarketContextOpen] = useState(true);
  const [devOpen, setDevOpen] = useState(false);
  const [chartTheme, setChartTheme] = useState<"dark" | "light">("dark");

  const [overrides, setOverrides] = useState<Record<string, ManualOverride>>({});
  const [editingSection, setEditingSection] = useState<string | null>(null);
  const [savingOverride, setSavingOverride] = useState(false);
  const [isOverrideRecomputing, setIsOverrideRecomputing] = useState(false);
  const [recomputeLayers, setRecomputeLayers] = useState<ManualRecomputeLayer[]>([]);
  const [recomputeScope, setRecomputeScope] = useState<Record<ManualRecomputeLayer, boolean>>({
    global: true,
    prime: true,
    walker: true,
    candidate: true,
  });
  const recomputeRunIdRef = useRef(0);

  function patchAnalysisDevParams(partial: Partial<AnalysisDevParams>) {
    onAnalysisDevParamsChange({ ...analysisDevParams, ...partial });
  }

  const GROUP_KEYS: Record<string, string[]> = {
    GLOBAL: ["globalLegs", "globalBos", "globalChochZone", "globalIchochZone"],
    PRIME: ["primeLegs", "primeIchochZone"],
    WALKER: ["walkerDepthRects", "walkerBosLines"],
    CANDIDATE: ["candidateLegs", "candidateChochZone", "candidateIchochZone", "candidatePrimeLegs", "candidatePrimeChoch"],
    TRADES: ["paperTradeOverlays"],
  };

  const toggleGroup = (group: string) => {
    const keys = GROUP_KEYS[group] ?? [];
    const anyOn = keys.some(k => overlayState[k as keyof typeof overlayState]);
    const update = Object.fromEntries(keys.map(k => [k, !anyOn]));
    setOverlayState(prev => ({ ...prev, ...update }));
  };

  const toggleOne = (key: keyof typeof overlayState) => {
    setOverlayState(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleDropdown = (group: string) => {
    setOpenGroup(prev => prev === group ? null : group);
  };

  useEffect(() => {
    const update = () => {
      const attr = document.documentElement.getAttribute("data-theme");
      setChartTheme(attr === "light" ? "light" : "dark");
    };
    update();
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);

  useEffect(() => {
    coreCommittedSnapRef.current = "";
  }, [setup.symbol]);

  useEffect(() => {
    if (!setup.symbol) return;
    let cancelled = false;
    api
      .getManualStructureOverrides(setup.symbol)
      .then((list) => {
        if (cancelled) return;
        const map: Record<string, ManualOverride> = {};
        list.forEach((o) => {
          map[o.override_type] = o;
        });
        setOverrides(normalizeOverrideMap(map));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [setup.symbol]);

  useEffect(() => {
    if (analysisData?.manual_overrides === undefined) return;
    setOverrides(normalizeOverrideMap(analysisData.manual_overrides));
  }, [analysisData?.manual_overrides]);

  useEffect(() => {
    recomputeRunIdRef.current += 1;
    setIsOverrideRecomputing(false);
    setRecomputeLayers([]);
    setRecomputeScope({ global: true, prime: true, walker: true, candidate: true });
  }, [setup.symbol]);

  const beginRecomputePolling = async (
    layers: ManualRecomputeLayer[],
    baselineAnalysis?: AnalysisResponse | null,
  ) => {
    const normalizedLayers = layers.length > 0 ? layers : ALL_RECOMPUTE_LAYERS;
    const baselineLayerTimestamps = baselineAnalysis?.layer_cache_timestamps ?? null;
    const baselineAnalysisComputedAt = baselineAnalysis?.analysis_computed_at ?? null;
    const runId = ++recomputeRunIdRef.current;

    setIsOverrideRecomputing(true);
    setRecomputeLayers(normalizedLayers);

    const startedAt = Date.now();
    let latestAnalysis: AnalysisResponse | null = baselineAnalysis ?? null;

    while (Date.now() - startedAt < 60_000) {
      await sleep(3_000);
      if (runId !== recomputeRunIdRef.current) return;

      try {
        const fresh = await api.getAnalysis(setup.symbol, activeTimeframe, analysisQueryForApi);
        latestAnalysis = fresh;
        if (runId !== recomputeRunIdRef.current) return;

        const nextLayerTimestamps: LayerCacheTimestamps | null | undefined = fresh.layer_cache_timestamps;
        const complete = nextLayerTimestamps
          ? normalizedLayers.every((layer) =>
              hasTimestampAdvanced(
                baselineLayerTimestamps?.[layer] ?? null,
                nextLayerTimestamps?.[layer] ?? null,
              ),
            )
          : hasTimestampAdvanced(baselineAnalysisComputedAt, fresh.analysis_computed_at ?? null);

        if (complete) {
          onAnalysisDataChange?.(fresh);
          setOverrides(normalizeOverrideMap(fresh.manual_overrides));
          setIsOverrideRecomputing(false);
          setRecomputeLayers([]);
          return;
        }
      } catch (error) {
        console.error("Recompute polling failed:", error);
      }
    }

    if (runId === recomputeRunIdRef.current) {
      onAnalysisDataChange?.(latestAnalysis);
      if (latestAnalysis) {
        setOverrides(normalizeOverrideMap(latestAnalysis.manual_overrides));
      }
      setIsOverrideRecomputing(false);
      setRecomputeLayers([]);
    }
  };

  const handleSectionScopeToggle = (layer: ManualRecomputeLayer) => {
    setRecomputeScope((prev) => ({ ...prev, [layer]: !prev[layer] }));
  };

  const layersForOverrideType = (overrideType: ManualOverride["override_type"]): ManualRecomputeLayer[] => {
    if (overrideType === "trend_bounds" || overrideType === "global_choch") {
      return ALL_RECOMPUTE_LAYERS;
    }
    if (overrideType === "ichoch") {
      return ["prime", "walker", "candidate"];
    }
    if (overrideType === "depth_choch") {
      return ["walker", "candidate"];
    }
    return ["candidate"];
  };

  const handleSaveOverride = async (data: Partial<ManualOverride>) => {
    if (!data.override_type) return;
    if (!setup.symbol) return;
    setSavingOverride(true);
    try {
      const { override_type, ...rest } = data;
      const result = await api.setManualStructureOverride(setup.symbol, {
        override_type,
        ...rest,
      });
      setOverrides((prev) => ({
        ...prev,
        [override_type]: result.override,
      }));
      setEditingSection(null);
      if (result.recompute_triggered) {
        void beginRecomputePolling(layersForOverrideType(override_type), analysisData ?? null);
      }
    } catch (e) {
      console.error("Failed to save override:", e);
    } finally {
      setSavingOverride(false);
    }
  };

  const handleResetOverride = async (overrideType: string) => {
    if (!setup.symbol) return;
    setSavingOverride(true);
    try {
      const result = await api.resetManualStructureOverride(setup.symbol, overrideType);
      setOverrides((prev) => {
        const next = { ...prev };
        delete next[overrideType];
        return next;
      });
      setEditingSection(null);
      if (result.recompute_triggered) {
        void beginRecomputePolling(
          layersForOverrideType(overrideType as ManualOverride["override_type"]),
          analysisData ?? null,
        );
      }
    } catch (e) {
      console.error("Failed to reset override:", e);
    } finally {
      setSavingOverride(false);
    }
  };

  const handleResetSection = async (layer: ManualRecomputeLayer) => {
    if (!setup.symbol) return;
    const activeTypes = SECTION_OVERRIDE_TYPES[layer].filter((overrideType) => overrides[overrideType]?.is_active);
    if (activeTypes.length === 0) return;

    setSavingOverride(true);
    try {
      for (const overrideType of activeTypes) {
        await api.resetManualStructureOverride(setup.symbol, overrideType);
      }
      setOverrides((prev) => {
        const next = { ...prev };
        for (const overrideType of activeTypes) {
          delete next[overrideType];
        }
        return next;
      });
      setEditingSection(null);
      void beginRecomputePolling(layersForOverrideType(activeTypes[0]!), analysisData ?? null);
    } catch (error) {
      console.error("Failed to reset section override:", error);
    } finally {
      setSavingOverride(false);
    }
  };

  const triggerScopedRecompute = async (layers: ManualRecomputeLayer[]) => {
    if (!setup.symbol || layers.length === 0) return;
    try {
      const result = await api.recomputeManualStructureOverrides(setup.symbol, layers);
      if (result.recompute_triggered) {
        void beginRecomputePolling(result.layers, analysisData ?? null);
      }
    } catch (error) {
      console.error("Failed to trigger scoped recompute:", error);
    }
  };

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
    if (!openGroup) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const el = overlayGroupsRef.current;
      if (el && !el.contains(e.target as Node)) {
        setOpenGroup(null);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [openGroup]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenGroup(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

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
  const zoneMapColor = isRangeTrend ? "var(--text-dim)" : isDownTrend ? "#EF5350" : "#26A69A";
  const zoneMapLabel = isRangeTrend ? "RANGE" : isDownTrend ? "DOWN ↓" : "UP ↑";

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

  const walkerState = analysisData?.structural_state ?? setup.structural_state_json ?? null;
  const walkerLevelsPanelData: WalkerLevel[] = (walkerState?.levels ?? []) as WalkerLevel[];
  const walkerMaxDepth = walkerState?.max_depth_reached ?? 0;
  const walkerWaitingFor = walkerState?.waiting_for ?? "";
  const walkerGlobalChoch =
    (walkerState as { global_choch_zone?: { lower_boundary: number; upper_boundary: number } | null } | null)
      ?.global_choch_zone ?? null;

  const candidateSourceRaw = String(candidateMove?.choch_source ?? "").toLowerCase();
  const candidatePanelSource =
    candidateSourceRaw === "both"
      ? "BOTH"
      : candidateSourceRaw === "prime_internal"
        ? "INTERNAL"
        : candidateSourceRaw === "global"
          ? "GLOBAL"
          : "—";
  const candidatePanelTrend =
    typeof candidateMove?.trend === "string"
      ? String(candidateMove.trend).toUpperCase()
      : "—";
  const candidatePanelLegs =
    candidateMove?.candidate_legs?.length != null
      ? String(candidateMove.candidate_legs.filter((l) => l.confirmed).length)
      : "—";
  const candidatePanelPhase =
    typeof candidateMove?.phase === "string" && candidateMove.phase.length > 0
      ? candidateMove.phase.toUpperCase()
      : "—";
  const candidatePrimeLeg = candidateMove?.candidate_prime_impulse;
  const candidatePanelPrimeImpulse =
    candidatePrimeLeg &&
    typeof candidatePrimeLeg.start_price === "number" &&
    candidatePrimeLeg.end_price != null
      ? `${formatPrice(candidatePrimeLeg.start_price)} → ${formatPrice(candidatePrimeLeg.end_price)}`
      : "—";
  const candidatePanelChoch =
    candidateMove?.candidate_choch_zone &&
    typeof candidateMove.candidate_choch_zone.lower_boundary === "number" &&
    typeof candidateMove.candidate_choch_zone.upper_boundary === "number"
      ? `${formatPrice(candidateMove.candidate_choch_zone.lower_boundary)} — ${formatPrice(candidateMove.candidate_choch_zone.upper_boundary)}`
      : "—";
  const candidatePanelBos =
    candidateMove != null && candidateMove.reference_bos_price != null
      ? formatPrice(candidateMove.reference_bos_price)
      : "—";
  const candidatePanelStructureBroken =
    candidateMove?.structure_broken === true
      ? "YES"
      : candidateMove?.structure_broken === false
        ? "NO"
        : "—";

  const candidateWalkerState = analysisOverlaysReady
    ? (candidateMove?.candidate_walker ?? null)
    : null;
  const candidateWalkerLevels: WalkerLevel[] =
    (candidateWalkerState?.levels ?? []) as WalkerLevel[];
  const candidateWalkerDepth = candidateWalkerState?.max_depth_reached ?? 0;
  const candidateWalkerWaiting = candidateWalkerState?.waiting_for ?? "";
  const candidateGlobalChoch = candidateWalkerState?.global_choch_zone ?? null;
  const activeOverrideCount = Object.values(overrides).filter((override) => override?.is_active).length;
  const globalOverrideActive = sectionHasActiveOverride(overrides, "global");
  const primeOverrideActive = sectionHasActiveOverride(overrides, "prime");
  const walkerOverrideActive = sectionHasActiveOverride(overrides, "walker");
  const candidateOverrideActive = sectionHasActiveOverride(overrides, "candidate");
  const globalRecomputing = isOverrideRecomputing && recomputeLayers.includes("global");
  const primeRecomputing = isOverrideRecomputing && recomputeLayers.includes("prime");
  const walkerRecomputing = isOverrideRecomputing && recomputeLayers.includes("walker");
  const candidateRecomputing = isOverrideRecomputing && recomputeLayers.includes("candidate");

  const panelRowLabel: CSSProperties = {
    fontSize: 9,
    color: "var(--text-dim)",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  };
  const panelRowValue: CSSProperties = {
    fontSize: 11,
    fontWeight: 700,
    color: "var(--text-primary)",
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

  const GROUP_CHECKBOXES: Record<string, { key: string; label: string }[]> = {
    GLOBAL: [
      { key: "globalLegs", label: "Trend legs" },
      { key: "globalBos", label: "BOS line" },
      { key: "globalChochZone", label: "CHoCH zone" },
      { key: "globalIchochZone", label: "iCHoCH zone" },
    ],
    PRIME: [
      { key: "primeLegs", label: "Internal legs" },
      { key: "primeIchochZone", label: "iCHoCH zone" },
    ],
    WALKER: [
      { key: "walkerDepthRects", label: "Depth rectangles" },
      { key: "walkerBosLines", label: "BOS classification lines" },
    ],
    CANDIDATE: [
      { key: "candidateLegs", label: "Candidate legs" },
      { key: "candidateChochZone", label: "CHoCH zone" },
      { key: "candidateIchochZone", label: "iCHoCH zone" },
      { key: "candidatePrimeLegs", label: "Prime internal legs" },
      { key: "candidatePrimeChoch", label: "Prime CHoCH zone" },
    ],
    TRADES: [{ key: "paperTradeOverlays", label: "Entry / stop / TP / zone" }],
  };

  const hasOpenPaperTrade = Boolean(analysisOverlaysReady && analysisData?.open_paper_trade);
  const overlayMasterGroups = hasOpenPaperTrade
    ? (["GLOBAL", "PRIME", "WALKER", "CANDIDATE", "TRADES"] as const)
    : (["GLOBAL", "PRIME", "WALKER", "CANDIDATE"] as const);

  return (
    <>
    <style>{`
      @keyframes overlayFadeIn {
        from { opacity: 0; transform: translateY(-4px); }
        to   { opacity: 1; transform: translateY(0); }
      }
    `}</style>
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        height: "100%",
        padding: 10,
        background: "var(--bg-base)",
        color: "var(--text-primary)",
        fontFamily: '"IBM Plex Mono", monospace',
      }}
    >
      <div ref={marketPickerRef} style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: "6px 8px", position: "relative" }}>
        <span style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Market</span>
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
              background: "var(--bg-base)",
              border: "1px solid var(--bg-elevated)",
              color: "var(--text-primary)",
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
            <span style={{ fontSize: 9, color: "var(--text-dim)" }}>{marketPickerOpen ? "▲" : "▼"}</span>
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
              border: "1px solid var(--border-subtle)",
              background: "var(--bg-surface)",
              zIndex: 20,
              display: "flex",
              flexDirection: "column",
              boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
            }}
          >
            <div style={{ padding: 8, borderBottom: "1px solid var(--border-subtle)" }}>
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
                  background: "var(--bg-base)",
                  border: "1px solid var(--bg-elevated)",
                  color: "var(--text-primary)",
                  padding: "6px 10px",
                  fontFamily: '"IBM Plex Mono", monospace',
                  outline: "none",
                }}
              />
            </div>
            <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
              {universeDeduped.length === 0 ? (
                <div style={{ padding: 12, fontSize: 10, color: "var(--text-dim)" }}>Loading universe…</div>
              ) : filteredUniverse.length === 0 ? (
                <div style={{ padding: 12, fontSize: 10, color: "var(--text-dim)" }}>No matches</div>
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
                          background: "var(--bg-base)",
                          borderBottom: "1px solid var(--border-subtle)",
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
                              borderBottom: "1px solid var(--border-subtle)",
                              background: active ? "rgba(245,166,35,0.12)" : "transparent",
                              color: active ? "#F5A623" : "var(--text-primary)",
                              fontSize: 11,
                              cursor: "pointer",
                              fontFamily: '"IBM Plex Mono", monospace',
                            }}
                          >
                            {sym}
                            <span style={{ marginLeft: 8, fontSize: 9, color: "var(--text-dim)" }}>{row.category}</span>
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
      <section style={{ display: "flex", minHeight: 0, flexDirection: "column", border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", position: "relative" }}>
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--border-subtle)", padding: "8px 12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.04em", color: "var(--text-primary)" }}>{setup.symbol}</div>
              {setup.category === "equities" &&
                setup.display_name &&
                setup.display_name !== setup.symbol && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--text-secondary)",
                      letterSpacing: "0.03em",
                      fontFamily: "'IBM Plex Mono', monospace",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      maxWidth: 200,
                    }}
                  >
                    {setup.display_name}
                  </div>
                )}
            </div>
            <div style={{ marginTop: 4, fontSize: 10, letterSpacing: "0.12em", color: "var(--text-dim)", textTransform: "uppercase" }}>
              {setup.category} · {activeTimeframe} · {setup.broker}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--text-dim)", textTransform: "uppercase" }}>Overlays</div>
              <div ref={overlayGroupsRef} style={{ display: "flex", alignItems: "center", gap: 4, position: "relative" }}>
                {overlayMasterGroups.map((group) => {
                  const keys = GROUP_KEYS[group];
                  const anyActive = keys.some(k => overlayState[k as keyof typeof overlayState]);
                  const allActive = keys.every(k => overlayState[k as keyof typeof overlayState]);
                  const bgColor = anyActive ? "#F5A623" : "#1a1a2e";
                  const textColor = anyActive ? "#000" : "#666";

                  return (
                    <div key={group} style={{ position: "relative", display: "inline-block" }}>
                      {/* Master toggle button */}
                      <button
                        type="button"
                        onClick={() => toggleGroup(group)}
                        style={{
                          background: bgColor,
                          color: textColor,
                          border: "none",
                          borderRadius: "4px 0 0 4px",
                          padding: "4px 8px",
                          cursor: "pointer",
                          fontSize: "11px",
                          fontWeight: 600,
                          fontFamily: '"IBM Plex Mono", monospace',
                        }}
                      >
                        {group}
                      </button>
                      {/* Expand chevron */}
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); toggleDropdown(group); }}
                        style={{
                          background: bgColor,
                          color: textColor,
                          border: "none",
                          borderRadius: "0 4px 4px 0",
                          padding: "4px 4px",
                          cursor: "pointer",
                          fontSize: "9px",
                          borderLeft: "1px solid rgba(0,0,0,0.2)",
                          fontFamily: '"IBM Plex Mono", monospace',
                        }}
                      >
                        <span style={{
                          display: "inline-block",
                          transition: "transform 150ms",
                          transform: openGroup === group ? "rotate(180deg)" : "rotate(0deg)",
                        }}>▾</span>
                      </button>
                      {/* Polished popover panel */}
                      {openGroup === group && (() => {
                        const checkboxes = GROUP_CHECKBOXES[group] ?? [];
                        return (
                          <div
                            style={{
                              position: "absolute",
                              top: "calc(100% + 8px)",
                              left: "0",
                              zIndex: 1000,
                              background: "#0d0d1a",
                              border: "1px solid #2a2a3e",
                              borderRadius: "8px",
                              boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
                              padding: "0",
                              minWidth: "200px",
                              animation: "overlayFadeIn 150ms ease forwards",
                              overflow: "hidden",
                            }}
                          >
                            {/* Panel header */}
                            <div style={{
                              padding: "8px 12px 6px",
                              borderBottom: "1px solid #2a2a3e",
                              fontSize: "10px",
                              fontWeight: 700,
                              letterSpacing: "0.1em",
                              textTransform: "uppercase",
                              color: "#F59E0B",
                            }}>
                              {openGroup}
                            </div>
                            {/* Checkbox rows */}
                            {checkboxes.map(({ key, label }) => {
                              const checked = overlayState[key as keyof typeof overlayState];
                              return (
                                <label
                                  key={key}
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "space-between",
                                    padding: "7px 12px",
                                    cursor: "pointer",
                                    fontSize: "12px",
                                    color: "#c0c0d0",
                                    position: "relative",
                                  }}
                                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#1a1a2e"; }}
                                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                                >
                                  <span>{label}</span>
                                  {/* Custom amber checkbox */}
                                  <div style={{
                                    width: "14px",
                                    height: "14px",
                                    border: "1.5px solid",
                                    borderColor: checked ? "#F59E0B" : "#444",
                                    borderRadius: "3px",
                                    background: checked ? "#F59E0B" : "transparent",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    flexShrink: 0,
                                    transition: "all 150ms",
                                  }}>
                                    {checked && (
                                      <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                                        <path
                                          d="M1 3.5L3.5 6L8 1"
                                          stroke="#000"
                                          strokeWidth="1.5"
                                          strokeLinecap="round"
                                          strokeLinejoin="round"
                                        />
                                      </svg>
                                    )}
                                  </div>
                                  {/* Hidden real checkbox for accessibility */}
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleOne(key as keyof typeof overlayState)}
                                    style={{ position: "absolute", opacity: 0, width: 0, height: 0 }}
                                  />
                                </label>
                              );
                            })}
                          </div>
                        );
                      })()}
                    </div>
                  );
                })}
              </div>
            </div>
            <div style={{ marginTop: 4, fontSize: 13, fontWeight: 700, color: zoneMapColor }}>
              {zoneMapLabel}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", padding: "6px 16px", borderBottom: "1px solid var(--border-subtle)", gap: 4 }}>
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
                    color: isActive ? "var(--bg-base)" : "var(--text-muted)",
                    border: isActive ? "1px solid #F5A623" : "1px solid var(--border-subtle)",
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
                e.currentTarget.style.color = "var(--text-primary)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = "var(--text-dim)";
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
                color: "var(--text-dim)",
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
              showGlobalLegs={overlayState.globalLegs}
              showGlobalBos={overlayState.globalBos}
              showGlobalChochZone={overlayState.globalChochZone}
              showGlobalIchochZone={overlayState.globalIchochZone}
              showPrimeLegs={overlayState.primeLegs}
              showPrimeIchochZone={overlayState.primeIchochZone}
              showWalkerDepthRects={overlayState.walkerDepthRects}
              showWalkerBosLines={overlayState.walkerBosLines}
              showCandidateLegs={overlayState.candidateLegs}
              showCandidateChochZone={overlayState.candidateChochZone}
              showCandidateIchochZone={overlayState.candidateIchochZone}
              showCandidatePrimeLegs={overlayState.candidatePrimeLegs}
              showCandidatePrimeChoch={overlayState.candidatePrimeChoch}
              walkerLevels={(analysisOverlaysReady ? (analysisData?.structural_state?.levels ?? []) : []) as unknown as WalkerLevel[]}
              bosClassifications={analysisOverlaysReady ? (analysisData as AnalysisResponse & { bos_classifications?: Record<string, string> })?.bos_classifications : undefined}
              primeImpulseStructure={analysisOverlaysReady ? (analysisData?.prime_impulse_structure ?? null) : null}
              candidatePrimeImpulse={analysisOverlaysReady ? ((analysisData?.candidate_move?.candidate_prime_impulse as unknown) ?? null) : null}
              candidatePrimeChochZone={analysisOverlaysReady ? (analysisData?.candidate_move?.candidate_prime_choch_zone ?? null) : null}
              candidateWalker={analysisOverlaysReady ? (analysisData?.candidate_move?.candidate_walker ?? null) : null}
              showAnalysisOverlays={analysisOverlaysReady}
              analysisReady={analysisOverlaysReady && analysisData != null}
              isSwitchingTimeframe={isSwitchingTimeframe}
              openPaperTrade={analysisData?.open_paper_trade ?? null}
              showPaperTradeOverlays={overlayState.paperTradeOverlays}
              theme={chartTheme}
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
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
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
              color: "var(--text-dim)",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>MARKET CONTEXT</span>
            <span style={{ color: "var(--text-dim)" }}>{marketContextOpen ? "−" : "+"}</span>
          </button>
          {marketContextOpen && (
            <div
              style={{
                borderTop: "1px solid var(--border-default)",
                padding: "10px 12px 14px",
              }}
            >
              <MarketContextPanel symbol={setup.symbol} />
            </div>
          )}
        </section>

        <section style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: 12 }}>
          <SectionLabel>Trend Summary</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>Trend</div>
              <ValueText color={trendColor(canonicalTrend)}>{canonicalTrend.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>Phase</div>
              <ValueText color={phaseTone(setup.current_phase)}>{setup.current_phase.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>State</div>
              <div style={{ marginTop: 4 }}>
                <MarketStateBadge
                  state={analysisData?.market_state ?? setup.market_state ?? "WAITING"}
                />
              </div>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>Score</div>
              <ValueText>{formatScore(setup.trend_score)}</ValueText>
            </div>
            {candidateMove != null && candidateMove.structure_broken != null ? (
              <div style={{ gridColumn: "1 / -1" }}>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    color: "var(--text-dim)",
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
          <div
            style={{
              marginTop: 12,
              borderTop: "1px solid var(--border-subtle)",
              paddingTop: 12,
              display: "grid",
              gap: 10,
            }}
          >
            <SectionLabel>Score Components</SectionLabel>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>
                Market state
              </span>
              <MarketStateBadge
                state={
                  setup.score_components?.market_state
                  ?? analysisData?.market_state
                  ?? setup.market_state
                  ?? "WAITING"
                }
              />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>
                State score
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
                {(() => {
                  const explicit = setup.score_components?.state_score;
                  if (explicit != null) return explicit.toFixed(1);
                  const stateKey =
                    setup.score_components?.market_state
                    ?? analysisData?.market_state
                    ?? setup.market_state;
                  const base = stateKey ? STATE_BASE_SCORES[stateKey] : undefined;
                  return base != null ? base.toFixed(1) : "0.0";
                })()}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>
                Opportunity
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)", textAlign: "right" }}>
                {setup.score_components?.opportunity_score != null
                  ? setup.score_components.opportunity_score.toFixed(1)
                  : "0.0"}
                {setup.score_components?.opp_detail ? ` (${setup.score_components.opp_detail})` : ""}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>
                Structure
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)" }}>
                {setup.score_components?.structure_score != null
                  ? setup.score_components.structure_score.toFixed(1)
                  : "0.0"}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--text-dim)", textTransform: "uppercase" }}>
                Profile
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-primary)", textTransform: "uppercase" }}>
                {setup.score_components?.profile ?? "BALANCED"}
              </span>
            </div>
          </div>
        </section>

        {analysisData?.open_paper_trade ? (
          <section
            style={{
              border: "1px solid rgba(123,97,255,0.3)",
              background: "rgba(123,97,255,0.08)",
              padding: 12,
              fontFamily: '"IBM Plex Mono", monospace',
            }}
          >
            <SectionLabel>Paper Trade</SectionLabel>
            {(() => {
              const pt = analysisData.open_paper_trade!;
              const d = String(pt.direction ?? "").toLowerCase();
              const long = d === "long" || d === "up";
              return (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#B8A9FF", marginBottom: 8 }}>
                    {long ? "\u25B2 LONG" : "\u25BC SHORT"}
                  </div>
                  <div style={{ display: "grid", gap: 6, fontSize: 11 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ color: "var(--text-dim)" }}>Entry</span>
                      <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>{formatPrice(pt.entry_price)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ color: "var(--text-dim)" }}>Stop</span>
                      <span style={{ color: "#FF1744", fontWeight: 600 }}>{formatPrice(pt.stop_price)}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ color: "var(--text-dim)" }}>TP</span>
                      <span style={{ color: "#00C853", fontWeight: 600 }}>
                        {pt.take_profit_price != null ? formatPrice(pt.take_profit_price) : "\u2014"}
                      </span>
                    </div>
                  </div>
                  <div style={{ marginTop: 10, fontSize: 9, letterSpacing: "0.08em", color: "#7B61FF" }}>
                    PAPER TRADE ACTIVE
                  </div>
                </div>
              );
            })()}
          </section>
        ) : null}

        {activeOverrideCount > 0 && (
          <section
            style={{
              border: "1px solid var(--border-default)",
              background: "var(--bg-base)",
              padding: "10px 12px",
              fontFamily: '"IBM Plex Mono", monospace',
              fontSize: 9,
              display: "grid",
              gap: 8,
            }}
          >
            <div style={{ color: "var(--text-dim)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
              Recompute Scope
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              {ALL_RECOMPUTE_LAYERS.map((layer) => (
                <label
                  key={layer}
                  style={{
                    display: "inline-flex",
                    gap: 6,
                    alignItems: "center",
                    color: "var(--text-primary)",
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={recomputeScope[layer]}
                    onChange={() => handleSectionScopeToggle(layer)}
                    disabled={isOverrideRecomputing}
                  />
                  <span>{layer}</span>
                </label>
              ))}
              <button
                type="button"
                disabled={isOverrideRecomputing || !ALL_RECOMPUTE_LAYERS.some((layer) => recomputeScope[layer])}
                onClick={() => {
                  const selected = ALL_RECOMPUTE_LAYERS.filter((layer) => recomputeScope[layer]);
                  void triggerScopedRecompute(selected);
                }}
                style={{
                  marginLeft: "auto",
                  padding: "5px 10px",
                  background: isOverrideRecomputing ? "#F5A62320" : "#F5A623",
                  color: isOverrideRecomputing ? "#F5A623" : "var(--bg-base)",
                  border: "1px solid #F5A62340",
                  borderRadius: 2,
                  cursor: isOverrideRecomputing ? "not-allowed" : "pointer",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                }}
              >
                {isOverrideRecomputing ? "Recomputing..." : "Run"}
              </button>
            </div>
          </section>
        )}

        <section
          style={{
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", padding: "10px 12px", gap: 8 }}>
            <button
              type="button"
              onClick={() => setGlobalStructureOpen((o) => !o)}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: 0,
                background: "transparent",
                border: "none",
                color: "var(--text-dim)",
                cursor: "pointer",
                textAlign: "left",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
              }}
            >
              <span>GLOBAL STRUCTURE</span>
              <span style={{ color: "var(--text-dim)" }}>{globalStructureOpen ? "−" : "+"}</span>
            </button>
            {globalOverrideActive && <span style={sectionHeaderBadgeStyle}>Override Active</span>}
            <span style={{ ...sectionStatusSlotStyle, color: globalRecomputing ? "#F5A623" : "transparent" }}>
              {globalRecomputing ? "Recomputing..." : "."}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingSection(editingSection === "global_structure" ? null : "global_structure");
              }}
              style={{
                ...overrideEditButtonStyle,
                color: overrides["global_choch"]?.is_active ? "#F5A623" : "var(--border-default)",
              }}
            >
              {overrides["global_choch"]?.is_active ? "● CHOCH" : "CHOCH"}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingSection(editingSection === "trend_bounds" ? null : "trend_bounds");
              }}
              style={{
                ...overrideEditButtonStyle,
                color: overrides["trend_bounds"]?.is_active ? "#F5A623" : "var(--border-default)",
              }}
            >
              {overrides["trend_bounds"]?.is_active ? "● TREND" : "TREND"}
            </button>
            {globalOverrideActive && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void handleResetSection("global");
                }}
                disabled={savingOverride || isOverrideRecomputing}
                style={{ ...overrideEditButtonStyle, color: "#EF5350" }}
              >
                RESET
              </button>
            )}
          </div>
          {editingSection === "global_structure" && (
            <OverrideForm
              overrideType="global_choch"
              existing={overrides["global_choch"]}
              onSave={handleSaveOverride}
              onReset={() => handleResetOverride("global_choch")}
              onClose={() => setEditingSection(null)}
              saving={savingOverride}
            />
          )}
          {editingSection === "trend_bounds" && (
            <OverrideForm
              overrideType="trend_bounds"
              existing={overrides["trend_bounds"]}
              onSave={handleSaveOverride}
              onReset={() => handleResetOverride("trend_bounds")}
              onClose={() => setEditingSection(null)}
              saving={savingOverride}
            />
          )}
          {globalStructureOpen && (
            <div
              style={{
                borderTop: "1px solid var(--border-default)",
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

        <section
          style={{
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", padding: "10px 12px", gap: 8 }}>
            <button
              type="button"
              onClick={() => setPrimeImpulseOpen((o) => !o)}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: 0,
                background: "transparent",
                border: "none",
                color: "var(--text-dim)",
                cursor: "pointer",
                textAlign: "left",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
              }}
            >
              <span>PRIME IMPULSE</span>
              <span style={{ color: "var(--text-dim)" }}>{primeImpulseOpen ? "−" : "+"}</span>
            </button>
            {primeOverrideActive && <span style={sectionHeaderBadgeStyle}>Override Active</span>}
            <span style={{ ...sectionStatusSlotStyle, color: primeRecomputing ? "#F5A623" : "transparent" }}>
              {primeRecomputing ? "Recomputing..." : "."}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingSection(editingSection === "prime_impulse" ? null : "prime_impulse");
              }}
              style={{
                ...overrideEditButtonStyle,
                color: overrides["ichoch"]?.is_active ? "#F5A623" : "var(--border-default)",
              }}
            >
              {overrides["ichoch"]?.is_active ? "● EDIT" : "EDIT"}
            </button>
            {primeOverrideActive && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void handleResetSection("prime");
                }}
                disabled={savingOverride || isOverrideRecomputing}
                style={{ ...overrideEditButtonStyle, color: "#EF5350" }}
              >
                RESET
              </button>
            )}
          </div>
          {editingSection === "prime_impulse" && (
            <OverrideForm
              overrideType="ichoch"
              existing={overrides["ichoch"]}
              onSave={handleSaveOverride}
              onReset={() => handleResetOverride("ichoch")}
              onClose={() => setEditingSection(null)}
              saving={savingOverride}
            />
          )}
          {primeImpulseOpen && (
            <div
              style={{
                borderTop: "1px solid var(--border-default)",
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

        <section
          style={{
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
          }}
        >
          <div style={{ display: "flex", alignItems: "center", padding: "10px 12px", gap: 8 }}>
            <button
              type="button"
              onClick={() => setWalkerOpen((o) => !o)}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: 0,
                background: "transparent",
                border: "none",
                color: "var(--text-dim)",
                cursor: "pointer",
                textAlign: "left",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
              }}
            >
              <span>WALKER</span>
              <span style={{ color: "var(--text-dim)" }}>{walkerOpen ? "−" : "+"}</span>
            </button>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {walkerOverrideActive && <span style={sectionHeaderBadgeStyle}>Override Active</span>}
              <span style={{ ...sectionStatusSlotStyle, color: walkerRecomputing ? "#F5A623" : "transparent", minWidth: 96 }}>
                {walkerRecomputing ? "Recomputing..." : "."}
              </span>
              {walkerMaxDepth > 0 && (
                <span
                  style={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    color: "#F5A623",
                  }}
                >
                  D{walkerMaxDepth}
                </span>
              )}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setEditingSection(editingSection === "walker" ? null : "walker");
                }}
                style={{
                  ...overrideEditButtonStyle,
                  color: overrides["depth_choch"]?.is_active ? "#F5A623" : "var(--border-default)",
                }}
              >
                {overrides["depth_choch"]?.is_active ? "● EDIT" : "EDIT"}
              </button>
              {walkerOverrideActive && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleResetSection("walker");
                  }}
                  disabled={savingOverride || isOverrideRecomputing}
                  style={{ ...overrideEditButtonStyle, color: "#EF5350" }}
                >
                  RESET
                </button>
              )}
            </div>
          </div>
          {walkerOpen && (
            <div>
              {editingSection === "walker" && (
                <OverrideForm
                  overrideType="depth_choch"
                  existing={overrides["depth_choch"]}
                  onSave={handleSaveOverride}
                  onReset={() => handleResetOverride("depth_choch")}
                  onClose={() => setEditingSection(null)}
                  saving={savingOverride}
                />
              )}

              {walkerWaitingFor && (
                <div
                  style={{
                    padding: "0 12px 8px 12px",
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    color: "var(--text-muted)",
                  }}
                >
                  {walkerWaitingFor}
                </div>
              )}

              {walkerGlobalChoch && (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "2px 12px",
                  }}
                >
                  <span style={panelRowLabel}>GLOBAL CHOCH</span>
                  <span style={panelRowValue}>
                    {walkerGlobalChoch.lower_boundary.toFixed(5)}
                    {" \u2013 "}
                    {walkerGlobalChoch.upper_boundary.toFixed(5)}
                  </span>
                </div>
              )}

              {walkerLevelsPanelData.length === 0 ? (
                <div
                  style={{
                    padding: "4px 12px 8px 12px",
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    color: "var(--border-default)",
                  }}
                >
                  NO DEPTH DATA
                </div>
              ) : (
                walkerLevelsPanelData.map((level, idx) => {
                  const depthColor = WALKER_DEPTH_COLORS[level.depth] ?? "#607D8B";
                  const zone = level.choch_zone;
                  const sl = level.structural_level;
                  const mitigated = level.is_mitigated ?? level.choch_mitigated ?? false;

                  return (
                    <div
                      key={idx}
                      style={{
                        borderLeft: `2px solid ${depthColor}40`,
                        margin: "4px 8px",
                        padding: "4px 8px",
                        background: `${depthColor}08`,
                        borderRadius: 2,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          marginBottom: 4,
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 9,
                            color: depthColor,
                            letterSpacing: "0.08em",
                          }}
                        >
                          DEPTH {level.depth}
                        </span>
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 9,
                            color: mitigated ? "#4CAF50" : "#EF5350",
                          }}
                        >
                          {mitigated ? "MITIGATED" : "ACTIVE"}
                        </span>
                      </div>

                      {zone && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>CHOCH ZONE</span>
                          <span style={{ ...panelRowValue, color: depthColor }}>
                            {zone.lower_boundary.toFixed(5)}
                            {" \u2013 "}
                            {zone.upper_boundary.toFixed(5)}
                          </span>
                        </div>
                      )}

                      {sl?.price != null && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>BOS</span>
                          <span style={panelRowValue}>
                            {sl.price.toFixed(5)}
                            {sl.classification ? ` (${sl.classification})` : ""}
                          </span>
                        </div>
                      )}

                      {level.termination_reason && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>REASON</span>
                          <span style={{ ...panelRowValue, color: "var(--text-muted)" }}>
                            {level.termination_reason}
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </section>

        <section
          style={{
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", padding: "10px 12px", gap: 8 }}>
            <button
              type="button"
              onClick={() => setCandidateImpulseOpen((o) => !o)}
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: 0,
                background: "transparent",
                border: "none",
                color: "var(--text-dim)",
                cursor: "pointer",
                textAlign: "left",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
              }}
            >
              <span>CANDIDATE IMPULSE</span>
              <span style={{ color: "var(--text-dim)" }}>{candidateImpulseOpen ? "−" : "+"}</span>
            </button>
            {candidateOverrideActive && <span style={sectionHeaderBadgeStyle}>Override Active</span>}
            <span style={{ ...sectionStatusSlotStyle, color: candidateRecomputing ? "#F5A623" : "transparent" }}>
              {candidateRecomputing ? "Recomputing..." : "."}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingSection(editingSection === "candidate_impulse" ? null : "candidate_impulse");
              }}
              style={{
                ...overrideEditButtonStyle,
                color: overrides["candidate_choch"]?.is_active ? "#F5A623" : "var(--border-default)",
              }}
            >
              {overrides["candidate_choch"]?.is_active ? "● EDIT" : "EDIT"}
            </button>
            {candidateOverrideActive && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void handleResetSection("candidate");
                }}
                disabled={savingOverride || isOverrideRecomputing}
                style={{ ...overrideEditButtonStyle, color: "#EF5350" }}
              >
                RESET
              </button>
            )}
          </div>
          {editingSection === "candidate_impulse" && (
            <OverrideForm
              overrideType="candidate_choch"
              existing={overrides["candidate_choch"]}
              onSave={handleSaveOverride}
              onReset={() => handleResetOverride("candidate_choch")}
              onClose={() => setEditingSection(null)}
              saving={savingOverride}
            />
          )}
          {candidateImpulseOpen && (
            <div
              style={{
                borderTop: "1px solid var(--border-default)",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 8,
                color: "#9CA3AF",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>CHOCH SOURCE</span>
                <span style={panelRowValue}>{candidatePanelSource}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>TREND</span>
                <span style={panelRowValue}>{candidatePanelTrend}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>LEGS</span>
                <span style={panelRowValue}>{candidatePanelLegs}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>PHASE</span>
                <span style={panelRowValue}>{candidatePanelPhase}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>PRIME IMPULSE</span>
                <span style={panelRowValue}>{candidatePanelPrimeImpulse}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>CHOCH</span>
                <span style={panelRowValue}>{candidatePanelChoch}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>BOS</span>
                <span style={panelRowValue}>{candidatePanelBos}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                <span style={panelRowLabel}>STRUCTURE BROKEN</span>
                <span style={panelRowValue}>{candidatePanelStructureBroken}</span>
              </div>
            </div>
          )}
        </section>

        {candidateMove !== null && (
          <section
            style={{
              border: "1px solid var(--border-default)",
              background: "var(--bg-base)",
              padding: 0,
              fontFamily: '"IBM Plex Mono", monospace',
            }}
          >
            <div
              style={{
                borderTop: "1px solid var(--bg-elevated)",
                padding: "12px 0 4px 0",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0 12px 8px 12px",
                }}
              >
                <span
                  style={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    letterSpacing: "0.12em",
                    color: "var(--text-muted)",
                    textTransform: "uppercase",
                  }}
                >
                  CANDIDATE WALKER
                </span>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {overrides["candidate_ichoch"]?.is_active && <span style={sectionHeaderBadgeStyle}>Override Active</span>}
                  <span style={{ ...sectionStatusSlotStyle, color: candidateRecomputing ? "#F5A623" : "transparent", minWidth: 96 }}>
                    {candidateRecomputing ? "Recomputing..." : "."}
                  </span>
                  {candidateWalkerDepth > 0 && (
                    <span
                      style={{
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 9,
                        color: "#F5A623",
                      }}
                    >
                      D{candidateWalkerDepth}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingSection(editingSection === "candidate_walker" ? null : "candidate_walker");
                    }}
                    style={{
                      ...overrideEditButtonStyle,
                      color: overrides["candidate_ichoch"]?.is_active ? "#F5A623" : "var(--border-default)",
                    }}
                  >
                    {overrides["candidate_ichoch"]?.is_active ? "● EDIT" : "EDIT"}
                  </button>
                  {overrides["candidate_ichoch"]?.is_active && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleResetOverride("candidate_ichoch");
                      }}
                      disabled={savingOverride || isOverrideRecomputing}
                      style={{ ...overrideEditButtonStyle, color: "#EF5350" }}
                    >
                      RESET
                    </button>
                  )}
                </div>
              </div>
              {editingSection === "candidate_walker" && (
                <OverrideForm
                  overrideType="candidate_ichoch"
                  existing={overrides["candidate_ichoch"]}
                  onSave={handleSaveOverride}
                  onReset={() => handleResetOverride("candidate_ichoch")}
                  onClose={() => setEditingSection(null)}
                  saving={savingOverride}
                />
              )}

              {candidateWalkerWaiting && (
                <div
                  style={{
                    padding: "0 12px 8px 12px",
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    color: "var(--text-muted)",
                  }}
                >
                  {candidateWalkerWaiting}
                </div>
              )}

              {candidateGlobalChoch && (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "2px 12px",
                  }}
                >
                  <span style={panelRowLabel}>GLOBAL CHOCH</span>
                  <span style={panelRowValue}>
                    {candidateGlobalChoch.lower_boundary.toFixed(5)}
                    {" \u2013 "}
                    {candidateGlobalChoch.upper_boundary.toFixed(5)}
                  </span>
                </div>
              )}

              {candidateWalkerLevels.length === 0 ? (
                <div
                  style={{
                    padding: "4px 12px 8px 12px",
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 9,
                    color: "var(--border-default)",
                  }}
                >
                  NO CANDIDATE DEPTH DATA
                </div>
              ) : (
                candidateWalkerLevels.map((level, idx) => {
                  const depthColor = WALKER_DEPTH_COLORS[level.depth] ?? "#607D8B";
                  const zone = level.choch_zone;
                  const sl = level.structural_level;
                  const mitigated = level.is_mitigated ?? level.choch_mitigated ?? false;

                  return (
                    <div
                      key={idx}
                      style={{
                        borderLeft: `2px solid ${depthColor}40`,
                        margin: "4px 8px",
                        padding: "4px 8px",
                        background: `${depthColor}08`,
                        borderRadius: 2,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          marginBottom: 4,
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 9,
                            color: depthColor,
                            letterSpacing: "0.08em",
                          }}
                        >
                          DEPTH {level.depth}
                        </span>
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 9,
                            color: mitigated ? "#4CAF50" : "#EF5350",
                          }}
                        >
                          {mitigated ? "MITIGATED" : "ACTIVE"}
                        </span>
                      </div>

                      {zone && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>CHOCH ZONE</span>
                          <span style={{ ...panelRowValue, color: depthColor }}>
                            {zone.lower_boundary.toFixed(5)}
                            {" \u2013 "}
                            {zone.upper_boundary.toFixed(5)}
                          </span>
                        </div>
                      )}

                      {sl?.price != null && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>BOS</span>
                          <span style={panelRowValue}>
                            {sl.price.toFixed(5)}
                            {sl.classification ? ` (${sl.classification})` : ""}
                          </span>
                        </div>
                      )}

                      {level.termination_reason && (
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={panelRowLabel}>REASON</span>
                          <span style={{ ...panelRowValue, color: "var(--text-muted)" }}>
                            {level.termination_reason}
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </section>
        )}

        <section
          style={{
            border: "1px dashed var(--border-strong)",
            background: "var(--bg-base)",
            padding: 0,
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: 10,
          }}
        >
          <button
            type="button"
            onClick={() => setDevOpen((o) => !o)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 12px",
              background: "transparent",
              border: "none",
              color: "var(--text-dim)",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  fontSize: 9,
                  letterSpacing: "0.14em",
                  padding: "2px 6px",
                  border: "1px solid #F5A623",
                  color: "#F5A623",
                  background: "rgba(245,166,35,0.08)",
                }}
              >
                DEV
              </span>
              <span>Developer tools</span>
            </span>
            <span style={{ color: "var(--text-dim)" }}>{devOpen ? "\u2212" : "+"}</span>
          </button>
          {devOpen && (
            <div style={{ borderTop: "1px dashed var(--border-strong)", padding: "10px 12px 12px", display: "grid", gap: 10 }}>
        <section
          style={{
            border: "1px solid var(--border-default)",
            background: "var(--bg-base)",
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
              color: "var(--text-dim)",
              cursor: "pointer",
              textAlign: "left",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            <span>TREND DETECTION</span>
            <span style={{ color: "var(--text-dim)" }}>{analysisParamsOpen ? "−" : "+"}</span>
          </button>
          {analysisParamsOpen && (
            <div
              style={{
                borderTop: "1px solid var(--border-default)",
                padding: "10px 12px 12px",
                display: "grid",
                gap: 10,
                color: "#9CA3AF",
              }}
            >
              <div style={{ fontSize: 9, color: "var(--text-dim)", lineHeight: 1.4 }}>
                Fine-tune how the system identifies trend structure for this market. Changes apply immediately and are saved for this market only.
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                <div
                  style={{
                    display: "grid",
                    gap: 8,
                    border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)",
                    padding: 10,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <TrendDetectionLabel
                      label="Parent relative filter"
                      tooltip={trendDetectionTooltipText.parent}
                    />
                    <button
                      type="button"
                      aria-pressed={coreDraft.use_parent_relative_filter}
                      onClick={() =>
                        setCoreDraft((d) => ({
                          ...d,
                          use_parent_relative_filter: !d.use_parent_relative_filter,
                        }))
                      }
                      style={{
                        ...trendToggleButtonBase,
                        fontWeight: coreDraft.use_parent_relative_filter ? 700 : 400,
                        border: `1px solid ${coreDraft.use_parent_relative_filter ? "#F5A623" : "var(--border-strong)"}`,
                        background: coreDraft.use_parent_relative_filter ? "#F5A623" : "var(--bg-elevated)",
                        color: coreDraft.use_parent_relative_filter ? "var(--bg-base)" : "var(--text-dim)",
                      }}
                    >
                      {coreDraft.use_parent_relative_filter ? "On" : "Off"}
                    </button>
                  </div>
                  {coreDraft.use_parent_relative_filter ? (
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <TrendDetectionLabel
                        label="Min impulse parent ratio"
                        tooltip={trendDetectionTooltipText.parent}
                      />
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
                  ) : null}
                </div>

                <div
                  style={{
                    display: "grid",
                    gap: 8,
                    border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)",
                    padding: 10,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <TrendDetectionLabel
                      label="Momentum filter"
                      tooltip={trendDetectionTooltipText.momentum}
                    />
                    <button
                      type="button"
                      aria-pressed={coreDraft.use_momentum_filter}
                      onClick={() =>
                        setCoreDraft((d) => ({
                          ...d,
                          use_momentum_filter: !d.use_momentum_filter,
                        }))
                      }
                      style={{
                        ...trendToggleButtonBase,
                        fontWeight: coreDraft.use_momentum_filter ? 700 : 400,
                        border: `1px solid ${coreDraft.use_momentum_filter ? "#F5A623" : "var(--border-strong)"}`,
                        background: coreDraft.use_momentum_filter ? "#F5A623" : "var(--bg-elevated)",
                        color: coreDraft.use_momentum_filter ? "var(--bg-base)" : "var(--text-dim)",
                      }}
                    >
                      {coreDraft.use_momentum_filter ? "On" : "Off"}
                    </button>
                  </div>
                  {coreDraft.use_momentum_filter ? (
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <TrendDetectionLabel
                        label="Min momentum ratio"
                        tooltip={trendDetectionTooltipText.momentum}
                      />
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
                  ) : null}
                </div>

                <div
                  style={{
                    display: "grid",
                    gap: 8,
                    border: "1px solid var(--border-default)",
                    background: "var(--bg-surface)",
                    padding: 10,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <TrendDetectionLabel
                      label="Dominance filter"
                      tooltip={trendDetectionTooltipText.dominance}
                    />
                    <button
                      type="button"
                      aria-pressed={coreDraft.use_dominance_filter}
                      onClick={() =>
                        setCoreDraft((d) => ({
                          ...d,
                          use_dominance_filter: !d.use_dominance_filter,
                        }))
                      }
                      style={{
                        ...trendToggleButtonBase,
                        fontWeight: coreDraft.use_dominance_filter ? 700 : 400,
                        border: `1px solid ${coreDraft.use_dominance_filter ? "#F5A623" : "var(--border-strong)"}`,
                        background: coreDraft.use_dominance_filter ? "#F5A623" : "var(--bg-elevated)",
                        color: coreDraft.use_dominance_filter ? "var(--bg-base)" : "var(--text-dim)",
                      }}
                    >
                      {coreDraft.use_dominance_filter ? "On" : "Off"}
                    </button>
                  </div>
                  {coreDraft.use_dominance_filter ? (
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <TrendDetectionLabel
                        label="Min dominance ratio"
                        tooltip={trendDetectionTooltipText.dominance}
                      />
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
                  ) : null}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
                <button
                  type="button"
                  onClick={() => onApplyCoreAnalysisParams(coreDraft)}
                  style={{
                    flex: 1,
                    padding: "6px 12px",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    background: "#F5A623",
                    border: "1px solid #F5A623",
                    color: "var(--bg-base)",
                    cursor: "pointer",
                    textAlign: "center",
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
                    flex: 1,
                    padding: "6px 12px",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-strong)",
                    color: "var(--text-primary)",
                    cursor: "pointer",
                    textAlign: "center",
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  RESET TO DEFAULTS
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onResetServerDefaults();
                  }}
                  style={{
                    flex: 1,
                    padding: "6px 12px",
                    fontSize: 10,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    background: "#151922",
                    border: "1px solid #F5A623",
                    color: "#F5A623",
                    cursor: "pointer",
                    textAlign: "center",
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  RESET TO SERVER DEFAULTS
                </button>
              </div>
              {isRecomputingParams ? (
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "#F5A623",
                  }}
                >
                  RECOMPUTING...
                </div>
              ) : null}

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
                  borderTop: "1px solid var(--border-default)",
                  color: "var(--text-dim)",
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
                  <div style={{ fontSize: 9, color: "var(--text-dim)", lineHeight: 1.4 }}>
                    Changing a value refetches overlays immediately (candles unchanged).
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontSize: 9, color: "var(--text-dim)" }}>max_walk_depth (omit if empty)</span>
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
                      <span style={{ fontSize: 9, color: "var(--text-dim)" }}>min_swing_candles (optional)</span>
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
                      <span style={{ fontSize: 9, color: "var(--text-dim)" }}>trend_confirmation_pct (optional)</span>
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
                  <div style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.06em" }}>RMT subtree (optional)</div>
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
                        <span style={{ fontSize: 8, color: "var(--text-dim)" }}>{label}</span>
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
            </div>
          )}
        </section>
      </aside>
      </div>
    </div>
  </>
  );
}

