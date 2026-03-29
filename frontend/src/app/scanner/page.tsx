"use client";
import { Suspense, useEffect, useState, useRef, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Setup } from "@/lib/types";

const SCAN_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "EURUSD", "XAUUSD"];
const SCAN_TIMEFRAME = "1h";

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
        {Math.round(value)}
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

function TFBadge({ label }: { label: string }) {
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
      padding: "2px 5px", border: "1px solid #2A2E39",
      borderRadius: 2, color: "#6B6F7A", letterSpacing: "0.05em",
    }}>
      {String(label || "").toUpperCase()}
    </span>
  );
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

function AnimatedScoreValue({ value }: { value: number }) {
  const [displayValue, setDisplayValue] = useState(0);
  const hasAnimatedRef = useRef(false);

  useEffect(() => {
    if (hasAnimatedRef.current) {
      setDisplayValue(value);
      return;
    }

    hasAnimatedRef.current = true;
    const start = performance.now();
    const duration = 600;
    let rafId = 0;

    const frame = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = t * (2 - t);
      setDisplayValue(value * eased);
      if (t < 1) {
        rafId = requestAnimationFrame(frame);
      }
    };

    rafId = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(rafId);
  }, [value]);

  return <>{displayValue.toFixed(2)}</>;
}

function MetricBlock({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
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

// ── Helpers ───────────────────────────────────────────────────────────────

function deriveStep(pullbackDepth: number): number {
  if (pullbackDepth <= 0) return 1;
  if (pullbackDepth <= 20) return 1;
  if (pullbackDepth <= 40) return 2;
  if (pullbackDepth <= 60) return 3;
  if (pullbackDepth <= 80) return 4;
  return 5;
}

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

// ── Main Component ────────────────────────────────────────────────────────

const CATEGORIES = ["All", "Forex", "Crypto", "Commodities", "Indices", "Synthetic"];
const TF_FILTERS = ["ALL", "15M", "30M", "1H", "4H", "1D"];

function normalizeCategory(cat: string | undefined): string {
  if (!cat) return "unknown";
  const c = cat.toLowerCase();
  if (c === "crypto") return "Crypto";
  if (c === "forex") return "Forex";
  if (c === "synthetic") return "Synthetic";
  if (c === "commodity") return "Commodities";
  if (c === "indices" || c === "index") return "Indices";
  return "Forex";
}

function ScannerContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [setups, setSetups] = useState<Setup[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const initialCategory = searchParams.get("category");
  const initialSort = searchParams.get("sort");
  const [category, setCategory] = useState(
    initialCategory && CATEGORIES.includes(initialCategory) ? initialCategory : "All"
  );
  const [sortBy, setSortBy] = useState<"score" | "symbol">(
    initialSort === "symbol" ? "symbol" : "score"
  );
  const [pulse, setPulse] = useState<number | null>(null);
  const [scanTime, setScanTime] = useState(new Date());
  const [nextScanCountdown, setNextScanCountdown] = useState("--:--");
  const [timeframeFilter, setTimeframeFilter] = useState<string>("ALL");
  const [minScore, setMinScore] = useState<number>(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const nextCategory = searchParams.get("category");
    const nextSort = searchParams.get("sort");
    const normalizedCategory = nextCategory && CATEGORIES.includes(nextCategory) ? nextCategory : "All";
    const normalizedSort: "score" | "symbol" = nextSort === "symbol" ? "symbol" : "score";

    setCategory((current) => (current === normalizedCategory ? current : normalizedCategory));
    setSortBy((current) => (current === normalizedSort ? current : normalizedSort));
  }, [searchParams]);

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

  async function fetchData() {
    try {
      const [setupsData, healthData] = await Promise.all([
        api.getSetups(),
        api.getHealth().catch(() => null),
      ]);
      setSetups(Array.isArray(setupsData) ? setupsData : []);
      setHealth(healthData);
      setScanTime(new Date());
      setError(null);
    } catch {
      setSetups([]);
      setHealth(null);
      setError("API unavailable");
    } finally {
      setLoading(false);
    }
  }

  async function handleScanAll() {
    setIsScanning(true);
    setError(null);

    try {
      const nextSetups = await api.scanSetups({});
      setSetups(Array.isArray(nextSetups) ? nextSetups : []);
      setScanTime(new Date());

      try {
        setHealth(await api.getHealth());
      } catch {
        setHealth(null);
      }
    } catch {
      setError("API unavailable");
    } finally {
      setIsScanning(false);
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const dataInterval = setInterval(fetchData, 30000);
    return () => clearInterval(dataInterval);
  }, []);

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      if (setups.length > 0) {
        const randomId = setups[Math.floor(Math.random() * setups.length)].setup_id;
        setPulse(randomId);
        setTimeout(() => setPulse(null), 600);
      }
    }, 4000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [setups]);

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

  const filtered = setups
    .filter(s => category === "All" || normalizeCategory(s.category) === category)
    .filter(s => {
      if (timeframeFilter === "ALL") return true;
      const tf = timeframeFilter.toLowerCase();
      const alignment = s.mtf_alignment;
      if (!alignment) return false;
      return tf in alignment;
    })
    .filter(s => s.trend_score >= minScore)
    .sort((a, b) => sortBy === "score" ? b.trend_score - a.trend_score : String(a.symbol || "").localeCompare(String(b.symbol || "")));

  const highConviction = setups.filter(s => s.trend_score >= 30).length;
  const inRetracement = setups.filter(s => s.fsm_state === "MONITORING").length;
  const inImpulse = setups.filter(s => s.fsm_state !== "MONITORING" && s.current_phase === "impulse").length;
  const derivedLastScan = setups.length > 0
    ? formatTime(setups.reduce((a, b) => new Date(a.last_checked_at) > new Date(b.last_checked_at) ? a : b).last_checked_at)
    : "--:--";
  const healthLastScanIso = health?.last_scan || null;
  const lastScan = healthLastScanIso ? formatTime(healthLastScanIso) : derivedLastScan;
  const isLastScanStale = healthLastScanIso
    ? (Date.now() - new Date(healthLastScanIso).getTime()) > (6 * 60 * 60 * 1000)
    : false;
  const sparklineScores = [...setups]
    .sort((a, b) => b.trend_score - a.trend_score)
    .slice(0, 5)
    .map((setup) => Math.max(4, Math.min(16, Math.round((setup.trend_score / 100) * 16))));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-base)", fontFamily: "'IBM Plex Mono', monospace", color: "var(--text-primary)" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 20px", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-elevated)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 10, color: "#3A3D48", letterSpacing: "0.1em" }}>MARKET SCANNER</span>
          <span style={{ fontSize: 10, color: "#2A2D36" }}>v2.4</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#4CAF7D", boxShadow: "0 0 6px #4CAF7D" }} />
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "#F5A623",
                animation: isScanning ? "live-pulse 1.4s ease-in-out infinite" : undefined,
                opacity: isScanning ? 1 : 0,
              }}
            />
            <span style={{ fontSize: 10, color: "#4A4D58", letterSpacing: "0.08em" }}>LIVE</span>
          </div>
          <span style={{ fontSize: 10, color: "#4A4D58", letterSpacing: "0.08em" }}>NEXT SCAN: {nextScanCountdown}</span>
          <span style={{ fontSize: 10, color: "#2A2D36" }}>{mounted ? scanTime.toUTCString().slice(17, 25) : "--:--:--"} UTC</span>
          <button
            onClick={handleScanAll}
            disabled={isScanning}
            style={{
              padding: "6px 14px",
              border: "1px solid #2A2D36",
              borderRadius: 2,
              fontSize: 10,
              color: isScanning ? "#A4A7B2" : "#6B6F7A",
              background: "transparent",
              cursor: isScanning ? "wait" : "pointer",
              letterSpacing: "0.06em",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {isScanning ? (
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
                SCANNING...
              </>
            ) : (
              "SCAN ALL"
            )}
          </button>
        </div>
      </div>

      {/* KPI Strip */}
      <div style={{ display: "flex", padding: "16px 0", borderBottom: "1px solid var(--border-default)", background: "var(--bg-surface)" }}>
        <MetricBlock label="ACTIVE SETUPS" value={setups.length} color="var(--text-primary)" />
        <MetricBlock label="HIGH CONVICTION" value={highConviction} />
        <MetricBlock label="IN RETRACEMENT" value={inRetracement} />
        <MetricBlock label="IN IMPULSE" value={inImpulse} />
        <MetricBlock label="LAST SCAN" value={mounted ? lastScan : "--:--"} color={isLastScanStale ? "#F5A623" : undefined} />
      </div>

      {/* Controls */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", gap: 2 }}>
          {CATEGORIES.map(cat => (
            <button key={`category-${cat}`} onClick={() => handleCategoryChange(cat)} style={{
              padding: "3px 8px", fontSize: 10, letterSpacing: "0.08em",
              background: category === cat ? "#F5A623" : "transparent",
              color: category === cat ? "#0D0F14" : "#4A4D58",
              border: `1px solid ${category === cat ? "#F5A623" : "#1C1E24"}`,
              borderRadius: 2, cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
              fontWeight: category === cat ? 700 : 400,
            }}>{cat}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#3A3D48", marginRight: 4 }}>SORT</span>
          {(["score", "symbol"] as const).map(s => (
            <button key={`sort-${s}`} onClick={() => handleSortChange(s)} style={{
              padding: "3px 7px", fontSize: 10,
              background: sortBy === s ? "#1C1E24" : "transparent",
              color: sortBy === s ? "#C8C8D0" : "#3A3D48",
              border: "1px solid #1C1E24", borderRadius: 2, cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace", textTransform: "uppercase", letterSpacing: "0.06em",
            }}>{s}</button>
          ))}
        </div>
      </div>

      {/* Controls Row 2 — TF filter + MIN SCORE */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "6px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <div style={{ display: "flex", flexDirection: "column", marginRight: 6 }}>
            <span style={{ fontSize: 9, color: "#434651", letterSpacing: "0.1em" }}>TF</span>
            <span style={{ fontSize: 8, color: "#434651", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>alignment</span>
          </div>
          {TF_FILTERS.map(tf => (
            <button key={`tf-${tf}`} onClick={() => setTimeframeFilter(tf)} style={{
              padding: "3px 8px", fontSize: 10, letterSpacing: "0.08em",
              background: timeframeFilter === tf ? "#F5A623" : "transparent",
              color: timeframeFilter === tf ? "#0D0F14" : "#4A4D58",
              border: `1px solid ${timeframeFilter === tf ? "#F5A623" : "#1C1E24"}`,
              borderRadius: 2, cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
              fontWeight: timeframeFilter === tf ? 700 : 400,
            }}>{tf}</button>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 9, color: "#434651", letterSpacing: "0.1em" }}>MIN SCORE</span>
          <span style={{ fontSize: 9, color: "#F5A623", letterSpacing: "0.08em" }}>{minScore}+</span>
          <input
            type="range"
            min={0}
            max={50}
            step={5}
            value={minScore}
            onChange={e => setMinScore(Number(e.target.value))}
            style={{ width: 120, accentColor: "#F5A623", cursor: "pointer" }}
          />
        </div>
      </div>

      {/* Table Header */}
      <div style={{ display: "grid", gridTemplateColumns: "28px 200px 80px 90px 160px 80px 100px 1fr 80px", padding: "8px 20px", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-base)" }}>
        <div />
        {["MARKET", "DIRECTION", "PHASE", "TREND SCORE", "DEPTH", "TIMEFRAMES", "SCORE / DATA", "SIGNAL"].map(h => (
          <span key={`header-${h}`} style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.14em" }}>{h}</span>
        ))}
      </div>

      {/* Table Body */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {loading && (
          <div style={{ padding: "40px 28px", textAlign: "center", color: "#3A3D48", fontSize: 11 }}>
            SCANNING MARKETS...
          </div>
        )}
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
              RUN SCAN ALL TO POPULATE THE UNIVERSE
            </div>
          </div>
        )}
        {!loading && !error && filtered.map(setup => {
          const symbol = String(setup.symbol || "");
          const timeframe = String(setup.timeframe || "");
          const trend = String(setup.trend || "");
          const fsmState = String(setup.fsm_state || "");
          const direction = deriveDirection(trend);
          const phase = derivePhase(fsmState);
          const step = deriveStep(setup.pullback_depth || 0);
          const isPulsing = pulse === setup.setup_id;
          const isActionable = setup.fsm_state === "MONITORING" && setup.current_phase === "retracement";
          const isImpulseRow = setup.current_phase === "impulse";
          const accentColor = isActionable ? "#F5A623" : isImpulseRow ? "#3A6BFF" : "#2A2D36";
          const rowPulseAnimation = setup.fsm_state === "MONITORING"
            ? "border-pulse-amber 3s ease-in-out infinite"
            : setup.current_phase === "impulse"
              ? "border-pulse-blue 3s ease-in-out infinite"
              : undefined;
          const waitingText = String(setup.waiting_for || "").trim() || fsmState;
          const waitingPreview = waitingText.length > 28 ? `${waitingText.slice(0, 28)}...` : waitingText;
          const marketParams = new URLSearchParams();
          marketParams.set("symbol", symbol);
          marketParams.set("timeframe", timeframe || "1h");
          if (category !== "All") {
            marketParams.set("category", category);
          }
          if (sortBy !== "score") {
            marketParams.set("sort", sortBy);
          }
          return (
            <Link
              key={`setup-${setup.setup_id}`}
              href={`/market?${marketParams.toString()}`}
              prefetch={true}
              style={{
                display: "grid",
                gridTemplateColumns: "28px 200px 80px 90px 160px 80px 100px 1fr 80px",
                padding: "8px 20px",
                alignItems: "center",
                borderBottom: "1px solid var(--border-subtle)",
                transition: "background 0.1s ease",
                background: setup.fsm_state === "MONITORING" ? "rgba(245,166,35,0.04)" : "transparent",
                cursor: "pointer",
                textDecoration: "none",
                color: "inherit",
                position: "relative",
              }}
              className="scanner-row"
            >
              {/* Accent bar */}
              <div
                style={{
                  width: 3,
                  height: "100%",
                  marginLeft: 0,
                  background:
                    setup.fsm_state === "MONITORING" && setup.current_phase === "retracement"
                      ? "#F5A623"
                      : setup.current_phase === "impulse"
                        ? "#26A69A"
                        : "#1E222D",
                  boxShadow:
                    setup.fsm_state === "MONITORING" && setup.current_phase === "retracement"
                      ? "2px 0 8px rgba(245,166,35,0.4)"
                      : setup.current_phase === "impulse"
                        ? "2px 0 8px rgba(38,166,154,0.4)"
                        : "none",
                }}
              />

              {/* Market */}
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
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", letterSpacing: "0.02em" }}>
                    {symbol}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 1 }}>
                    {String(normalizeCategory(setup.category) || "").toUpperCase()}
                  </div>
                </div>
              </div>

              {/* Direction */}
              <div>
                <DirectionTag direction={direction} />
              </div>

              {/* Phase */}
              <div>
                <PhaseBadge phase={phase} />
              </div>

              {/* Trend Score */}
              <div>
                <TrendScoreDisplay value={setup.trend_score} />
              </div>

              {/* Depth */}
              <div>
                <DepthBadge depth={setup.pullback_depth || 0} />
              </div>

              {/* Timeframe */}
              <div>
                <TFBadge label={timeframe || "—"} />
              </div>

              {/* Score / Data */}
              <div className="group relative" style={{ textAlign: "right", overflow: "visible" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                  <AnimatedScoreValue value={setup.trend_score} />
                </div>
                <div style={{ fontSize: 10, color: "var(--text-secondary)", marginTop: 2 }}>
                  {waitingPreview}
                </div>
                <div className="pointer-events-none absolute right-0 top-full z-30 mt-2 hidden w-64 rounded-none border border-var(--border-default) bg-var(--bg-elevated) p-2 text-[10px] text-var(--text-primary) shadow-none group-hover:block">
                  {waitingText}
                </div>
              </div>

              {/* Signal */}
              <div>
                <SignalBadge signal={setup.ema_signal} />
              </div>
            </Link>
          );
        })}
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