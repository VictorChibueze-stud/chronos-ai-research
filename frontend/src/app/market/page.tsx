"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { IkengaLogomark } from "@/components/ikenga-logomark";
import { MarketCockpit } from "@/components/market-cockpit";
import { FullBleedPageSkeleton } from "@/components/ui/page-skeleton";
import {
  clearCoreAnalysisParams,
  loadCoreAnalysisParams,
  saveCoreAnalysisParams,
  type AnalysisCoreParams,
} from "@/lib/analysis-params-storage";
import { ApiError, analysisDevParamsToQueryRecord, api } from "@/lib/api";
import { formatScore } from "@/lib/format-display";
import type {
  AnalysisDevParams,
  AnalysisResponse,
  CandleBar,
  Setup,
  SignalHistoryItem,
} from "@/lib/types";
import { DEFAULT_ANALYSIS_DEV_PARAMS } from "@/lib/types";

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"] as const;

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
  const [tfError, setTfError] = useState<string | null>(null);
  /** Set only when GET /api/setups/:symbol fails (network / 5xx). Candle failures use chartLoadError. */
  const [error, setError] = useState<string | null>(null);
  const [chartLoadError, setChartLoadError] = useState<string | null>(null);
  const [featuredSetups, setFeaturedSetups] = useState<Setup[]>([]);
  const [featuredLoading, setFeaturedLoading] = useState(false);
  const [signalHistory, setSignalHistory] = useState<SignalHistoryItem[]>([]);
  /** True until analysis for the active symbol/TF has finished loading (candles may already be shown). */
  const [analysisLoading, setAnalysisLoading] = useState(true);
  const [universeMarkets, setUniverseMarkets] = useState<Setup[]>([]);
  const [analysisDevParams, setAnalysisDevParams] = useState<AnalysisDevParams>(() => ({
    ...DEFAULT_ANALYSIS_DEV_PARAMS,
  }));
  const analysisRequestId = useRef(0);
  const activeTimeframeRef = useRef(activeTimeframe);
  activeTimeframeRef.current = activeTimeframe;

  const analysisQueryForApi = useMemo(
    () => analysisDevParamsToQueryRecord(analysisDevParams),
    [analysisDevParams],
  );

  useLayoutEffect(() => {
    if (!symbolParam) {
      return;
    }
    const stored = loadCoreAnalysisParams(symbolParam);
    setAnalysisDevParams({ ...DEFAULT_ANALYSIS_DEV_PARAMS, ...(stored ?? {}) });
  }, [symbolParam]);

  const handleApplyCoreAnalysisParams = useCallback(
    (core: AnalysisCoreParams) => {
      if (!symbolParam) return;
      setAnalysisDevParams((prev) => ({ ...prev, ...core }));
      saveCoreAnalysisParams(symbolParam, core);
    },
    [symbolParam],
  );

  const handleResetAnalysisParams = useCallback(() => {
    if (symbolParam) {
      clearCoreAnalysisParams(symbolParam);
    }
    setAnalysisDevParams({ ...DEFAULT_ANALYSIS_DEV_PARAMS });
  }, [symbolParam]);

  useEffect(() => {
    let cancelled = false;
    api
      .getSetupsUniverse()
      .then((rows) => {
        if (!cancelled) setUniverseMarkets(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setUniverseMarkets([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleTimeframeChange = useCallback(
    async (tf: string) => {
      if (!symbolParam || tf === activeTimeframe) {
        return;
      }
      setActiveTimeframe(tf);
      setIsSwitchingTimeframe(true);
      setAnalysisLoading(true);
      setAnalysisData(null);
      setCandlesLoading(true);
      try {
        const newCandles = await api.getCandles(symbolParam, tf);
        if (activeTimeframeRef.current !== tf) {
          return;
        }
        setCandles(Array.isArray(newCandles) ? newCandles : []);
        setChartLoadError(null);
      } catch (err) {
        console.error("Timeframe switch failed:", tf, err);
        const reason =
          err instanceof ApiError && err.reason
            ? ` (${err.reason.replaceAll("_", " ")})`
            : "";
        // Keep current candles visible; only surface TF load failure.
        setChartLoadError(`Failed to load ${tf} candles${reason}`);
        setTfError(`Failed to load ${tf} data`);
        setTimeout(() => setTfError(null), 3000);
        setAnalysisLoading(false);
        return;
      } finally {
        setIsSwitchingTimeframe(false);
        setCandlesLoading(false);
      }
    },
    [symbolParam, activeTimeframe],
  );

  useEffect(() => {
    let cancelled = false;

    async function loadSetup() {
      if (!symbolParam) {
        setSetup(null);
        setCandles([]);
        setAnalysisData(null);
        setError(null);
        setChartLoadError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      setChartLoadError(null);

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
      setSignalHistory([]);
      setCandlesLoading(false);
      setAnalysisLoading(false);
      setIsSwitchingTimeframe(false);
      setTfError(null);
      setChartLoadError(null);
      return;
    }

    const tf = TIMEFRAMES.includes((timeframeParam ?? "") as (typeof TIMEFRAMES)[number])
      ? (timeframeParam as (typeof TIMEFRAMES)[number])
      : "1h";
    setActiveTimeframe(tf);

    let cancelled = false;
    setCandlesLoading(true);
    setAnalysisLoading(true);
    setAnalysisData(null);
    void (async () => {
      try {
        const candlesData = await api.getCandles(symbolParam, tf);
        if (cancelled) {
          return;
        }
        setCandles(Array.isArray(candlesData) ? candlesData : []);
        setChartLoadError(null);
      } catch {
        if (!cancelled) {
          setCandles([]);
          setAnalysisData(null);
          setSignalHistory([]);
          setChartLoadError("Unable to load candles for this market");
        }
        return;
      } finally {
        if (!cancelled) {
          setCandlesLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [symbolParam, timeframeParam]);

  useEffect(() => {
    if (!symbolParam) {
      return;
    }
    if (candlesLoading) {
      return;
    }
    if (chartLoadError || candles.length === 0) {
      setAnalysisData(null);
      setSignalHistory([]);
      setAnalysisLoading(false);
      return;
    }

    let cancelled = false;
    const reqId = ++analysisRequestId.current;
    setAnalysisLoading(true);
    const tf = activeTimeframe;

    void (async () => {
      try {
        const analysisResponse = await api.getAnalysis(symbolParam, tf, analysisQueryForApi).catch(() => null);
        if (cancelled || reqId !== analysisRequestId.current) {
          return;
        }
        setAnalysisData(analysisResponse);
        const signalData = await api.getSignalHistory(symbolParam, tf).catch(() => ({ items: [] }));
        if (cancelled || reqId !== analysisRequestId.current) {
          return;
        }
        setSignalHistory(Array.isArray(signalData.items) ? signalData.items : []);
      } finally {
        if (!cancelled && reqId === analysisRequestId.current) {
          setAnalysisLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    symbolParam,
    activeTimeframe,
    analysisQueryForApi,
    candlesLoading,
    candles.length,
    chartLoadError,
  ]);

  useEffect(() => {
    if (symbolParam) return;
    let cancelled = false;
    setFeaturedLoading(true);
    api
      .getSetups()
      .then((data) => {
        if (cancelled) return;
        const list = Array.isArray(data) ? data : [];
        const top = [...list].sort((a, b) => b.trend_score - a.trend_score).slice(0, 6);
        setFeaturedSetups(top);
      })
      .catch(() => {
        if (!cancelled) {
          setFeaturedSetups([]);
        }
      })
      .finally(() => {
        if (!cancelled) setFeaturedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbolParam]);

  const handleBackFromMarket = useCallback(() => {
    if (typeof window !== "undefined" && window.history.length <= 1) {
      router.push("/scanner");
      return;
    }
    router.back();
  }, [router]);

  function emptyStateTrendArrow(trend: string | undefined): { glyph: string; color: string } {
    const t = String(trend ?? "").toLowerCase();
    if (t === "up") return { glyph: "▲", color: "#26A69A" };
    if (t === "down") return { glyph: "▼", color: "#EF5350" };
    return { glyph: "—", color: "#787B86" };
  }

  if (!symbolParam) {
    return (
      <div
        style={{
          flex: 1,
          minHeight: 0,
          background: "#0B0D11",
          display: "flex",
          flexDirection: "column",
          alignItems: "stretch",
          justifyContent: "flex-start",
          boxSizing: "border-box",
          fontFamily: '"IBM Plex Mono", monospace',
        }}
      >
        <style>{`@keyframes card-pulse { 0%,100%{opacity:0.3} 50%{opacity:0.6} }`}</style>

        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "24px 20px",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(100px, 112px))",
              gridTemplateRows: "repeat(2, auto)",
              gap: 10,
              maxWidth: 380,
              width: "100%",
              justifyContent: "center",
            }}
          >
            {featuredLoading
              ? (Array.from({ length: 6 }) as unknown[]).map((_, i) => (
                  <div
                    key={i}
                    style={{
                      minHeight: 72,
                      border: "1px solid #F5A623",
                      background: "#131722",
                      borderRadius: 2,
                      animation: `card-pulse 1.4s ease-in-out ${i * 0.1}s infinite`,
                    }}
                  />
                ))
              : featuredSetups.map((s) => {
                  const { glyph, color } = emptyStateTrendArrow(s.trend);
                  return (
                    <div
                      key={s.symbol}
                      role="button"
                      tabIndex={0}
                      onClick={() =>
                        router.push(`/market?symbol=${encodeURIComponent(s.symbol)}&timeframe=1h`)
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          router.push(`/market?symbol=${encodeURIComponent(s.symbol)}&timeframe=1h`);
                        }
                      }}
                      style={{
                        minHeight: 72,
                        border: "1px solid #F5A623",
                        background: "#131722",
                        borderRadius: 2,
                        cursor: "pointer",
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "space-between",
                        padding: "8px 10px",
                        transition: "background 0.12s ease",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = "#1E222D";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = "#131722";
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#D1D4DC",
                            letterSpacing: "0.03em",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {s.symbol}
                        </span>
                        <span style={{ fontSize: 11, color, flexShrink: 0 }}>{glyph}</span>
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#D1D4DC", alignSelf: "flex-end" }}>
                        {formatScore(s.trend_score)}
                      </span>
                    </div>
                  );
                })}
          </div>

          <div style={{ marginTop: 28, display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
            <IkengaLogomark size={48} />
            <div
              style={{
                fontSize: 11,
                letterSpacing: "0.2em",
                color: "#F5A623",
                textTransform: "uppercase",
              }}
            >
              IKENGA
            </div>
            <div style={{ fontSize: 9, letterSpacing: "0.12em", color: "#787B86", textAlign: "center" }}>
              SELECT A MARKET TO BEGIN ANALYSIS
            </div>
          </div>
        </div>

        <div
          style={{
            flexShrink: 0,
            padding: "12px 20px 20px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexWrap: "wrap",
            gap: 6,
            fontSize: 9,
            letterSpacing: "0.06em",
            color: "#434651",
          }}
        >
          <span style={{ color: "#F5A623" }}>1</span>
          <span>RUN SCANNER</span>
          <span style={{ color: "#2A2E39" }}>→</span>
          <span style={{ color: "#F5A623" }}>2</span>
          <span>SELECT MARKET</span>
          <span style={{ color: "#2A2E39" }}>→</span>
          <span style={{ color: "#F5A623" }}>3</span>
          <span>VIEW ANALYSIS</span>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <FullBleedPageSkeleton label="Loading market" />
      </div>
    );
  }

  if (error || !setup) {
    return <div style={{ ...CENTERED_STATUS_STYLE, color: "#E05A5A" }}>DATA UNAVAILABLE</div>;
  }

  const combinedTfError = chartLoadError ?? tfError;

  return (
    <MarketCockpit
      setup={setup}
      candles={candles}
      analysisData={analysisData ?? undefined}
      analysisOverlaysReady={!analysisLoading}
      universeMarkets={universeMarkets}
      activeTimeframe={activeTimeframe}
      onTimeframeChange={handleTimeframeChange}
      onNavigate={(symbol) => {
        const next = String(symbol || "").trim().toUpperCase();
        if (!next) {
          return;
        }
        const tf = TIMEFRAMES.includes(activeTimeframe as (typeof TIMEFRAMES)[number]) ? activeTimeframe : "1h";
        router.push(`/market?symbol=${encodeURIComponent(next)}&timeframe=${encodeURIComponent(tf)}`);
      }}
      candlesLoading={candlesLoading}
      isSwitchingTimeframe={isSwitchingTimeframe}
      tfError={combinedTfError}
      signalHistory={signalHistory}
      analysisDevParams={analysisDevParams}
      analysisQueryForApi={analysisQueryForApi}
      onAnalysisDevParamsChange={setAnalysisDevParams}
      onApplyCoreAnalysisParams={handleApplyCoreAnalysisParams}
      onResetAnalysisParams={handleResetAnalysisParams}
      onBack={handleBackFromMarket}
    />
  );
}

export default function MarketPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
          <FullBleedPageSkeleton label="Loading market" />
        </div>
      }
    >
      <MarketContent />
    </Suspense>
  );
}