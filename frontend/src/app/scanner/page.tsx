"use client";
import { Fragment, Suspense, useCallback, useEffect, useState, useRef, type ReactNode, type CSSProperties } from "react";
import Link from "next/link";
import { LayoutGrid, Table2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { ScoreBar } from "@/components/score-bar";
import { PanelEdgeCollapseToggle } from "@/components/ui/panel-edge-collapse-toggle";
import { LiveStatusMeta, LiveStatusRow } from "@/components/ui/live-status";
import { ScannerTableSkeleton } from "@/components/ui/page-skeleton";
import { RelativeTimeWithTooltip } from "@/components/ui/relative-time";
import { Tooltip } from "@/components/ui/tooltip";
import { formatLocaleInt, formatScore } from "@/lib/format-display";
import { MarketStateBadge, MarketStateDrawer } from "@/components/market-state-badge";
import type { PaperTrade, ScanJobLog, ScanSettings, Setup, UniverseRankingStatus, UniverseSettings } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SCAN_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "EURUSD", "XAUUSD"];
const SCAN_TIMEFRAME = "1h";
const SCAN_SETTINGS_PANEL_STORAGE_KEY = "ikenga.scanSettingsPanelCollapsed";

interface Health {
  status: string;
  active_setups: number;
  max_capacity: number;
  next_scan?: string | null;
  last_scan?: string | null;
}

// ── Sub-components (inline styles, exact reference match) ─────────────────

function TrendScoreDisplay({ value }: { value: number }) {
  let color: string;
  if (value >= 40) color = "#F5A623";
  else if (value >= 20) color = "#D4A017";
  else color = "#434651";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 700, color }}>
        {formatScore(value)}
      </div>
      <div style={{ width: "100%", height: 2, background: "#1E222D", borderRadius: 1, overflow: "hidden" }}>
        <div
          style={{
            width: `${Math.min(100, value)}%`,
            height: "100%",
            background: color,
            transition: "width 0.6s ease",
          }}
        />
      </div>
    </div>
  );
}

function DepthBadge({ depth }: { depth: number }) {
  let color: string;
  if (depth === 1) color = "#2962FF";
  else if (depth === 2) color = "#26A69A";
  else if (depth === 3) color = "#F5A623";
  else color = "#434651";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 700, color }}>
        {depth}
      </div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8, color: "#434651", letterSpacing: "0.06em" }}>
        DEPTH
      </div>
    </div>
  );
}

function DirectionTag({ direction }: { direction: string }) {
  const isLong = direction === "LONG";
  const arrow = isLong ? "▲" : "▼";
  const color = isLong ? "#26A69A" : "#EF5350";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 11, color }}>
        {arrow}
      </span>
      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 600, color }}>
        {isLong ? "LONG" : "SHORT"}
      </span>
    </div>
  );
}

function PhaseBadge({ phase }: { phase: string }) {
  const isRetracement = phase === "RETRACEMENT";
  const color = isRetracement ? "#F5A623" : "#787B86";
  return (
    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color }}>
      {phase}
    </span>
  );
}

function FilterDivider() {
  return (
    <div
      aria-hidden
      style={{ width: 1, alignSelf: "stretch", background: "#2A2E39", flexShrink: 0, margin: "0 10px" }}
    />
  );
}

const filterLabelStyle: CSSProperties = {
  fontSize: 9,
  textTransform: "uppercase",
  color: "#787B86",
  letterSpacing: "0.1em",
  marginBottom: 4,
  fontFamily: "'IBM Plex Mono', monospace",
};

function FilterPill({
  active,
  children,
  onClick,
  tooltip,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
  tooltip?: string;
}) {
  const [hover, setHover] = useState(false);
  const bg = active ? "#F5A623" : hover ? "#2A2E39" : "#1E222D";
  const color = active ? "#0D0F14" : "#787B86";
  const border = active ? "#F5A623" : "#1E222D";
  const inner = (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: "3px 8px",
        fontSize: 10,
        letterSpacing: "0.08em",
        background: bg,
        color,
        border: `1px solid ${border}`,
        borderRadius: 2,
        cursor: "pointer",
        fontFamily: "'IBM Plex Mono', monospace",
        fontWeight: active ? 700 : 400,
      }}
    >
      {children}
    </button>
  );
  return tooltip ? <Tooltip content={tooltip}>{inner}</Tooltip> : inner;
}

const YFINANCE_SYMBOLS = new Set(["SPX500", "NAS100", "DAX40", "FTSE100", "NKY225"]);

function inferBroker(symbol: string): string {
  const u = symbol.toUpperCase();
  if (u.endsWith("USDT") || u.endsWith("BTC")) return "BINANCE";
  if (YFINANCE_SYMBOLS.has(u)) return "YFINANCE";
  return "DERIV";
}

function setupBrokerUpper(setup: Setup): string {
  return setup.broker ? String(setup.broker).toUpperCase() : inferBroker(setup.symbol);
}

function clampMinScoreStep5(n: number): number {
  const r = Math.round(n / 5) * 5;
  return Math.max(0, Math.min(100, r));
}

function cardDepthColor(depth: number): string {
  if (depth === 1) return "#2962FF";
  if (depth === 2) return "#26A69A";
  if (depth === 3) return "#F5A623";
  return "#434651";
}

type DepthFilterOption = "ALL DEPTHS" | "DEPTH 1+" | "DEPTH 2+" | "DEPTH 3";

function passesDepthFilter(setup: Setup, depthFilter: DepthFilterOption): boolean {
  const d = setup.pullback_depth ?? 0;
  if (depthFilter === "ALL DEPTHS") return true;
  if (depthFilter === "DEPTH 1+") return d >= 1;
  if (depthFilter === "DEPTH 2+") return d >= 2;
  return d >= 3;
}

function SignalBadge({ signal }: { signal: Setup["ema_signal"] }) {
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

function MetricBlock({
  label,
  value,
  valueNode,
  color,
}: {
  label: string;
  value?: string | number;
  valueNode?: ReactNode;
  color?: string;
}) {
  return (
    <div style={{ flex: 1, padding: "12px 0", display: "flex", flexDirection: "column", alignItems: "center", borderRight: "1px solid var(--border-subtle)" }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 28, fontWeight: 700, color: color || "var(--text-primary)", lineHeight: 1 }}>
        {valueNode ?? value}
      </div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, letterSpacing: "0.14em", color: "var(--text-dim)", marginTop: 6 }}>
        {label}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────

function derivePhase(fsm_state: string): string {
  return fsm_state === "MONITORING" ? "RETRACEMENT" : "IMPULSE";
}

function deriveDirection(trend: string): string {
  return trend === "up" ? "LONG" : "SHORT";
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toUTCString().slice(17, 22);
  } catch {
    return "--:--";
  }
}

function formatCountdown(msUntil: number): string {
  const totalSeconds = Math.max(0, Math.floor(msUntil / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}


function nextMidnightUtc(): Date {
  const now = new Date();
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1, 0, 0, 0, 0),
  );
}

function formatUtcTimestamp(iso: string | null | undefined): string {
  if (!iso) return "Never";
  try {
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return "Never";
    return d.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
  } catch {
    return "Never";
  }
}

