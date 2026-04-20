"use client";

import {
  Suspense,
  useCallback,
  useEffect,
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

type FeaturedUniverse = "all" | "multi_asset" | "synthetic" | "crypto";

// Mirror of src/api/routers/setups.py::_infer_universe — kept in
// sync for the 6-card grid tab filter when the backend has not yet
// populated Setup.universe for a row.
function _inferUniverseFrontend(symbol: string, category: string): string {
  const sym = symbol.toUpperCase();
  if (sym.endsWith("USDT") || sym.endsWith("BTC")) return "crypto";
  const SYNTH = ["R_", "1HZ", "BOOM", "CRASH", "JD", "OTC_", "STEP", "WLD", "RB"];
  if (SYNTH.some((p) => sym.startsWith(p))) return "synthetic";
  if (category === "synthetic") return "synthetic";
  if (category === "crypto") return "crypto";
  return "multi_asset";
}

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
  const [landingSearch, setLandingSearch] = useState("");
  const [landingSearchFocused, setLandingSearchFocused] = useState(false);
  const [featuredUniverse, setFeaturedUniverse] = useState<FeaturedUniverse>("all");
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

  const toggleCategory = useCallback((cat: string) => {
    setCollapsedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  const handleLandingSearchChange = useCallback((val: string) => {
    setLandingSearch(val);
    if (!val.trim()) setCollapsedCategories(new Set());
  }, []);
  const [analysisDevParams, setAnalysisDevParams] = useState<AnalysisDevParams>(() => ({
    ...DEFAULT_ANALYSIS_DEV_PARAMS,
  }));
  const [isRecomputingParams, setIsRecomputingParams] = useState(false);
  const analysisRequestId = useRef(0);
  const recomputeBadgeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeTimeframeRef = useRef(activeTimeframe);
  activeTimeframeRef.current = activeTimeframe;

  const showRecomputingBadge = useCallback(() => {
    setIsRecomputingParams(true);
    if (recomputeBadgeTimeoutRef.current) {
      clearTimeout(recomputeBadgeTimeoutRef.current);
    }
    recomputeBadgeTimeoutRef.current = setTimeout(() => {
      setIsRecomputingParams(false);
      recomputeBadgeTimeoutRef.current = null;
    }, 3000);
  }, []);

  const analysisQueryForApi = useMemo(
    () => analysisDevParamsToQueryRecord(analysisDevParams),
    [analysisDevParams],
  );

  useEffect(() => {
    if (!symbolParam) {
      return;
    }
    const stored = loadCoreAnalysisParams(symbolParam);
    setAnalysisDevParams({ ...DEFAULT_ANALYSIS_DEV_PARAMS, ...(stored ?? {}) });
    let cancelled = false;
    api
      .getSymbolParams(symbolParam)
      .then((res) => {
        if (cancelled) return;
        if (!res.is_default) {
          setAnalysisDevParams({
            ...DEFAULT_ANALYSIS_DEV_PARAMS,
            ...(res.params ?? {}),
          });
        }
      })
      .catch(() => {
        // Keep localStorage fallback if server fetch fails.
      });
    return () => {
      cancelled = true;
    };
  }, [symbolParam]);

  useEffect(() => {
    return () => {
      if (recomputeBadgeTimeoutRef.current) {
        clearTimeout(recomputeBadgeTimeoutRef.current);
      }
    };
  }, []);

  const handleApplyCoreAnalysisParams = useCallback(
    (core: AnalysisCoreParams) => {
      if (!symbolParam) return;
      const next = { ...analysisDevParams, ...core };
      setAnalysisDevParams(next);
      saveCoreAnalysisParams(symbolParam, core);
      void api
        .saveSymbolParams(symbolParam, next)
        .then(() => {
          showRecomputingBadge();
        })
        .catch(() => {
          // Keep local state even if persistence fails.
        });
    },
    [symbolParam, analysisDevParams, showRecomputingBadge],
  );

  const handleResetAnalysisParams = useCallback(() => {
    if (symbolParam) {
      clearCoreAnalysisParams(symbolParam);
    }
    setAnalysisDevParams({ ...DEFAULT_ANALYSIS_DEV_PARAMS });
  }, [symbolParam]);

  const handleResetServerDefaults = useCallback(() => {
    if (!symbolParam) return;
    clearCoreAnalysisParams(symbolParam);
    setAnalysisDevParams({ ...DEFAULT_ANALYSIS_DEV_PARAMS });
    void api
      .saveSymbolParams(symbolParam, {})
      .then(() => {
        showRecomputingBadge();
      })
      .catch(() => {
        // Keep local default state if server reset fails.
      });
  }, [symbolParam, showRecomputingBadge]);

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
        setFeaturedSetups(
          [...list].sort((a, b) => b.trend_score - a.trend_score),
        );
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

  // Pool used by the landing-state quick search. Prefer the
  // full universe if loaded; otherwise fall back to the
  // featured top-6 so search still works during initial load.
  // Zero-score markets are placeholders / unscored — never real
  // signals — so we exclude them from the browseable dropdown.
  const allLandingMarkets: Setup[] = (
    universeMarkets.length > 0 ? universeMarkets : featuredSetups
  ).filter((s) => (s.trend_score ?? 0) > 0);

  // Tab-filtered top 6 for the featured cards. The full sorted
  // list is kept in featuredSetups; we filter + slice per render
  // so switching tabs is instant and doesn't require a refetch.
  const displayedFeaturedSetups: Setup[] = featuredSetups
    .filter((s) => (s.trend_score ?? 0) > 0)
    .filter((s) => {
      if (featuredUniverse === "all") return true;
      const u = s.universe ?? _inferUniverseFrontend(s.symbol, s.category ?? "");
      return u === featuredUniverse;
    })
    .slice(0, 6);
  const landingSearchTrimmed = landingSearch.trim();
  const filteredLandingMarkets: Setup[] = landingSearchTrimmed
    ? allLandingMarkets.filter((s) => {
        const q = landingSearchTrimmed.toUpperCase();
        return (
          s.symbol.toUpperCase().includes(q) ||
          (s.display_name ?? "").toUpperCase().includes(q)
        );
      })
    : allLandingMarkets;

  // Floating dropdown is open when the user focuses the
  // input or types into it. The 6-card grid stays mounted
  // beneath; the dropdown overlays on top.
  const showLandingDropdown =
    landingSearchFocused || landingSearchTrimmed.length > 0;

  // While typing, cap the visible matches to keep the
  // dropdown snappy. While just browsing, show the full
  // universe scrollable.
  const displayMarkets: Setup[] = landingSearchTrimmed
    ? filteredLandingMarkets.slice(0, 50)
    : allLandingMarkets;

  // Category buckets shown in the dropdown, in a fixed
  // order so it always reads the same way.
  const CATEGORY_ORDER = [
    "equities",
    "forex",
    "indices",
    "commodity",
    "synthetic",
    "crypto",
  ];

  const groupedDisplayMarkets: { category: string; items: Setup[] }[] =
    CATEGORY_ORDER.map((cat) => ({
      category: cat.toUpperCase(),
      items: displayMarkets.filter(
        (s) => (s.category ?? "").toLowerCase() === cat,
      ),
    })).filter((g) => g.items.length > 0);

  // Anything whose category does not match the canonical
  // list above is collected under an "OTHER" bucket so we
  // never silently drop a row.
  const categorizedSymbols = new Set(
    groupedDisplayMarkets.flatMap((g) => g.items.map((s) => s.symbol)),
  );
  const uncategorizedDisplayMarkets = displayMarkets.filter(
    (s) => !categorizedSymbols.has(s.symbol),
  );
  if (uncategorizedDisplayMarkets.length > 0) {
    groupedDisplayMarkets.push({
      category: "OTHER",
      items: uncategorizedDisplayMarkets,
    });
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
              position: "relative",
              width: "100%",
              maxWidth: 400,
            }}
          >
            <input
              type="text"
              placeholder="Search any market..."
              value={landingSearch}
              onChange={(e) => handleLandingSearchChange(e.target.value)}
              onFocus={() => setLandingSearchFocused(true)}
              onBlur={() =>
                setTimeout(() => setLandingSearchFocused(false), 150)
              }
              autoFocus
              style={{
                width: "100%",
                background: "#111318",
                border: "1px solid #2A2E39",
                borderRadius: 2,
                padding: "10px 14px",
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 11,
                color: "#D1D4DC",
                outline: "none",
                boxSizing: "border-box",
                letterSpacing: "0.06em",
              }}
            />
            {landingSearchTrimmed ? (
              <div
                style={{
                  marginTop: 4,
                  fontSize: 8,
                  color: "#4A4D58",
                  fontFamily: "'IBM Plex Mono', monospace",
                  letterSpacing: "0.08em",
                }}
              >
                {filteredLandingMarkets.length} MARKETS FOUND
              </div>
            ) : null}

            {showLandingDropdown ? (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  right: 0,
                  marginTop: 4,
                  maxHeight: 420,
                  overflowY: "auto",
                  background: "#111318",
                  border: "1px solid #2A2E39",
                  borderRadius: 2,
                  zIndex: 100,
                  boxShadow: "0 8px 32px rgba(0,0,0,0.6)",
                }}
              >
                {displayMarkets.length === 0 ? (
                  <div
                    style={{
                      padding: "20px 14px",
                      fontFamily: "'IBM Plex Mono', monospace",
                      fontSize: 10,
                      color: "#4A4D58",
                      textAlign: "center",
                      letterSpacing: "0.08em",
                    }}
                  >
                    NO MARKETS FOUND
                  </div>
                ) : (
                  groupedDisplayMarkets.map((group) => {
                    const isCollapsed = collapsedCategories.has(group.category);
                    return (
                    <div key={group.category}>
                      <button
                        type="button"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          toggleCategory(group.category);
                        }}
                        style={{
                          position: "sticky",
                          top: 0,
                          width: "100%",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          padding: "6px 14px 4px 14px",
                          background: "#0D0F14",
                          fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 8,
                          letterSpacing: "0.12em",
                          color: "#F5A623",
                          textTransform: "uppercase",
                          borderBottom: "1px solid #1E222D",
                          border: "none",
                          cursor: "pointer",
                          textAlign: "left",
                        }}
                      >
                        <span>{group.category}</span>
                        <span style={{ fontSize: 8 }}>
                          {isCollapsed
                            ? `▶ ${group.items.length}`
                            : `▼ ${group.items.length}`}
                        </span>
                      </button>
                      {!isCollapsed && group.items.map((s) => {
                        const { glyph, color } = emptyStateTrendArrow(s.trend);
                        return (
                          <button
                            key={s.symbol}
                            type="button"
                            onMouseDown={() => {
                              router.push(
                                `/market?symbol=${encodeURIComponent(s.symbol)}&timeframe=1d`,
                              );
                            }}
                            style={{
                              width: "100%",
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              padding: "8px 14px",
                              background: "transparent",
                              border: "none",
                              borderBottom: "1px solid #1A1D24",
                              cursor: "pointer",
                              gap: 8,
                              textAlign: "left",
                            }}
                            onMouseEnter={(e) => {
                              (e.currentTarget as HTMLButtonElement).style.background =
                                "#1A1D24";
                            }}
                            onMouseLeave={(e) => {
                              (e.currentTarget as HTMLButtonElement).style.background =
                                "transparent";
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 2,
                                minWidth: 0,
                              }}
                            >
                              <span
                                style={{
                                  fontFamily: "'IBM Plex Mono', monospace",
                                  fontSize: 11,
                                  fontWeight: 700,
                                  color: "#D1D4DC",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                {s.symbol}
                              </span>
                              {s.display_name && s.display_name !== s.symbol ? (
                                <span
                                  style={{
                                    fontFamily: "'IBM Plex Mono', monospace",
                                    fontSize: 8,
                                    color: "#4A4D58",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                    whiteSpace: "nowrap",
                                  }}
                                >
                                  {s.display_name}
                                </span>
                              ) : null}
                            </div>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                flexShrink: 0,
                              }}
                            >
                              <span style={{ fontSize: 10, color }}>{glyph}</span>
                              <span
                                style={{
                                  fontFamily: "'IBM Plex Mono', monospace",
                                  fontSize: 10,
                                  fontWeight: 700,
                                  color: "#F5A623",
                                }}
                              >
                                {typeof s.trend_score === "number"
                                  ? s.trend_score.toFixed(1)
                                  : "—"}
                              </span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                    );
                  })
                )}
              </div>
            ) : null}
          </div>

          <div style={{ height: 20 }} />

          <div
            style={{
              display: "flex",
              gap: 4,
              marginBottom: 14,
            }}
          >
            {(
              [
                { key: "all", label: "ALL" },
                { key: "multi_asset", label: "MULTI-ASSET" },
                { key: "synthetic", label: "SYNTHETIC" },
                { key: "crypto", label: "CRYPTO" },
              ] as const
            ).map((tab) => {
              const active = featuredUniverse === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setFeaturedUniverse(tab.key)}
                  style={{
                    padding: "4px 10px",
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    fontFamily: "'IBM Plex Mono', monospace",
                    border: active ? "1px solid #F5A623" : "1px solid #1C1E24",
                    borderRadius: 2,
                    background: active ? "#F5A623" : "transparent",
                    color: active ? "#0D0F14" : "#787B86",
                    cursor: "pointer",
                    textTransform: "uppercase",
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

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
              : displayedFeaturedSetups.map((s) => {
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
      onResetServerDefaults={handleResetServerDefaults}
      isRecomputingParams={isRecomputingParams}
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