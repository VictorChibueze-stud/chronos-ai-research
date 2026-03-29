"use client";

import { Fragment, Suspense, useEffect, useRef, useState, type CSSProperties } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { MarketCockpit } from "@/components/market-cockpit";
import { api } from "@/lib/api";
import type { AnalysisResponse, CandleBar, Setup } from "@/lib/types";

const TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"] as const;

const CANDLE_LIMITS: Record<string, number> = {
  "15m": 672,
  "30m": 336,
  "1h": 240,
  "4h": 90,
  "1d": 365,
};

const CENTERED_STATUS_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: "100%",
  background: "#0D0F14",
  color: "#F5A623",
  fontFamily: '"IBM Plex Mono", monospace',
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

function MarketContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const symbolParam = searchParams.get("symbol");
  const timeframeParam = searchParams.get("timeframe");
  const initialTimeframe = TIMEFRAMES.includes((timeframeParam ?? "") as (typeof TIMEFRAMES)[number])
    ? (timeframeParam as (typeof TIMEFRAMES)[number])
    : "1h";

  const [setup, setSetup] = useState<Setup | null>(null);
  const [candles, setCandles] = useState<CandleBar[]>([]);
  const [analysisData, setAnalysisData] = useState<AnalysisResponse | null>(null);
  const [activeTimeframe, setActiveTimeframe] = useState<string>(initialTimeframe);
  const [loading, setLoading] = useState(true);
  const [candlesLoading, setCandlesLoading] = useState(false);
  const [isSwitchingTimeframe, setIsSwitchingTimeframe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [featuredSetups, setFeaturedSetups] = useState<Setup[]>([]);
  const [featuredLoading, setFeaturedLoading] = useState(false);
  const [hoveredCard, setHoveredCard] = useState<number | null>(null);
  const timeframeRequestIdRef = useRef(0);

  async function loadTimeframeData(symbol: string, timeframe: string, isSwitch: boolean) {
    const requestId = ++timeframeRequestIdRef.current;

    if (isSwitch) {
      setIsSwitchingTimeframe(true);
    } else {
      setCandlesLoading(true);
    }

    try {
      const limit = CANDLE_LIMITS[timeframe] ?? 200;
      const [candlesData, analysisResponse] = await Promise.all([
        api.getCandles(symbol, timeframe, limit),
        api.getAnalysis(symbol, timeframe).catch(() => null),
      ]);

      if (requestId !== timeframeRequestIdRef.current) {
        return;
      }

      const nextCandles = Array.isArray(candlesData) ? candlesData : [];
      setCandles(nextCandles);
      setAnalysisData(analysisResponse);
      setError(null);
    } catch {
      if (requestId !== timeframeRequestIdRef.current) {
        return;
      }

      // Keep existing chart visible during timeframe switching failures.
      if (!isSwitch) {
        setCandles([]);
        setAnalysisData(null);
      }
      setError("DATA UNAVAILABLE");
    } finally {
      if (requestId !== timeframeRequestIdRef.current) {
        return;
      }
      setCandlesLoading(false);
      setIsSwitchingTimeframe(false);
    }
  }

  function handleTimeframeChange(nextTimeframe: string) {
    if (nextTimeframe === activeTimeframe) {
      return;
    }

    setActiveTimeframe(nextTimeframe);

    if (!symbolParam) {
      return;
    }

    void loadTimeframeData(symbolParam, nextTimeframe, true);
  }

  useEffect(() => {
    let cancelled = false;

    async function loadSetup() {
      if (!symbolParam) {
        setSetup(null);
        setCandles([]);
        setAnalysisData(null);
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const setupData = await api.getSetup(symbolParam);

        if (cancelled) {
          return;
        }

        setSetup(setupData);
      } catch {
        if (!cancelled) {
          setSetup(null);
          setError("DATA UNAVAILABLE");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadSetup();

    return () => {
      cancelled = true;
    };
  }, [symbolParam]);

  useEffect(() => {
    if (!symbolParam) {
      setCandles([]);
      setAnalysisData(null);
      setCandlesLoading(false);
      setIsSwitchingTimeframe(false);
      return;
    }

    void loadTimeframeData(symbolParam, activeTimeframe, false);
  }, [symbolParam]);

  useEffect(() => {
    const nextFromUrl = TIMEFRAMES.includes((timeframeParam ?? "") as (typeof TIMEFRAMES)[number])
      ? (timeframeParam as (typeof TIMEFRAMES)[number])
      : "1h";

    if (nextFromUrl === activeTimeframe) {
      return;
    }

    setActiveTimeframe(nextFromUrl);

    if (symbolParam) {
      void loadTimeframeData(symbolParam, nextFromUrl, true);
    }
  }, [timeframeParam, activeTimeframe, symbolParam]);

  useEffect(() => {
    if (symbolParam) return;
    let cancelled = false;
    setFeaturedLoading(true);
    api
      .getSetups()
      .then((data) => {
        if (!cancelled) setFeaturedSetups(data.slice(0, 6));
      })
      .catch(() => {
        if (!cancelled) setFeaturedSetups([]);
      })
      .finally(() => {
        if (!cancelled) setFeaturedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbolParam]);

  function categoryBorderColor(cat: string): string {
    const c = (cat ?? "").toLowerCase();
    if (c === "crypto") return "#F5A623";
    if (c === "forex") return "#26A69A";
    if (c === "synthetic") return "#9B59B6";
    if (c === "commodity") return "#EF5350";
    return "#434651";
  }

  function depthDotColor(depth: number): string {
    if (depth === 1) return "#2962FF";
    if (depth === 2) return "#26A69A";
    return "#F5A623";
  }

  if (!symbolParam) {
    return (
      <div style={{
        minHeight: "100%",
        background: "#0B0D11",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        fontFamily: '"IBM Plex Mono", monospace',
      }}>
        <style>{`@keyframes card-pulse { 0%,100%{opacity:0.3} 50%{opacity:0.6} }`}</style>

        {/* Live market cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 96px)", gap: 6 }}>
          {featuredLoading
            ? (Array.from({ length: 6 }) as unknown[]).map((_, i) => (
                <div
                  key={i}
                  style={{
                    width: 96,
                    height: 64,
                    border: "1px solid #1E222D",
                    background: "#131722",
                    borderTop: "3px solid #1E222D",
                    animation: `card-pulse 1.4s ease-in-out ${i * 0.1}s infinite`,
                  }}
                />
              ))
            : featuredSetups.map((s, i) => {
                const depth = Math.min(3, Math.max(1, s.structural_state_json?.max_depth_reached ?? 1));
                return (
                  <div
                    key={s.symbol}
                    onClick={() =>
                      router.push(
                        `/market?symbol=${encodeURIComponent(s.symbol)}&timeframe=1h`,
                      )
                    }
                    onMouseEnter={() => setHoveredCard(i)}
                    onMouseLeave={() => setHoveredCard(null)}
                    style={{
                      width: 96,
                      height: 64,
                      border: "1px solid #1E222D",
                      background: hoveredCard === i ? "#1E222D" : "#131722",
                      borderTop: `3px solid ${categoryBorderColor(s.category)}`,
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      padding: "6px 8px 5px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: "#D1D4DC", letterSpacing: "0.03em" }}>
                        {s.symbol}
                      </span>
                      <span style={{ fontSize: 11, color: s.trend === "up" ? "#26A69A" : "#EF5350" }}>
                        {s.trend === "up" ? "▲" : "▼"}
                      </span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <div
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background: depthDotColor(depth),
                        }}
                      />
                      <span style={{ fontSize: 9, color: "#434651" }}>{Math.round(s.trend_score)}</span>
                    </div>
                  </div>
                );
              })}
        </div>

        {/* Logo mark + text */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
          <svg width="48" height="48" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="10" cy="10" r="8" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.4" style={{ animation: 'logo-spin 12s linear infinite', transformBox: 'fill-box', transformOrigin: 'center' }}/>
            <circle cx="10" cy="10" r="5" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.7"/>
            <path d="M10 3 L10 6 M8.5 5 L10 6.5 L11.5 5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M10 17 L10 14 M8.5 15 L10 13.5 L11.5 15" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M3 10 L6 10 M5 8.5 L6.5 10 L5 11.5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M17 10 L14 10 M15 8.5 L13.5 10 L15 11.5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <circle cx="10" cy="10" r="1.5" fill="#F5A623"/>
          </svg>
          <div style={{ fontSize: 11, letterSpacing: "0.3em", color: "#434651" }}>IKENGA</div>
          <div style={{ fontSize: 10, letterSpacing: "0.2em", color: "#2A2E39" }}>SELECT A MARKET TO BEGIN ANALYSIS</div>
        </div>

        {/* Steps */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {["RUN SCANNER", "SELECT MARKET", "VIEW ANALYSIS"].map((step, i) => (
            <Fragment key={step}>
              {i > 0 && <span style={{ fontSize: 9, color: "#2A2E39" }}>→</span>}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                <div style={{ fontSize: 9, color: "#F5A623" }}>{i + 1}</div>
                <div style={{ fontSize: 9, color: "#434651", letterSpacing: "0.06em" }}>{step}</div>
              </div>
            </Fragment>
          ))}
        </div>
      </div>
    );
  }

  if (loading) {
    return <div style={CENTERED_STATUS_STYLE}>LOADING MARKET DATA...</div>;
  }

  if (error || !setup) {
    return <div style={{ ...CENTERED_STATUS_STYLE, color: "#E05A5A" }}>DATA UNAVAILABLE</div>;
  }

  return (
    <MarketCockpit
      setup={setup}
      candles={candles}
      analysisData={analysisData ?? undefined}
      activeTimeframe={activeTimeframe}
      onTimeframeChange={handleTimeframeChange}
      onNavigate={(symbol) => {
        const next = String(symbol || "").trim().toUpperCase();
        if (!next) {
          return;
        }
        router.push(`/market?symbol=${encodeURIComponent(next)}&timeframe=1h`);
      }}
      candlesLoading={candlesLoading}
      isSwitchingTimeframe={isSwitchingTimeframe}
    />
  );
}

export default function MarketPage() {
  return (
    <Suspense fallback={null}>
      <MarketContent />
    </Suspense>
  );
}