function formatDurationSeconds(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "Unknown";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

function getLatestFinishedUniverseRanking(logs: ScanJobLog[] | null | undefined): ScanJobLog | null {
  if (!logs?.length) return null;
  const finished = logs.filter(
    (j) => j.job_type === "universe_ranking" && j.completed_at != null && j.status !== "running",
  );
  finished.sort((a, b) => {
    const ta = new Date(a.completed_at as string).getTime();
    const tb = new Date(b.completed_at as string).getTime();
    return tb - ta;
  });
  return finished[0] ?? null;
}

function formatEtaSeconds(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "—";
  return formatCountdown(sec * 1000);
}

function formatUniverseRank(rank: number | null | undefined): { text: string; color: string } {
  if (rank == null || !Number.isFinite(Number(rank))) {
    return { text: "—", color: "#434651" };
  }
  const n = Math.floor(Number(rank));
  return {
    text: `#${n}`,
    color: n >= 1 && n <= 50 ? "#F5A623" : "#D1D4DC",
  };
}

// ── Main Component ────────────────────────────────────────────────────────

type UniverseKey = "multi_asset" | "synthetic" | "crypto";

const SYNTHETIC_PREFIXES_FRONTEND = [
  "R_", "1HZ", "BOOM", "CRASH", "JD",
  "OTC_", "STEP", "WLD", "RB", "RDBULL", "STPRNG",
];

function _inferUniverseFrontend(symbol: string, category: string): UniverseKey {
  const sym = (symbol || "").toUpperCase();
  if (sym.endsWith("USDT") || sym.endsWith("BTC")) return "crypto";
  if (SYNTHETIC_PREFIXES_FRONTEND.some((p) => sym.startsWith(p))) return "synthetic";
  const c = (category || "").toLowerCase();
  if (c === "synthetic") return "synthetic";
  if (c === "crypto") return "crypto";
  return "multi_asset";
}

const UNIVERSE_TABS: Array<{ key: UniverseKey; label: string; icon: string }> = [
  { key: "multi_asset", label: "MULTI-ASSET", icon: "◈" },
  { key: "synthetic", label: "SYNTHETIC", icon: "⬡" },
  { key: "crypto", label: "CRYPTO", icon: "₿" },
];

const UNIVERSE_CATEGORIES: Record<UniverseKey, string[]> = {
  multi_asset: ["All", "Forex", "Indices", "Commodities", "Equities"],
  synthetic: ["All", "Synthetic"],
  crypto: ["All", "Crypto"],
};

const RANK_BUTTON_LABELS: Record<UniverseKey, string> = {
  multi_asset: "RANK MARKETS",
  synthetic: "RANK SYNTHETIC",
  crypto: "RANK CRYPTO",
};

const UNIVERSE_RANK_FREQUENCY_OPTIONS = ["hourly", "daily", "weekly", "monthly"] as const;
const UNIVERSE_REFRESH_HOUR_OPTIONS = [1, 2, 4, 8, 12, 24] as const;

const CATEGORIES = ["All", "Forex", "Crypto", "Commodities", "Indices", "Synthetic", "Equities"];
const BROKER_FILTER_OPTIONS = ["ALL", "BINANCE", "DERIV"] as const;
const STATE_FILTER_OPTIONS = ["ALL", "MONITORING", "SCANNING"] as const;
const DEPTH_FILTER_OPTIONS: DepthFilterOption[] = ["ALL DEPTHS", "DEPTH 1+", "DEPTH 2+", "DEPTH 3"];
const SCANNER_FILTER_STORAGE_KEY = "scanner:filters:v1";
const SCANNER_VIEW_STORAGE_KEY = "ikenga.scanner.view";
const MARKET_CATEGORIES = ["forex", "synthetic", "commodity", "indices", "crypto", "equities", "stocks", "etfs"] as const;

const SCAN_SETTINGS_FONT = "'IBM Plex Mono', monospace" as const;

const scanSettingsFieldLabelStyle: CSSProperties = {
  fontFamily: SCAN_SETTINGS_FONT,
  fontSize: 9,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "#787B86",
};

const scanSettingsInputBase: CSSProperties = {
  fontFamily: SCAN_SETTINGS_FONT,
  fontSize: 11,
  color: "#FFFFFF",
  background: "#1E222D",
  border: "1px solid #363A45",
  borderRadius: 0,
  padding: "6px 8px",
  outline: "none",
};

const scanSettingsHintStyle: CSSProperties = {
  fontFamily: SCAN_SETTINGS_FONT,
  fontSize: 9,
  color: "#787B86",
  marginTop: 4,
  lineHeight: 1.35,
};

const DEFAULT_CATEGORY_MIN_SLOTS: ScanSettings["category_min_slots"] = {
  forex: 5,
  commodity: 3,
  indices: 3,
  synthetic: 5,
  crypto: 0,
  equities: 0,
};

const CATEGORY_MIN_ROWS: { key: keyof ScanSettings["category_min_slots"]; label: string }[] = [
  { key: "forex", label: "FOREX" },
  { key: "commodity", label: "COMMODITY" },
  { key: "indices", label: "INDICES" },
  { key: "synthetic", label: "SYNTHETIC" },
  { key: "crypto", label: "CRYPTO" },
  { key: "equities", label: "EQUITIES" },
];

const DEFAULT_SCAN_SETTINGS: ScanSettings = {
  binance_top_n: 350,
  brokers: ["binance", "deriv", "yfinance"],
  deriv_categories: ["forex", "synthetic", "commodity", "indices"],
  include_symbols: [],
  exclude_symbols: [],
  score_weights: { price_ratio_weight: 0.7, bar_ratio_weight: 0.3 },
  scoring_profile: "balanced",
  scoring_layer_weights: {
    state_weight: 0.5,
    opportunity_weight: 0.35,
    structure_weight: 0.15,
  },
  retracement_bonus: 10,
  deriv_category_overrides: {},
  universe_scan_frequency: "daily",
  active_refresh_hours: 4,
  deep_analysis_refresh_hours: 24,
  non_top50_analysis_depth: "global_and_prime",
  category_min_slots: { ...DEFAULT_CATEGORY_MIN_SLOTS },
};

const UNIVERSE_SCAN_FREQUENCIES: ScanSettings["universe_scan_frequency"][] = ["hourly", "daily", "weekly", "monthly"];
const ACTIVE_REFRESH_HOUR_OPTIONS: ScanSettings["active_refresh_hours"][] = [1, 2, 4, 8, 12, 24];
const DEEP_ANALYSIS_REFRESH_OPTIONS = [4, 8, 12, 24, 48, 72] as const;
const NON_TOP50_DEPTH_OPTIONS: { value: string; label: string }[] = [
  { value: "global_only", label: "Global only" },
  { value: "global_and_prime", label: "Global + Prime" },
  { value: "global_prime_walker", label: "Global + Prime + Walker" },
  { value: "full_chain", label: "Full chain" },
];

const SCORING_PROFILE_OPTIONS = ["aggressive", "balanced", "conservative"] as const;

function parseSymbolText(value: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const token of value.split(/[,\n\s]+/g)) {
    const t = token.trim().toUpperCase();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

function parseBinanceTopNDraft(draft: string, fallback: number): number {
  const n = parseInt(draft.trim(), 10);
  const base = Number.isFinite(n) ? n : fallback;
  return Math.max(10, Math.min(1000, base));
}

function OpenPaperTradeBadge({ trade }: { trade: PaperTrade }) {
  const isLong = trade.direction === "long" || trade.direction === "up";
  const arrow = isLong ? "\u25B2" : "\u25BC";
  const hasPnl = trade.pnl_usd != null && Number.isFinite(trade.pnl_usd);
  const pnl = trade.pnl_usd ?? 0;
  const color =
    !hasPnl ? "#7B61FF" : pnl === 0 ? "#7B61FF" : pnl > 0 ? "#00C853" : "#FF1744";
  const text = !hasPnl ? `${arrow} OPEN` : `${pnl >= 0 ? "+" : "-"}$${Math.abs(pnl).toFixed(2)}`;
  return (
    <div
      style={{
        flexShrink: 0,
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 9,
        letterSpacing: "0.04em",
        padding: "2px 6px",
        background: "rgba(123,97,255,0.15)",
        border: "1px solid #7B61FF",
        color,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
}

function normalizeCategory(cat: string | undefined): string {
  if (!cat) return "unknown";
  const c = cat.toLowerCase();
  if (c === "crypto") return "Crypto";
  if (c === "forex") return "Forex";
  if (c === "synthetic") return "Synthetic";
  if (c === "commodity") return "Commodities";
  if (c === "indices" || c === "index") return "Indices";
  if (c === "equities" || c === "equity" || c === "stocks") return "Equities";
  return "Forex";
}

function ScannerContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [setups, setSetups] = useState<Setup[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rankConfirmOpen, setRankConfirmOpen] = useState(false);
  const [rankDialogLoading, setRankDialogLoading] = useState(false);
  const [rankDialogLogs, setRankDialogLogs] = useState<ScanJobLog[] | null>(null);
  const [universeRankingStatus, setUniverseRankingStatus] = useState<UniverseRankingStatus | null>(null);
  const [rankingPollActive, setRankingPollActive] = useState(false);
  const [isTriggeringRank, setIsTriggeringRank] = useState(false);
  const [rankingJustCompleted, setRankingJustCompleted] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [yfinanceRefreshNotice, setYfinanceRefreshNotice] = useState<string | null>(null);
  const initialCategory = searchParams.get("category");
  const initialSort = searchParams.get("sort");
  const [category, setCategory] = useState(
    initialCategory && CATEGORIES.includes(initialCategory) ? initialCategory : "All"
  );
  const [sortBy, setSortBy] = useState<"score" | "symbol">(
    initialSort === "symbol" ? "symbol" : "score"
  );
  const [scanTime, setScanTime] = useState(new Date());
  const [nextScanCountdown, setNextScanCountdown] = useState("--:--");
  const [brokerFilter, setBrokerFilter] = useState<(typeof BROKER_FILTER_OPTIONS)[number]>("ALL");
  const [stateFilter, setStateFilter] = useState<(typeof STATE_FILTER_OPTIONS)[number]>("ALL");
  const [depthFilter, setDepthFilter] = useState<DepthFilterOption>("ALL DEPTHS");
  const [minScore, setMinScore] = useState<number>(0);
  const [listView, setListView] = useState<"table" | "card">("table");
  const [droppingSymbol, setDroppingSymbol] = useState<string | null>(null);
  const [stateDrawerSymbol, setStateDrawerSymbol] = useState<string | null>(null);
  const [scanSettings, setScanSettings] = useState<ScanSettings>(DEFAULT_SCAN_SETTINGS);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsNotice, setSettingsNotice] = useState<"saved" | "failed" | null>(null);
  const settingsNoticeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [includeInput, setIncludeInput] = useState("");
  const [excludeInput, setExcludeInput] = useState("");
  const [topNDraft, setTopNDraft] = useState(String(DEFAULT_SCAN_SETTINGS.binance_top_n));
  const [scanSettingsPanelCollapsed, setScanSettingsPanelCollapsed] = useState(false);
  const universeRankBusy = isTriggeringRank || rankingPollActive;
  const [openTradesMap, setOpenTradesMap] = useState<Map<string, PaperTrade>>(new Map());
  const [symbolsWithOverrides, setSymbolsWithOverrides] = useState<Set<string>>(new Set());

  const [activeUniverse, setActiveUniverse] = useState<UniverseKey>("multi_asset");
  const [universeSettings, setUniverseSettings] = useState<UniverseSettings[]>([]);
  const [universeSettingsTab, setUniverseSettingsTab] = useState<UniverseKey>("multi_asset");
  const [universeSettingsDraft, setUniverseSettingsDraft] = useState<Partial<UniverseSettings>>({});
  const [universeSettingsSaving, setUniverseSettingsSaving] = useState(false);
  const [universeSettingsNotice, setUniverseSettingsNotice] = useState<"saved" | "failed" | null>(null);
  const [tradingBroker, setTradingBroker] = useState<string>("FTMO");

  useEffect(() => {
    api.getUniverses()
      .then((u) => setUniverseSettings(u))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem("trading_broker");
    if (stored && stored.trim().length > 0) {
      setTradingBroker(stored);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const u = params.get("universe");
    if (u === "multi_asset" || u === "synthetic" || u === "crypto") {
      setActiveUniverse(u);
      setUniverseSettingsTab(u);
    }
  }, []);

  const handleUniverseChange = useCallback((u: UniverseKey) => {
    setActiveUniverse(u);
    setUniverseSettingsTab(u);
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    params.set("universe", u);
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?${params.toString()}`,
    );
  }, []);

  const handleTradingBrokerChange = useCallback((value: string) => {
    setTradingBroker(value);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem("trading_broker", value);
      } catch {
        // ignore
      }
    }
  }, []);

  const currentUniverseRow = universeSettings.find(
    (u) => u.universe_name === universeSettingsTab,
  );

  useEffect(() => {
    if (currentUniverseRow) {
      setUniverseSettingsDraft({
        capacity: currentUniverseRow.capacity,
        rank_frequency: currentUniverseRow.rank_frequency,
        refresh_interval_hours: currentUniverseRow.refresh_interval_hours,
      });
    } else {
      setUniverseSettingsDraft({});
    }
    setUniverseSettingsNotice(null);
  }, [universeSettingsTab, currentUniverseRow?.capacity, currentUniverseRow?.rank_frequency, currentUniverseRow?.refresh_interval_hours]);

  const handleSaveUniverseSettings = useCallback(async () => {
    if (!currentUniverseRow) return;
    setUniverseSettingsSaving(true);
    setUniverseSettingsNotice(null);
    try {
      const payload: Partial<UniverseSettings> = {};
      if (universeSettingsDraft.capacity != null && universeSettingsDraft.capacity !== currentUniverseRow.capacity) {
        payload.capacity = Number(universeSettingsDraft.capacity);
      }
      if (universeSettingsDraft.rank_frequency != null && universeSettingsDraft.rank_frequency !== currentUniverseRow.rank_frequency) {
        payload.rank_frequency = String(universeSettingsDraft.rank_frequency);
      }
      if (
        universeSettingsDraft.refresh_interval_hours != null &&
        universeSettingsDraft.refresh_interval_hours !== currentUniverseRow.refresh_interval_hours
      ) {
        payload.refresh_interval_hours = Number(universeSettingsDraft.refresh_interval_hours);
      }
      if (Object.keys(payload).length === 0) {
        setUniverseSettingsNotice("saved");
        return;
      }
      await api.updateUniverse(currentUniverseRow.universe_name, payload);
      const refreshed = await api.getUniverses();
      setUniverseSettings(refreshed);
      setUniverseSettingsNotice("saved");
    } catch {
      setUniverseSettingsNotice("failed");
    } finally {
      setUniverseSettingsSaving(false);
    }
  }, [currentUniverseRow, universeSettingsDraft]);

  useEffect(() => {
    setCategory("All");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeUniverse]);

  useEffect(() => {
    api
      .getPaperTrades({ status: "open", limit: 100 })
      .then((trades) => {
        const map = new Map<string, PaperTrade>();
        trades.forEach((t) => map.set(t.symbol.toUpperCase(), t));
        setOpenTradesMap(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (setups.length === 0) return;
    let cancelled = false;
    Promise.allSettled(
      setups.map((s) =>
        api.getManualStructureOverrides(s.symbol).then((list) => ({
          symbol: s.symbol,
          hasOverride: list.some((o) => o.is_active),
        })),
      ),
    ).then((results) => {
      if (cancelled) return;
      const withOverrides = new Set<string>();
      results.forEach((r) => {
        if (r.status === "fulfilled" && r.value.hasOverride) {
          withOverrides.add(r.value.symbol);
        }
      });
      setSymbolsWithOverrides(withOverrides);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setups.length]);

  useEffect(() => {
    setTopNDraft(String(scanSettings.binance_top_n));
  }, [scanSettings.binance_top_n]);

  useEffect(
    () => () => {
      if (settingsNoticeTimeoutRef.current != null) {
        clearTimeout(settingsNoticeTimeoutRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    setMounted(true);
  }, []);

  const skipFirstViewPersist = useRef(true);

  useEffect(() => {
    try {
      const v = localStorage.getItem(SCANNER_VIEW_STORAGE_KEY);
      if (v === "card" || v === "table") setListView(v);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (skipFirstViewPersist.current) {
      skipFirstViewPersist.current = false;
      return;
    }
    try {
      localStorage.setItem(SCANNER_VIEW_STORAGE_KEY, listView);
    } catch {
      // ignore
    }
  }, [listView]);

  useEffect(() => {
    try {
      if (localStorage.getItem(SCAN_SETTINGS_PANEL_STORAGE_KEY) === "true") {
        setScanSettingsPanelCollapsed(true);
      }
    } catch {
      // localStorage unavailable
    }
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SCANNER_FILTER_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        category?: string;
        sortBy?: "score" | "symbol";
        minScore?: number;
      };
      if (!searchParams.get("category") && parsed.category && CATEGORIES.includes(parsed.category)) {
        setCategory(parsed.category);
      }
      if (!searchParams.get("sort") && parsed.sortBy && (parsed.sortBy === "score" || parsed.sortBy === "symbol")) {
        setSortBy(parsed.sortBy);
      }
      if (typeof parsed.minScore === "number" && Number.isFinite(parsed.minScore)) {
        setMinScore(clampMinScoreStep5(parsed.minScore));
      }
    } catch {
      // localStorage unavailable (private mode/quota) or malformed data
    }
  }, [searchParams]);

  useEffect(() => {
    const nextCategory = searchParams.get("category");
    const nextSort = searchParams.get("sort");
    const normalizedCategory = nextCategory && CATEGORIES.includes(nextCategory) ? nextCategory : "All";
    const normalizedSort: "score" | "symbol" = nextSort === "symbol" ? "symbol" : "score";

    setCategory((current) => (current === normalizedCategory ? current : normalizedCategory));
    setSortBy((current) => (current === normalizedSort ? current : normalizedSort));
  }, [searchParams]);

  useEffect(() => {
    try {
      localStorage.setItem(
        SCANNER_FILTER_STORAGE_KEY,
        JSON.stringify({
          category,
          sortBy,
          minScore,
        }),
      );
    } catch {
      // non-fatal: skip persistence when storage is unavailable
    }
  }, [category, sortBy, minScore]);

  function updateQuery(nextCategory: string, nextSort: "score" | "symbol") {
    const params = new URLSearchParams(searchParams.toString());

    if (nextCategory === "All") {
      params.delete("category");
    } else {
      params.set("category", nextCategory);
    }

    if (nextSort === "score") {
      params.delete("sort");
    } else {
      params.set("sort", nextSort);
    }

    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function handleCategoryChange(nextCategory: string) {
    setCategory(nextCategory);
    updateQuery(nextCategory, sortBy);
  }

  function handleSortChange(nextSort: "score" | "symbol") {
    setSortBy(nextSort);
    updateQuery(category, nextSort);
  }

  const fetchData = useCallback(async () => {
    try {
      const [setupsData, healthData, settingsData] = await Promise.all([
        api.getSetups(),
        api.getHealth().catch(() => null),
        api.getScanSettings().catch(() => DEFAULT_SCAN_SETTINGS),
      ]);
      setSetups(Array.isArray(setupsData) ? setupsData : []);
      setHealth(healthData);
      setScanSettings({ ...DEFAULT_SCAN_SETTINGS, ...(settingsData ?? {}) });
      setIncludeInput((settingsData?.include_symbols ?? []).join(", "));
      setExcludeInput((settingsData?.exclude_symbols ?? []).join(", "));
      setScanTime(new Date());
      setError(null);
    } catch {
      setSetups([]);
      setHealth(null);
      setError("API unavailable");
    } finally {
      setSettingsLoading(false);
      setLoading(false);
    }
  }, []);

  const fetchDataRef = useRef(fetchData);
  fetchDataRef.current = fetchData;

  async function handleDropSetup(symbol: string) {
    setDroppingSymbol(symbol);
    try {
      await api.deleteSetup(symbol);
      await fetchDataRef.current();
      try {
        setHealth(await api.getHealth());
      } catch {
        setHealth(null);
      }
    } catch {
      setError("API unavailable");
    } finally {
      setDroppingSymbol(null);
    }
  }

  async function handleSaveSettings() {
    if (settingsNoticeTimeoutRef.current != null) {
      clearTimeout(settingsNoticeTimeoutRef.current);
      settingsNoticeTimeoutRef.current = null;
    }
    setSettingsSaving(true);
    setSettingsNotice(null);
    try {
      const binanceTopN = parseBinanceTopNDraft(topNDraft, scanSettings.binance_top_n);
      const withCorr = scanSettings as ScanSettings & { enable_correlation_filter?: boolean };
      const payload = {
        binance_top_n: binanceTopN,
        brokers: [...scanSettings.brokers],
        deriv_categories: [...scanSettings.deriv_categories],
        include_symbols: parseSymbolText(includeInput),
        exclude_symbols: parseSymbolText(excludeInput),
        score_weights: { ...scanSettings.score_weights },
        scoring_profile: scanSettings.scoring_profile,
        scoring_layer_weights: { ...scanSettings.scoring_layer_weights },
        retracement_bonus: scanSettings.retracement_bonus,
        enable_correlation_filter: Boolean(withCorr.enable_correlation_filter),
        universe_scan_frequency: scanSettings.universe_scan_frequency,
        active_refresh_hours: scanSettings.active_refresh_hours,
        deep_analysis_refresh_hours: scanSettings.deep_analysis_refresh_hours,
        non_top50_analysis_depth: scanSettings.non_top50_analysis_depth,
        category_min_slots: { ...scanSettings.category_min_slots },
        deriv_category_overrides: { ...scanSettings.deriv_category_overrides },
      } as ScanSettings;
      const saved = await api.saveScanSettings(payload);
      setScanSettings({ ...DEFAULT_SCAN_SETTINGS, ...saved });
      setIncludeInput((saved.include_symbols ?? []).join(", "));
      setExcludeInput((saved.exclude_symbols ?? []).join(", "));
      setTopNDraft(String(saved.binance_top_n));
      setSettingsNotice("saved");
      settingsNoticeTimeoutRef.current = setTimeout(() => {
        setSettingsNotice(null);
        settingsNoticeTimeoutRef.current = null;
      }, 2000);
    } catch {
      setSettingsNotice("failed");
      settingsNoticeTimeoutRef.current = setTimeout(() => {
        setSettingsNotice(null);
        settingsNoticeTimeoutRef.current = null;
      }, 3000);
    } finally {
      setSettingsSaving(false);
    }
  }

  function toggleScanSettingsPanel() {
    setScanSettingsPanelCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SCAN_SETTINGS_PANEL_STORAGE_KEY, String(next));
      } catch {
        // non-fatal
      }
      return next;
    });
  }

  function openRankConfirm() {
    setRankConfirmOpen(true);
  }

  async function handleRankProceed() {
    setRankConfirmOpen(false);
    setIsTriggeringRank(true);
    setError(null);
    try {
      await api.rankUniverseSpecific(activeUniverse);
      const s = await api.getUniverseRankingStatus();
      setUniverseRankingStatus(s);
      if (s.in_progress) {
        setRankingPollActive(true);
      } else {
        await fetchData();
        try {
          setHealth(await api.getHealth());
        } catch {
          setHealth(null);
        }
      }
    } catch {
      setError("API unavailable");
      setUniverseRankingStatus(null);
      setRankingPollActive(false);
    } finally {
      setIsTriggeringRank(false);
    }
  }

  useEffect(() => {
    if (!rankConfirmOpen) return;
    let cancelled = false;
    setRankDialogLogs(null);
    setRankDialogLoading(true);
    void (async () => {
      try {
        const logs = await api.getScanJobLog();
        if (!cancelled) setRankDialogLogs(Array.isArray(logs) ? logs : []);
      } catch {
        if (!cancelled) setRankDialogLogs([]);
      } finally {
        if (!cancelled) setRankDialogLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rankConfirmOpen]);

  useEffect(() => {
    if (!rankingPollActive) return;
    let cancelled = false;
    async function tick() {
      try {
        const s = await api.getUniverseRankingStatus();
        if (cancelled) return;
        setUniverseRankingStatus(s);
        if (!s.in_progress) {
          setRankingPollActive(false);
          setRankingJustCompleted(true);
          setTimeout(() => setRankingJustCompleted(false), 3000);
          await fetchDataRef.current();
          try {
            setHealth(await api.getHealth());
          } catch {
            setHealth(null);
          }
        }
      } catch {
        if (!cancelled) setRankingPollActive(false);
      }
    }
    void tick();
    const id = setInterval(() => void tick(), 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [rankingPollActive]);

  useEffect(() => {
    void fetchData();
    const dataInterval = setInterval(() => void fetchData(), 30000);
    return () => clearInterval(dataInterval);
  }, [fetchData]);

  useEffect(() => {
    const updateCountdown = () => {
      if (!health?.next_scan) {
        setNextScanCountdown("--:--");
        return;
      }

      const nextMs = new Date(health.next_scan).getTime();
      if (!Number.isFinite(nextMs)) {
        setNextScanCountdown("--:--");
        return;
      }

      setNextScanCountdown(formatCountdown(nextMs - Date.now()));
    };

    updateCountdown();
    const countdownInterval = setInterval(updateCountdown, 1000);
    return () => clearInterval(countdownInterval);
  }, [health?.next_scan]);

  const filteredByUniverse = setups.filter((s) => {
    const u = (s.universe as UniverseKey | null | undefined) ||
      _inferUniverseFrontend(s.symbol, s.category);
    return u === activeUniverse;
  });

  const availableCategories = UNIVERSE_CATEGORIES[activeUniverse] ?? ["All"];

  const filtered = filteredByUniverse
    .filter((s) => category === "All" || normalizeCategory(s.category) === category)
    .filter((s) => {
      if (stateFilter === "ALL") return true;
      return s.fsm_state === stateFilter;
    })
    .filter((s) => passesDepthFilter(s, depthFilter))
    .filter((s) => {
      if (brokerFilter === "ALL") return true;
      return setupBrokerUpper(s) === brokerFilter;
    })
    .filter((s) => s.trend_score >= minScore)
    .sort((a, b) =>
      sortBy === "score"
        ? b.trend_score - a.trend_score
        : String(a.symbol || "").localeCompare(String(b.symbol || "")),
    );

  const highConviction = filteredByUniverse.filter(s => s.trend_score >= 30).length;
  const inRetracement = filteredByUniverse.filter(s => s.fsm_state === "MONITORING").length;
  const inImpulse = filteredByUniverse.filter(s => s.fsm_state !== "MONITORING" && s.current_phase === "impulse").length;
  const derivedLastScan = setups.length > 0
    ? formatTime(setups.reduce((a, b) => new Date(a.last_checked_at) > new Date(b.last_checked_at) ? a : b).last_checked_at)
    : "--:--";
  const healthLastScanIso = health?.last_scan || null;
  const lastScan = healthLastScanIso ? formatTime(healthLastScanIso) : derivedLastScan;
  const isLastScanStale = healthLastScanIso
    ? (Date.now() - new Date(healthLastScanIso).getTime()) > (6 * 60 * 60 * 1000)
    : false;

  const tableGridColumns = "28px 44px 200px 80px 90px 160px 80px minmax(100px,1fr) 72px";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-base)", fontFamily: "'IBM Plex Mono', monospace", color: "var(--text-primary)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 20px", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-elevated)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 10, color: "#3A3D48", letterSpacing: "0.1em" }}>MARKET SCANNER</span>
          <span style={{ fontSize: 10, color: "#2A2D36" }}>v2.4</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <LiveStatusRow
            variant="live"
            showSecondaryBusyDot={universeRankBusy}
            label="LIVE"
            rightSlot={
              <>
                <LiveStatusMeta>NEXT SCAN: {nextScanCountdown}</LiveStatusMeta>
                <LiveStatusMeta dim>{mounted ? scanTime.toUTCString().slice(17, 25) : "--:--:--"} UTC</LiveStatusMeta>
              </>
            }
          />
          <Tooltip content="Score and rank the full universe (manual job)">
            <button
              onClick={openRankConfirm}
              disabled={universeRankBusy}
              style={{
                padding: "6px 14px",
                border: "1px solid #2A2D36",
                borderRadius: 2,
                fontSize: 10,
                color: universeRankBusy ? "#A4A7B2" : "#6B6F7A",
                background: "transparent",
                cursor: universeRankBusy ? "wait" : "pointer",
                letterSpacing: "0.06em",
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              {universeRankBusy ? (
                <>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      border: "2px solid #2A2D36",
                      borderTopColor: "#F5A623",
                      animation: "scanner-spin 0.8s linear infinite",
                    }}
                  />
                  RANKING...
                </>
              ) : (
                RANK_BUTTON_LABELS[activeUniverse] ?? "RANK"
              )}
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Universe Ranking Progress */}
      {(universeRankingStatus?.in_progress || rankingJustCompleted) && (
        <div style={{ padding: "8px 20px", borderBottom: "1px solid #1C1E24", background: "#0D0F14" }}>
          {rankingJustCompleted && !universeRankingStatus?.in_progress ? (
            <div style={{ fontSize: 10, color: "#4CAF7D", letterSpacing: "0.1em", fontFamily: "'IBM Plex Mono', monospace" }}>
              RANKING COMPLETE
            </div>
          ) : (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={{ fontSize: 10, color: "#787B86", letterSpacing: "0.08em", fontFamily: "'IBM Plex Mono', monospace" }}>
                  {universeRankingStatus?.symbols_scored ?? 0} / {universeRankingStatus?.total_symbols ?? 0} MARKETS SCORED
                </span>
                {universeRankingStatus?.estimated_seconds_remaining != null && (
                  <span style={{ fontSize: 9, color: "#4A4D58", letterSpacing: "0.06em", fontFamily: "'IBM Plex Mono', monospace" }}>
                    ~{formatEtaSeconds(universeRankingStatus.estimated_seconds_remaining)} REMAINING
                  </span>
                )}
              </div>
              <div style={{ width: "100%", height: 2, background: "#1E222D" }}>
                <div
                  style={{
                    height: 2,
                    background: "#F5A623",
                    width: universeRankingStatus?.total_symbols
                      ? `${Math.min(100, ((universeRankingStatus.symbols_scored ?? 0) / universeRankingStatus.total_symbols) * 100)}%`
                      : "0%",
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
              {universeRankingStatus?.current_symbol && (
                <div style={{ marginTop: 4, fontSize: 9, color: "#4A4D58", letterSpacing: "0.06em", fontFamily: "'IBM Plex Mono', monospace" }}>
                  CURRENT: {universeRankingStatus.current_symbol}
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div style={{ borderBottom: "1px solid var(--border-default)", background: "var(--bg-surface)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "8px 20px",
            borderBottom: scanSettingsPanelCollapsed ? undefined : "1px solid var(--border-subtle)",
          }}
        >
          <div
            style={{
              fontFamily: SCAN_SETTINGS_FONT,
              fontSize: 9,
              textTransform: "uppercase",
              letterSpacing: "0.12em",
              color: "#787B86",
            }}
          >
            SCAN SETTINGS
          </div>
          <PanelEdgeCollapseToggle
            variant="horizontal"
            expanded={!scanSettingsPanelCollapsed}
            onClick={toggleScanSettingsPanel}
            aria-expanded={!scanSettingsPanelCollapsed}
            aria-controls="scanner-scan-settings"
            title={scanSettingsPanelCollapsed ? "Show scan settings" : "Hide scan settings"}
            aria-label={scanSettingsPanelCollapsed ? "Show scan settings" : "Hide scan settings"}
          />
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateRows: scanSettingsPanelCollapsed ? "0fr" : "1fr",
            transition: "grid-template-rows 280ms ease",
          }}
        >
          <div style={{ minHeight: 0 }}>
            <div
              id="scanner-scan-settings"
              className="scanner-scan-settings-panel"
              style={{
                padding: "10px 20px 12px",
                opacity: scanSettingsPanelCollapsed ? 0 : 1,
                pointerEvents: scanSettingsPanelCollapsed ? "none" : "auto",
                fontFamily: SCAN_SETTINGS_FONT,
                maxHeight: scanSettingsPanelCollapsed ? 0 : "min(70vh, 600px)",
                overflowY: "auto",
                overflowX: "hidden",
                transition: "opacity 200ms ease, max-height 280ms ease",
              }}
              aria-hidden={scanSettingsPanelCollapsed}
            >
              <style>{`
                .scanner-scan-settings-panel input[type="number"],
                .scanner-scan-settings-panel textarea {
                  accent-color: #F5A623;
                }
                .scanner-scan-settings-panel input:focus-visible,
                .scanner-scan-settings-panel textarea:focus-visible,
                .scanner-scan-settings-panel button.scanner-scan-settings-save:focus-visible {
                  outline: 1px solid #F5A623;
                  outline-offset: 1px;
                }
                .scanner-scan-settings-save {
                  width: 100%;
                  font-family: ${SCAN_SETTINGS_FONT};
                  font-size: 11px;
                  font-weight: 600;
                  letter-spacing: 0.1em;
                  text-transform: uppercase;
                  padding: 10px 12px;
                  border: 1px solid #F5A623;
                  background: transparent;
                  color: #F5A623;
                  border-radius: 0;
                  cursor: pointer;
                }
                .scanner-scan-settings-save:hover:not(:disabled) {
                  background: #F5A623;
                  color: #0D0F14;
                }
                .scanner-scan-settings-save:disabled {
                  opacity: 0.5;
                  cursor: not-allowed;
                }
                @media (max-width: 900px) {
                  .scanner-scan-settings-grid { grid-template-columns: 1fr !important; }
                }
                .scanner-scan-settings-panel::-webkit-scrollbar {
                  width: 4px;
                }
                .scanner-scan-settings-panel::-webkit-scrollbar-track {
                  background: transparent;
                }
                .scanner-scan-settings-panel::-webkit-scrollbar-thumb {
                  background: #2A2E39;
                  border-radius: 2px;
                }
                .scanner-scan-settings-panel::-webkit-scrollbar-thumb:hover {
                  background: #363A45;
                }
              `}</style>
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div
                  className="scanner-scan-settings-grid"
                  style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr", gap: 12, alignItems: "start" }}
                >
                  <div style={{ display: "grid", gap: 10 }}>
                    <label style={{ display: "grid", gap: 6 }}>
                      <Tooltip content="Maximum symbols fetched from Binance by 24h volume before scoring">
                        <span style={{ ...scanSettingsFieldLabelStyle, cursor: "help" }}>TOP N SYMBOLS</span>
                      </Tooltip>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={topNDraft}
                        onChange={(e) => setTopNDraft(e.target.value)}
                        onBlur={() => {
                          const n = parseInt(topNDraft, 10);
                          const v = Number.isFinite(n) ? Math.max(10, Math.min(1000, n)) : scanSettings.binance_top_n;
                          setScanSettings((s) => ({ ...s, binance_top_n: v }));
                          setTopNDraft(String(v));
                        }}
                        style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                      />
                      <span style={scanSettingsHintStyle}>Ranked by 24h volume</span>
                    </label>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      {(["binance", "deriv", "yfinance"] as const).map((broker) => {
                        const active = scanSettings.brokers.includes(broker);
                        return (
                          <button
                            key={broker}
                            type="button"
                            onClick={() => setScanSettings((s) => ({
                              ...s,
                              brokers: active ? s.brokers.filter((b) => b !== broker) : [...s.brokers, broker],
                            }))}
                            style={{
                              padding: "4px 12px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                            }}
                          >
                            {broker.toUpperCase()}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 10 }}>
                    <div style={scanSettingsFieldLabelStyle}>MARKET CATEGORIES</div>
                    <div
                      style={{
                        fontSize: 8,
                        color: "#4A4D58",
                        fontFamily: "'IBM Plex Mono', monospace",
                        letterSpacing: "0.06em",
                        marginBottom: 4,
                      }}
                    >
                      Filter which Deriv market types enter the scan universe
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                        gap: 6,
                      }}
                    >
                      {MARKET_CATEGORIES.map((cat) => {
                        const active = scanSettings.deriv_categories.includes(cat);
                        return (
                          <button
                            key={cat}
                            type="button"
                            onClick={() => setScanSettings((s) => ({
                              ...s,
                              deriv_categories: active
                                ? s.deriv_categories.filter((c) => c !== cat)
                                : [...s.deriv_categories, cat],
                            }))}
                            style={{
                              padding: "5px 6px",
                              fontSize: 9,
                              letterSpacing: "0.06em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                              textTransform: "uppercase",
                              width: "100%",
                              boxSizing: "border-box",
                            }}
                          >
                            {cat.toUpperCase()}
                          </button>
                        );
                      })}
                    </div>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={scanSettingsFieldLabelStyle}>INCLUDE SYMBOLS</span>
                      <textarea
                        rows={2}
                        value={includeInput}
                        onChange={(e) => setIncludeInput(e.target.value)}
                        placeholder="BTCUSDT, ETHUSDT"
                        style={{
                          ...scanSettingsInputBase,
                          resize: "vertical",
                          minHeight: 48,
                          color: "#D1D4DC",
                        }}
                      />
                      <span style={scanSettingsHintStyle}>Comma or newline separated; merged with scan universe</span>
                    </label>
                    <label style={{ display: "grid", gap: 6 }}>
                      <span style={scanSettingsFieldLabelStyle}>EXCLUDE SYMBOLS</span>
                      <textarea
                        rows={2}
                        value={excludeInput}
                        onChange={(e) => setExcludeInput(e.target.value)}
                        placeholder="BTCUSDT"
                        style={{
                          ...scanSettingsInputBase,
                          resize: "vertical",
                          minHeight: 48,
                          color: "#D1D4DC",
                        }}
                      />
                      <span style={scanSettingsHintStyle}>Comma or newline separated; exclusions win over includes</span>
                    </label>
                  </div>
                  <div style={{ display: "grid", gap: 10 }}>
                    <div style={scanSettingsFieldLabelStyle}>SCORING</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {SCORING_PROFILE_OPTIONS.map((profile) => {
                        const active = scanSettings.scoring_profile === profile;
                        return (
                          <button
                            key={profile}
                            type="button"
                            onClick={() => setScanSettings((s) => ({ ...s, scoring_profile: profile }))}
                            style={{
                              padding: "4px 10px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                              textTransform: "uppercase",
                            }}
                          >
                            {profile}
                          </button>
                        );
                      })}
                      <button
                        type="button"
                        onClick={() => setScanSettings((s) => ({ ...s, scoring_profile: "custom" }))}
                        style={{
                          padding: "4px 10px",
                          fontSize: 10,
                          letterSpacing: "0.08em",
                          fontFamily: SCAN_SETTINGS_FONT,
                          fontWeight: scanSettings.scoring_profile === "custom" ? 700 : 400,
                          border: `1px solid ${scanSettings.scoring_profile === "custom" ? "#F5A623" : "#363A45"}`,
                          borderRadius: 0,
                          background: scanSettings.scoring_profile === "custom" ? "#F5A623" : "#1E222D",
                          color: scanSettings.scoring_profile === "custom" ? "#0D0F14" : "#787B86",
                          cursor: "pointer",
                          textTransform: "uppercase",
                        }}
                      >
                        CUSTOM
                      </button>
                    </div>
                    {scanSettings.scoring_profile === "custom" ? (
                      <>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={scanSettingsFieldLabelStyle}>STATE WEIGHT</span>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.01}
                            value={scanSettings.scoring_layer_weights.state_weight}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              if (!Number.isFinite(v)) return;
                              setScanSettings((s) => ({
                                ...s,
                                scoring_layer_weights: {
                                  ...s.scoring_layer_weights,
                                  state_weight: v,
                                },
                              }));
                            }}
                            style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={scanSettingsFieldLabelStyle}>OPPORTUNITY WEIGHT</span>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.01}
                            value={scanSettings.scoring_layer_weights.opportunity_weight}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              if (!Number.isFinite(v)) return;
                              setScanSettings((s) => ({
                                ...s,
                                scoring_layer_weights: {
                                  ...s.scoring_layer_weights,
                                  opportunity_weight: v,
                                },
                              }));
                            }}
                            style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                          />
                        </label>
                        <label style={{ display: "grid", gap: 6 }}>
                          <span style={scanSettingsFieldLabelStyle}>STRUCTURE WEIGHT</span>
                          <input
                            type="number"
                            min={0}
                            max={1}
                            step={0.01}
                            value={scanSettings.scoring_layer_weights.structure_weight}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              if (!Number.isFinite(v)) return;
                              setScanSettings((s) => ({
                                ...s,
                                scoring_layer_weights: {
                                  ...s.scoring_layer_weights,
                                  structure_weight: v,
                                },
                              }));
                            }}
                            style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                          />
                        </label>
                        <div style={scanSettingsHintStyle}>Weights are normalised automatically</div>
                      </>
                    ) : null}
                    <label style={{ display: "grid", gap: 6 }}>
                      <Tooltip content="Additive bonus points for markets currently in retracement phase">
                        <span style={{ ...scanSettingsFieldLabelStyle, cursor: "help" }}>RETRACEMENT BONUS</span>
                      </Tooltip>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={scanSettings.retracement_bonus}
                        onChange={(e) => setScanSettings((s) => ({ ...s, retracement_bonus: Number(e.target.value || 0) }))}
                        style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                      />
                    </label>
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 12, width: "100%" }}>
                  <button
                    type="button"
                    onClick={async () => {
                      await fetch(`${API_BASE}/api/setups/refresh-yfinance-candles`, { method: "POST" });
                      setYfinanceRefreshNotice("YFINANCE CANDLE REFRESH STARTED");
                      setTimeout(() => setYfinanceRefreshNotice(null), 4000);
                    }}
                    style={{
                      padding: "6px 14px",
                      fontSize: 10,
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      background: "#1E222D",
                      border: "1px solid #363A45",
                      color: "#D1D4DC",
                      cursor: "pointer",
                      fontFamily: '"IBM Plex Mono", monospace',
                      justifySelf: "start",
                    }}
                  >
                    REFRESH YFINANCE CANDLES
                  </button>
                  {yfinanceRefreshNotice && (
                    <div
                      style={{
                        marginTop: 6,
                        fontSize: 9,
                        fontFamily: "'IBM Plex Mono', monospace",
                        color: "#26A69A",
                        letterSpacing: "0.08em",
                      }}
                    >
                      ● {yfinanceRefreshNotice}
                    </div>
                  )}
                  <div style={scanSettingsFieldLabelStyle}>SCAN SCHEDULE</div>
                  <div style={{ display: "grid", gap: 8 }}>
                    <Tooltip content="How often the full universe is re-scored and top N promoted">
                      <span style={{ ...scanSettingsFieldLabelStyle, cursor: "help", display: "inline-block" }}>UNIVERSE SCAN</span>
                    </Tooltip>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {UNIVERSE_SCAN_FREQUENCIES.map((freq) => {
                        const active = scanSettings.universe_scan_frequency === freq;
                        return (
                          <button
                            key={freq}
                            type="button"
                            onClick={() => setScanSettings((s) => ({ ...s, universe_scan_frequency: freq }))}
                            style={{
                              padding: "4px 12px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                              textTransform: "uppercase",
                            }}
                          >
                            {freq}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    <Tooltip content="How often top N setups recompute candidate impulse and market state">
                      <span style={{ ...scanSettingsFieldLabelStyle, cursor: "help", display: "inline-block" }}>ACTIVE REFRESH</span>
                    </Tooltip>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {ACTIVE_REFRESH_HOUR_OPTIONS.map((h) => {
                        const active = scanSettings.active_refresh_hours === h;
                        const label = h === 24 ? "24H" : `${h}H`;
                        return (
                          <button
                            key={h}
                            type="button"
                            onClick={() => setScanSettings((s) => ({ ...s, active_refresh_hours: h }))}
                            style={{
                              padding: "4px 12px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                            }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    <Tooltip content="How often global structure, prime impulse, and walker recompute">
                      <span style={{ ...scanSettingsFieldLabelStyle, cursor: "help", display: "inline-block" }}>DEEP ANALYSIS REFRESH</span>
                    </Tooltip>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {DEEP_ANALYSIS_REFRESH_OPTIONS.map((h) => {
                        const active = scanSettings.deep_analysis_refresh_hours === h;
                        const label = `${h}H`;
                        return (
                          <button
                            key={h}
                            type="button"
                            onClick={() => setScanSettings((s) => ({ ...s, deep_analysis_refresh_hours: h }))}
                            style={{
                              padding: "4px 12px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                            }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 8 }}>
                    <span style={scanSettingsFieldLabelStyle}>NON-TOP-N DEPTH</span>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {NON_TOP50_DEPTH_OPTIONS.map(({ value, label }) => {
                        const active = scanSettings.non_top50_analysis_depth === value;
                        return (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setScanSettings((s) => ({ ...s, non_top50_analysis_depth: value }))}
                            style={{
                              padding: "4px 12px",
                              fontSize: 10,
                              letterSpacing: "0.08em",
                              fontFamily: SCAN_SETTINGS_FONT,
                              fontWeight: active ? 700 : 400,
                              border: `1px solid ${active ? "#F5A623" : "#363A45"}`,
                              borderRadius: 0,
                              background: active ? "#F5A623" : "#1E222D",
                              color: active ? "#0D0F14" : "#787B86",
                              cursor: "pointer",
                            }}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 10, width: "100%" }}>
                  <div style={scanSettingsFieldLabelStyle}>CATEGORY MINIMUMS</div>
                  <div style={scanSettingsHintStyle}>Minimum guaranteed slots per universe scan</div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "minmax(100px, 1fr) minmax(72px, 88px)",
                      gap: "8px 12px",
                      alignItems: "center",
                    }}
                  >
                    {CATEGORY_MIN_ROWS.map(({ key: slotKey, label }) => (
                      <Fragment key={slotKey}>
                        <span style={{ ...scanSettingsFieldLabelStyle, letterSpacing: "0.06em" }}>{label}</span>
                        <input
                          type="text"
                          inputMode="numeric"
                          value={String(scanSettings.category_min_slots[slotKey])}
                          onChange={(e) => {
                            const t = e.target.value.replace(/[^\d]/g, "");
                            const n = t === "" ? 0 : parseInt(t, 10);
                            const v = Number.isFinite(n) ? Math.max(0, Math.min(50, n)) : 0;
                            setScanSettings((s) => ({
                              ...s,
                              category_min_slots: { ...s.category_min_slots, [slotKey]: v },
                            }));
                          }}
                          onBlur={() => {
                            setScanSettings((s) => {
                              const raw = s.category_min_slots[slotKey];
                              const n = typeof raw === "number" ? raw : parseInt(String(raw), 10);
                              const v = Number.isFinite(n) ? Math.max(0, Math.min(50, n)) : 0;
                              return {
                                ...s,
                                category_min_slots: { ...s.category_min_slots, [slotKey]: v },
                              };
                            });
                          }}
                          style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                        />
                      </Fragment>
                    ))}
                  </div>
                </div>

                <div
                  style={{
                    borderTop: "1px solid #1E222D",
                    paddingTop: 12,
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <div
                    style={{
                      fontFamily: SCAN_SETTINGS_FONT,
                      fontSize: 9,
                      textTransform: "uppercase",
                      letterSpacing: "0.12em",
                      color: "#787B86",
                    }}
                  >
                    UNIVERSE SETTINGS
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {UNIVERSE_TABS.map((tab) => (
                      <button
                        key={`uni-edit-tab-${tab.key}`}
                        type="button"
                        onClick={() => setUniverseSettingsTab(tab.key)}
                        style={{
                          padding: "4px 10px",
                          fontSize: 9,
                          letterSpacing: "0.08em",
                          fontFamily: SCAN_SETTINGS_FONT,
                          fontWeight: universeSettingsTab === tab.key ? 700 : 400,
                          border: `1px solid ${universeSettingsTab === tab.key ? "#F5A623" : "#363A45"}`,
                          background: universeSettingsTab === tab.key ? "#F5A623" : "#1E222D",
                          color: universeSettingsTab === tab.key ? "#0D0F14" : "#787B86",
                          cursor: "pointer",
                          textTransform: "uppercase",
                        }}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>
                  {currentUniverseRow ? (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr 1fr auto",
                        gap: 10,
                        alignItems: "end",
                      }}
                    >
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={scanSettingsFieldLabelStyle}>CAPACITY</span>
                        <input
                          type="number"
                          min={1}
                          max={1000}
                          value={universeSettingsDraft.capacity ?? currentUniverseRow.capacity}
                          onChange={(e) => {
                            const n = parseInt(e.target.value, 10);
                            setUniverseSettingsDraft((d) => ({
                              ...d,
                              capacity: Number.isFinite(n) ? Math.max(1, Math.min(1000, n)) : d.capacity,
                            }));
                          }}
                          style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                        />
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={scanSettingsFieldLabelStyle}>RANK FREQUENCY</span>
                        <select
                          value={universeSettingsDraft.rank_frequency ?? currentUniverseRow.rank_frequency}
                          onChange={(e) =>
                            setUniverseSettingsDraft((d) => ({
                              ...d,
                              rank_frequency: e.target.value,
                            }))
                          }
                          style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                        >
                          {UNIVERSE_RANK_FREQUENCY_OPTIONS.map((opt) => (
                            <option key={opt} value={opt} style={{ background: "#131722", color: "#D1D4DC" }}>
                              {opt.toUpperCase()}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label style={{ display: "grid", gap: 6 }}>
                        <span style={scanSettingsFieldLabelStyle}>REFRESH (HOURS)</span>
                        <select
                          value={String(universeSettingsDraft.refresh_interval_hours ?? currentUniverseRow.refresh_interval_hours)}
                          onChange={(e) =>
                            setUniverseSettingsDraft((d) => ({
                              ...d,
                              refresh_interval_hours: parseInt(e.target.value, 10),
                            }))
                          }
                          style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                        >
                          {UNIVERSE_REFRESH_HOUR_OPTIONS.map((opt) => (
                            <option key={opt} value={opt} style={{ background: "#131722", color: "#D1D4DC" }}>
                              {opt}h
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        onClick={() => void handleSaveUniverseSettings()}
                        disabled={universeSettingsSaving}
                        style={{
                          padding: "8px 14px",
                          fontFamily: SCAN_SETTINGS_FONT,
                          fontSize: 10,
                          letterSpacing: "0.1em",
                          textTransform: "uppercase",
                          border: "1px solid #F5A623",
                          background: "transparent",
                          color: "#F5A623",
                          cursor: universeSettingsSaving ? "not-allowed" : "pointer",
                          opacity: universeSettingsSaving ? 0.5 : 1,
                          borderRadius: 0,
                        }}
                      >
                        {universeSettingsSaving ? "SAVING..." : "SAVE"}
                      </button>
                    </div>
                  ) : (
                    <div style={{ ...scanSettingsHintStyle, color: "#4A4D58" }}>
                      Universe settings unavailable — backend may not be reachable.
                    </div>
                  )}
                  {universeSettingsNotice === "saved" ? (
                    <div
                      style={{
                        fontFamily: SCAN_SETTINGS_FONT,
                        fontSize: 9,
                        color: "#F5A623",
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                      }}
                    >
                      UNIVERSE SETTINGS SAVED
                    </div>
                  ) : null}
                  {universeSettingsNotice === "failed" ? (
                    <div
                      style={{
                        fontFamily: SCAN_SETTINGS_FONT,
                        fontSize: 9,
                        color: "#EF5350",
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                      }}
                    >
                      UNIVERSE SAVE FAILED
                    </div>
                  ) : null}
                  <label style={{ display: "grid", gap: 6, marginTop: 4 }}>
                    <span style={scanSettingsFieldLabelStyle}>TRADING BROKER</span>
                    <input
                      type="text"
                      value={tradingBroker}
                      onChange={(e) => handleTradingBrokerChange(e.target.value)}
                      placeholder="FTMO"
                      style={{ ...scanSettingsInputBase, width: "100%", boxSizing: "border-box" }}
                    />
                    <span style={scanSettingsHintStyle}>
                      Multi-Asset Broker (display only)
                    </span>
                  </label>
                </div>

                <button
                  type="button"
                  className="scanner-scan-settings-save"
                  onClick={handleSaveSettings}
                  disabled={settingsSaving || settingsLoading}
                >
                  {settingsSaving ? "SAVING..." : "SAVE SETTINGS"}
                </button>
                {settingsNotice === "saved" ? (
                  <div
                    style={{
                      fontFamily: SCAN_SETTINGS_FONT,
                      fontSize: 9,
                      color: "#F5A623",
                      textAlign: "center",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    SETTINGS SAVED
                  </div>
                ) : null}
                {settingsNotice === "failed" ? (
                  <div
                    style={{
                      fontFamily: SCAN_SETTINGS_FONT,
                      fontSize: 9,
                      color: "#EF5350",
                      textAlign: "center",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    SAVE FAILED
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Universe Tab Bar */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: "1px solid #1E222D",
          background: "#0D0F14",
          padding: "0 20px",
          alignItems: "center",
        }}
      >
        {UNIVERSE_TABS.map((tab) => (
          <button
            key={`universe-tab-${tab.key}`}
            type="button"
            onClick={() => handleUniverseChange(tab.key)}
            style={{
              padding: "12px 20px",
              background: "transparent",
              border: "none",
              borderBottom: activeUniverse === tab.key
                ? "2px solid #F5A623"
                : "2px solid transparent",
              color: activeUniverse === tab.key ? "#F5A623" : "#4A4D58",
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
              transition: "color 0.1s, border-color 0.1s",
            }}
          >
            <span style={{ fontSize: 12 }}>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
        {activeUniverse === "multi_asset" && (
          <span
            style={{
              marginLeft: 12,
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 8,
              color: "#4A4D58",
              letterSpacing: "0.08em",
              padding: "2px 8px",
              border: "1px solid #1E222D",
              borderRadius: 2,
            }}
          >
            BROKER: {tradingBroker}
          </span>
        )}
      </div>

      {/* KPI Strip */}
      <div style={{ display: "flex", padding: "16px 0", borderBottom: "1px solid var(--border-default)", background: "var(--bg-surface)" }}>
        <MetricBlock label="ACTIVE SETUPS" value={formatLocaleInt(filteredByUniverse.length)} color="var(--text-primary)" />
        <MetricBlock label="HIGH CONVICTION" value={formatLocaleInt(highConviction)} />
        <MetricBlock label="IN RETRACEMENT" value={formatLocaleInt(inRetracement)} />
        <MetricBlock label="IN IMPULSE" value={formatLocaleInt(inImpulse)} />
        <MetricBlock
          label="LAST SCAN"
          color={isLastScanStale ? "#F5A623" : undefined}
          valueNode={
            mounted && healthLastScanIso ? (
              <RelativeTimeWithTooltip
                iso={healthLastScanIso}
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  color: isLastScanStale ? "#F5A623" : "var(--text-primary)",
                }}
              />
            ) : (
              <span style={{ color: isLastScanStale ? "#F5A623" : "var(--text-primary)" }}>{mounted ? lastScan : "--:--"}</span>
            )
          }
        />
      </div>

      {/* Unified filters */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          gap: 0,
          padding: "10px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          background: "var(--bg-surface)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={filterLabelStyle}>CATEGORY</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {availableCategories.map((cat) => (
              <FilterPill
                key={`category-${cat}`}
                active={category === cat}
                onClick={() => handleCategoryChange(cat)}
                tooltip={`Filter scanner by ${cat}`}
              >
                {cat}
              </FilterPill>
            ))}
          </div>
        </div>
        <FilterDivider />
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={filterLabelStyle}>BROKER</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {BROKER_FILTER_OPTIONS.map((value) => (
              <FilterPill
                key={`broker-${value}`}
                active={brokerFilter === value}
                onClick={() => setBrokerFilter(value)}
                tooltip={value === "ALL" ? "All brokers" : `Filter by ${value}`}
              >
                {value}
              </FilterPill>
            ))}
          </div>
        </div>
        <FilterDivider />
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={filterLabelStyle}>STATE</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {STATE_FILTER_OPTIONS.map((value) => (
              <FilterPill
                key={`state-${value}`}
                active={stateFilter === value}
                onClick={() => setStateFilter(value)}
                tooltip={`Filter by ${value.toLowerCase()} state`}
              >
                {value}
              </FilterPill>
            ))}
          </div>
        </div>
        <FilterDivider />
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={filterLabelStyle}>DEPTH</span>
          <select
            value={depthFilter}
            onChange={(e) => setDepthFilter(e.target.value as DepthFilterOption)}
            style={{
              fontSize: 10,
              padding: "4px 8px",
              border: "1px solid #2A2E39",
              borderRadius: 2,
              background: "#1E222D",
              color: "#787B86",
              fontFamily: "'IBM Plex Mono', monospace",
              letterSpacing: "0.08em",
              outline: "none",
              minWidth: 128,
              cursor: "pointer",
            }}
          >
            {DEPTH_FILTER_OPTIONS.map((option) => (
              <option key={option} value={option} style={{ background: "#131722", color: "#D1D4DC" }}>
                {option}
              </option>
            ))}
          </select>
        </div>
        <FilterDivider />
        <div style={{ display: "flex", flexDirection: "column", minWidth: 88 }}>
          <span style={filterLabelStyle}>SCORE ≥</span>
          <input
            type="number"
            min={0}
            max={100}
            step={5}
            value={minScore}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isFinite(v)) return;
              setMinScore(clampMinScoreStep5(v));
            }}
            onBlur={() => setMinScore((v) => clampMinScoreStep5(v))}
            style={{
              width: 56,
              fontSize: 11,
              background: "#1E222D",
              color: "#D1D4DC",
              border: "1px solid #2A2E39",
              padding: "4px 6px",
              fontFamily: "'IBM Plex Mono', monospace",
            }}
          />
        </div>
        <FilterDivider />
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={filterLabelStyle}>SORT</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(["score", "symbol"] as const).map((s) => (
              <FilterPill
                key={`sort-${s}`}
                active={sortBy === s}
                onClick={() => handleSortChange(s)}
                tooltip={`Sort rows by ${s}`}
              >
                {s}
              </FilterPill>
            ))}
          </div>
        </div>
      </div>

      {/* View toggle + table header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 20px",
          borderBottom: "1px solid var(--border-subtle)",
          background: "var(--bg-base)",
          gap: 12,
        }}
      >
        {listView === "table" && !loading ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: tableGridColumns,
              flex: 1,
              alignItems: "center",
              minWidth: 0,
            }}
          >
            <div />
            {["RANK", "MARKET", "DIRECTION", "PHASE", "TREND SCORE", "DEPTH", "SIGNAL", "DROP"].map((h) => (
              <span key={`header-${h}`} style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.14em" }}>
                {h}
              </span>
            ))}
          </div>
        ) : (
          <div style={{ flex: 1 }} />
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <Tooltip content="Table view">
            <button
              type="button"
              aria-pressed={listView === "table"}
              title="Table view"
              onClick={() => setListView("table")}
              style={{
                padding: 6,
                border: `1px solid ${listView === "table" ? "#F5A623" : "#2A2E39"}`,
                background: listView === "table" ? "rgba(245,166,35,0.12)" : "transparent",
                color: listView === "table" ? "#F5A623" : "#787B86",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                borderRadius: 2,
              }}
            >
              <Table2 size={16} strokeWidth={1.75} aria-hidden />
            </button>
          </Tooltip>
          <Tooltip content="Card view">
            <button
              type="button"
              aria-pressed={listView === "card"}
              title="Card view"
              onClick={() => setListView("card")}
              style={{
                padding: 6,
                border: `1px solid ${listView === "card" ? "#F5A623" : "#2A2E39"}`,
                background: listView === "card" ? "rgba(245,166,35,0.12)" : "transparent",
                color: listView === "card" ? "#F5A623" : "#787B86",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                borderRadius: 2,
              }}
            >
              <LayoutGrid size={16} strokeWidth={1.75} aria-hidden />
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Table / card body */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && <ScannerTableSkeleton />}
        {!loading && error && (
          <div style={{ padding: "40px 28px", textAlign: "center", color: "#E05A5A", fontSize: 11 }}>
            API unavailable
          </div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div style={{ padding: "40px 28px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
            <div style={{ border: "1px solid #F5A623", borderRadius: "50%", width: 32, height: 32 }} />
            <div style={{ fontSize: 11, color: "#3A3D48", letterSpacing: "0.14em" }}>
              NO MARKETS LOADED
            </div>
            <div style={{ fontSize: 9, color: "#2A2D36" }}>
              RUN RANK UNIVERSE TO POPULATE THE UNIVERSE
            </div>
          </div>
        )}
        {!loading && !error && listView === "table" &&
          filtered.map((setup) => {
            const symbol = String(setup.symbol || "");
            const timeframe = String(setup.timeframe || "");
            const trend = String(setup.trend || "");
            const fsmState = String(setup.fsm_state || "");
            const direction = deriveDirection(trend);
            const phase = derivePhase(fsmState);
            const rankUi = formatUniverseRank(setup.universe_rank);
            const marketParams = new URLSearchParams();
            marketParams.set("symbol", symbol);
            marketParams.set("timeframe", timeframe || "1h");
            if (category !== "All") {
              marketParams.set("category", category);
            }
            if (sortBy !== "score") {
              marketParams.set("sort", sortBy);
            }
            const marketHref = `/market?${marketParams.toString()}`;
            const isDropping = droppingSymbol === symbol;
            const openPaper = openTradesMap.get(symbol.toUpperCase());
            return (
              <div
                key={`setup-${setup.setup_id}`}
                role="button"
                tabIndex={0}
                onClick={() => router.push(marketHref)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    router.push(marketHref);
                  }
                }}
                style={{
                  display: "grid",
                  gridTemplateColumns: tableGridColumns,
                  padding: "8px 20px",
                  alignItems: "center",
                  borderBottom: "1px solid var(--border-subtle)",
                  transition: "background 0.1s ease",
                  background: setup.fsm_state === "MONITORING" ? "rgba(245,166,35,0.04)" : "transparent",
                  cursor: "pointer",
                  color: "inherit",
                  position: "relative",
                }}
                className="scanner-row"
              >
                <div
                  style={{
                    width: 3,
                    height: "100%",
                    marginLeft: 0,
                    background: openPaper
                      ? "#7B61FF"
                      : setup.fsm_state === "MONITORING" && setup.current_phase === "retracement"
                        ? "#F5A623"
                        : setup.current_phase === "impulse"
                          ? "#26A69A"
                          : "#1E222D",
                    boxShadow: openPaper
                      ? "2px 0 8px rgba(123,97,255,0.35)"
                      : setup.fsm_state === "MONITORING" && setup.current_phase === "retracement"
                        ? "2px 0 8px rgba(245,166,35,0.4)"
                        : setup.current_phase === "impulse"
                          ? "2px 0 8px rgba(38,166,154,0.4)"
                          : "none",
                  }}
                />
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 700, color: rankUi.color, letterSpacing: "0.04em" }}>
                  {rankUi.text}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {setup.fsm_state === "MONITORING" && (
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: "50%",
                        background: "#F5A623",
                        animation: "live-pulse 2s ease-in-out infinite",
                        flexShrink: 0,
                      }}
                    />
                  )}
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", letterSpacing: "0.02em", display: "inline-flex", alignItems: "center" }}>
                      {symbolsWithOverrides.has(symbol) && (
                        <span
                          title="Manual override active"
                          style={{
                            width: 5,
                            height: 5,
                            borderRadius: "50%",
                            background: "#F5A623",
                            display: "inline-block",
                            marginRight: 4,
                            flexShrink: 0,
                          }}
                        />
                      )}
                      {symbol}
                    </div>
                    {setup.category === "equities" &&
                      setup.display_name &&
                      setup.display_name !== setup.symbol && (
                        <div
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 8,
                            color: "#4A4D58",
                            letterSpacing: "0.06em",
                            marginTop: 2,
                          }}
                        >
                          {setup.display_name}
                        </div>
                      )}
                    <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 1, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span>{String(normalizeCategory(setup.category) || "").toUpperCase()}</span>
                      {setup.sector && (
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 7,
                            letterSpacing: "0.08em",
                            color: "#787B86",
                            border: "1px solid #2A2E39",
                            padding: "1px 5px",
                            borderRadius: 2,
                            textTransform: "uppercase",
                          }}
                        >
                          {setup.sector}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div>
                  <DirectionTag direction={direction} />
                </div>
                <div
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <MarketStateBadge
                    state={setup.market_state ?? setup.fsm_state ?? "WAITING"}
                    onClick={() => setStateDrawerSymbol(setup.symbol)}
                  />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <TrendScoreDisplay value={setup.trend_score} />
                  </div>
                  {openPaper ? <OpenPaperTradeBadge trade={openPaper} /> : null}
                </div>
                <div>
                  <DepthBadge depth={setup.pullback_depth || 0} />
                </div>
                <div>
                  <SignalBadge signal={setup.ema_signal} />
                </div>
                <div
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <Tooltip content="Remove this setup from scanner">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDropSetup(symbol);
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
                        fontFamily: "'IBM Plex Mono', monospace",
                      }}
                    >
                      {isDropping ? "..." : "DROP"}
                    </button>
                  </Tooltip>
                </div>
              </div>
            );
          })}
        {!loading && !error && listView === "card" && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 10,
              padding: "12px 20px 20px",
            }}
          >
            {filtered.map((setup) => {
              const symbol = String(setup.symbol || "");
              const timeframe = String(setup.timeframe || "");
              const trend = String(setup.trend || "");
              const fsmState = String(setup.fsm_state || "");
              const direction = deriveDirection(trend);
              const phase = derivePhase(fsmState);
              const marketParams = new URLSearchParams();
              marketParams.set("symbol", symbol);
              marketParams.set("timeframe", timeframe || "1h");
              if (category !== "All") marketParams.set("category", category);
              if (sortBy !== "score") marketParams.set("sort", sortBy);
              const marketHref = `/market?${marketParams.toString()}`;
              const isDropping = droppingSymbol === symbol;
              const depth = setup.pullback_depth || 0;
              const openPaper = openTradesMap.get(symbol.toUpperCase());
              return (
                <div
                  key={`card-${setup.setup_id}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => router.push(marketHref)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      router.push(marketHref);
                    }
                  }}
                  style={{
                    border: "1px solid var(--border-subtle)",
                    borderLeft: openPaper ? "3px solid #7B61FF" : undefined,
                    background: setup.fsm_state === "MONITORING" ? "rgba(245,166,35,0.04)" : "var(--bg-elevated)",
                    padding: 12,
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", letterSpacing: "0.02em", display: "inline-flex", alignItems: "center" }}>
                        {symbolsWithOverrides.has(symbol) && (
                          <span
                            title="Manual override active"
                            style={{
                              width: 5,
                              height: 5,
                              borderRadius: "50%",
                              background: "#F5A623",
                              display: "inline-block",
                              marginRight: 4,
                              flexShrink: 0,
                            }}
                          />
                        )}
                        {symbol}
                      </div>
                      {setup.sector && (
                        <span
                          style={{
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 7,
                            letterSpacing: "0.08em",
                            color: "#787B86",
                            border: "1px solid #2A2E39",
                            padding: "1px 5px",
                            borderRadius: 2,
                            textTransform: "uppercase",
                          }}
                        >
                          {setup.sector}
                        </span>
                      )}
                      {openPaper ? <OpenPaperTradeBadge trade={openPaper} /> : null}
                    </div>
                    {setup.category === "equities" &&
                      setup.display_name &&
                      setup.display_name !== setup.symbol && (
                        <div
                          style={{
                            width: "100%",
                            fontFamily: "'IBM Plex Mono', monospace",
                            fontSize: 8,
                            color: "#4A4D58",
                            letterSpacing: "0.06em",
                            marginTop: -4,
                          }}
                        >
                          {setup.display_name}
                        </div>
                      )}
                    <Tooltip content="Remove this setup from scanner">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDropSetup(symbol);
                        }}
                        disabled={isDropping}
                        style={{
                          border: "1px solid var(--border-default)",
                          background: "var(--border-default)",
                          padding: "2px 6px",
                          fontSize: 9,
                          letterSpacing: "0.08em",
                          color: "var(--text-secondary)",
                          cursor: isDropping ? "default" : "pointer",
                          opacity: isDropping ? 0.5 : 1,
                          borderRadius: 2,
                          fontFamily: "'IBM Plex Mono', monospace",
                          flexShrink: 0,
                        }}
                      >
                        {isDropping ? "..." : "DROP"}
                      </button>
                    </Tooltip>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <DirectionTag direction={direction} />
                    <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                      <MarketStateBadge
                        state={setup.market_state ?? setup.fsm_state ?? "WAITING"}
                        onClick={() => setStateDrawerSymbol(setup.symbol)}
                      />
                    </div>
                  </div>
                  <ScoreBar value={setup.trend_score} />
                  <div
                    style={{
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontSize: 18,
                      fontWeight: 700,
                      color: cardDepthColor(depth),
                      letterSpacing: "0.04em",
                    }}
                  >
                    {depth}
                    <span style={{ fontSize: 9, color: "#434651", marginLeft: 6, letterSpacing: "0.06em" }}>DEPTH</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{ borderTop: "1px solid var(--border-subtle)", padding: "8px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--bg-elevated)", fontSize: 9, color: "var(--text-dim)" }}>
        <span style={{ letterSpacing: "0.1em" }}>
          IKENGA · SWING TREND ENGINE · {health ? `CAPACITY ${health.active_setups}/${health.max_capacity}` : ""}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ letterSpacing: "0.08em" }}>
            {filtered.length} MARKETS · BOS/CHoCH · MULTI-TF ALIGNMENT
          </span>
          <Link
            href="/universe"
            style={{
              fontSize: 9,
              color: "#434651",
              letterSpacing: "0.1em",
              textDecoration: "none",
            }}
          >
            VIEW FULL UNIVERSE →
          </Link>
        </div>
      </div>

      {/* Rank Universe Confirmation Dialog */}
      {rankConfirmOpen && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 50,
            background: "rgba(0,0,0,0.65)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onClick={() => setRankConfirmOpen(false)}
        >
          <div
            style={{
              background: "#0D0F14",
              border: "1px solid #2A2E39",
              padding: "24px 28px",
              minWidth: 340,
              maxWidth: 420,
              fontFamily: "'IBM Plex Mono', monospace",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.16em", color: "#D1D4DC", marginBottom: 20 }}>
              RANK UNIVERSE
            </div>
            {rankDialogLoading ? (
              <div style={{ fontSize: 10, color: "#4A4D58", marginBottom: 20 }}>Loading...</div>
            ) : (() => {
              const lastJob = getLatestFinishedUniverseRanking(rankDialogLogs);
              return (
                <div style={{ display: "grid", gap: 10, marginBottom: 20 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.1em" }}>LAST COMPLETED</span>
                    <span style={{ fontSize: 9, color: "#D1D4DC" }}>
                      {formatUtcTimestamp(lastJob?.completed_at)}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.1em" }}>NEXT SCHEDULED</span>
                    <span style={{ fontSize: 9, color: "#D1D4DC" }}>
                      {mounted ? formatUtcTimestamp(nextMidnightUtc().toISOString()) : "—"}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.1em" }}>LAST DURATION</span>
                    <span style={{ fontSize: 9, color: "#D1D4DC" }}>
                      {formatDurationSeconds(lastJob?.duration_seconds)}
                    </span>
                  </div>
                </div>
              );
            })()}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => setRankConfirmOpen(false)}
                style={{
                  fontSize: 10, padding: "6px 14px",
                  border: "1px solid #2A2E39", background: "transparent",
                  color: "#787B86", cursor: "pointer", letterSpacing: "0.08em",
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
              >
                CANCEL
              </button>
              <button
                type="button"
                onClick={() => void handleRankProceed()}
                style={{
                  fontSize: 10, padding: "6px 14px",
                  border: "1px solid #F5A623", background: "transparent",
                  color: "#F5A623", cursor: "pointer", letterSpacing: "0.08em",
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
              >
                PROCEED
              </button>
            </div>
          </div>
        </div>
      )}
      <MarketStateDrawer
        symbol={stateDrawerSymbol ?? ""}
        state={setups.find(s => s.symbol === stateDrawerSymbol)?.market_state ?? "WAITING"}
        isOpen={stateDrawerSymbol !== null}
        onClose={() => setStateDrawerSymbol(null)}
      />
    </div>
  );
}

export default function ScannerPage() {
  return (
    <Suspense fallback={null}>
      <ScannerContent />
    </Suspense>
  );
}