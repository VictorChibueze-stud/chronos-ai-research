"use client";

import { useEffect, useRef } from "react";
import {
  BaselineSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import type {
  BosLevel,
  CandleBar,
  CandidateMovePayload,
  CandidateMoveTealStructure,
  ChochLevel,
  ChochZone,
  StructureChochZone,
  TrendLeg,
  PaperTradeLevels,
  TrendWindowStructure,
  WalkerLevel,
} from "@/lib/types";
import {
  CHART_CHOCH_DEPTH1_BLUE,
  CHART_GLOBAL_CHOCH_AMBER,
  CHART_INTERNAL_CHOCH_TEAL,
  STRUCTURE_CANDIDATE_MOVE,
} from "@/lib/structure-colors";

const CANDIDATE_IMPULSE_COLOR = "#00C853";
const CANDIDATE_RETRACEMENT_COLOR = "#D50000";
const WALKER_DEPTH_COLORS: Record<number, string> = {
  1: "#2196F3",
  2: "#4CAF50",
  3: "#9C27B0",
};
const BOS_CLASS_COLORS: Record<string, string> = {
  true: "#00C853",
  false: "#D50000",
  pending: "#9E9E9E",
  broken: "#FFFFFF",
};
const WALKER_ZONE_ALPHA = 0.05;

/** API may send Python `internal_structure.legs` until fully normalized. */
type LegInput = TrendLeg & { internal_structure?: { legs?: TrendLeg[] } };
type CandidatePrimeImpulseInput = {
  start_timestamp?: string | null;
  start_price?: number;
  end_price?: number | null;
  internal_structure?: { legs?: TrendLeg[] };
  choch_zone?: StructureChochZone | null;
};

function internalLegsList(leg: LegInput): TrendLeg[] {
  const direct = leg.internal_legs;
  if (direct && direct.length > 0) {
    return direct;
  }
  const fromStructure = leg.internal_structure?.legs;
  return fromStructure ?? [];
}

interface CandleChartProps {
  candles: CandleBar[];
  trend: string;
  legs?: TrendLeg[];
  bosLevels?: BosLevel[];
  chochLevel?: ChochLevel | null;
  chochZones?: ChochZone[];
  /** Primary global CHoCH band from GET /api/analysis (replaces CHoCH line when set). */
  globalChochZone?: StructureChochZone | null;
  /** CHoCH band for the last confirmed impulse internal trend. */
  internalChochZone?: StructureChochZone | null;
  /** Sub-trend stack from CHoCH candidate pivot (teal BOS + CHoCH bands). */
  candidateMoveTealStructure?: CandidateMoveTealStructure | null;
  /** Last confirmed retracement end → current bar (developing structure). */
  provisionalDeveloping?: { start_timestamp: string; start_price: number } | null;
  trendStartOverlay?: {
    start_timestamp: string;
    start_price: number;
    current_timestamp: string;
    current_price: number;
    trend: string;
  } | null;
  trendWindowStructure?: TrendWindowStructure | null;
  showGlobalLegs?: boolean;
  showGlobalBos?: boolean;
  showGlobalChochZone?: boolean;
  showGlobalIchochZone?: boolean;
  showPrimeLegs?: boolean;
  showPrimeIchochZone?: boolean;
  showWalkerDepthRects?: boolean;
  showWalkerBosLines?: boolean;
  showCandidateLegs?: boolean;
  showCandidateChochZone?: boolean;
  showCandidateIchochZone?: boolean;
  showCandidatePrimeLegs?: boolean;
  showCandidatePrimeChoch?: boolean;
  walkerLevels?: WalkerLevel[];
  bosClassifications?: Record<string, string>;
  primeImpulseStructure?: {
    legs: TrendLeg[];
    source_tf?: string;
    choch_zone?: StructureChochZone | null;
  } | null;
  candidatePrimeImpulse?: CandidatePrimeImpulseInput | null;
  candidatePrimeChochZone?: StructureChochZone | null;
  /** Walker levels computed on the candidate prime retracement window. */
  candidateWalker?: CandidateMovePayload["candidate_walker"];
  /** When false, only candles/volume render; structural overlays load after parent analysis is ready. */
  showAnalysisOverlays?: boolean;
  isSwitchingTimeframe?: boolean;
  openPaperTrade?: PaperTradeLevels | null;
  showPaperTradeOverlays?: boolean;
}

function candleTimeSeconds(c: CandleBar): UTCTimestamp | null {
  const t = Math.floor(new Date(c.time).getTime() / 1000) as UTCTimestamp;
  return Number.isFinite(t) ? t : null;
}

/** Nearest candle by absolute unix time difference (cross-TF: e.g. 5m timestamps on 1H chart). */
function findCandleIndexByTime(candles: CandleBar[], isoTime: string | null | undefined): number {
  if (!isoTime) {
    return -1;
  }
  const targetSec = Math.floor(new Date(isoTime).getTime() / 1000);
  if (!Number.isFinite(targetSec)) {
    return -1;
  }
  if (candles.length === 0) {
    return -1;
  }
  let bestIdx = -1;
  let bestDiff = Infinity;
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]!;
    const candleTime =
      typeof c.time === "string"
        ? Math.floor(new Date(c.time).getTime() / 1000)
        : Number(c.time);
    if (!Number.isFinite(candleTime)) {
      continue;
    }
    const diff = Math.abs(candleTime - targetSec);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIdx = i;
    }
  }
  return bestIdx;
}

/** 6-digit hex + alpha byte (e.g. 15% → 26, 60% → 99). */
function hexWithAlphaByte(color: string, alphaByte: string): string {
  const raw = color.trim().replace(/^#/, "");
  const six = raw.length >= 6 ? raw.slice(0, 6) : "2962FF";
  return `#${six}${alphaByte}`;
}

export default function CandleChart({
  candles,
  trend,
  legs = [],
  bosLevels = [],
  chochLevel = null,
  chochZones = [],
  globalChochZone = null,
  internalChochZone = null,
  candidateMoveTealStructure = null,
  provisionalDeveloping = null,
  trendStartOverlay = null,
  trendWindowStructure = null,
  showGlobalLegs = true,
  showGlobalBos = true,
  showGlobalChochZone = true,
  showGlobalIchochZone = true,
  showPrimeLegs = true,
  showPrimeIchochZone = true,
  showWalkerDepthRects = true,
  showWalkerBosLines = true,
  showCandidateLegs = true,
  showCandidateChochZone = true,
  showCandidateIchochZone = true,
  showCandidatePrimeLegs = true,
  showCandidatePrimeChoch = true,
  walkerLevels = [],
  bosClassifications = {},
  primeImpulseStructure = null,
  candidatePrimeImpulse = null,
  candidatePrimeChochZone = null,
  candidateWalker = null,
  showAnalysisOverlays = true,
  isSwitchingTimeframe: _isSwitchingTimeframe = false,
  openPaperTrade = null,
  showPaperTradeOverlays = false,
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlayCleanupRef = useRef<Array<() => void>>([]);

  const clearOverlays = () => {
    for (const cleanup of overlayCleanupRef.current) {
      cleanup();
    }
    overlayCleanupRef.current = [];
  };

  const trendIsDown = trend === "down";

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 420,
      layout: {
        background: { type: ColorType.Solid, color: "#111318" },
        textColor: "#787B86",
      },
      grid: {
        vertLines: { color: "#1C1E24" },
        horzLines: { color: "#1C1E24" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1C1E24" },
      timeScale: {
        borderColor: "#1C1E24",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#4CAF7D",
      downColor: "#E05A5A",
      borderUpColor: "#4CAF7D",
      borderDownColor: "#E05A5A",
      wickUpColor: "#4CAF7D",
      wickDownColor: "#E05A5A",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "#1C1E24",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });

    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      chart.applyOptions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });

    observer.observe(container);

    return () => {
      observer.disconnect();
      clearOverlays();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!chart || !candleSeries || !volumeSeries) {
      return;
    }

    const parsedCandles: CandlestickData<UTCTimestamp>[] = [];
    for (const candle of candles) {
      const time = candleTimeSeconds(candle);
      if (time === null) {
        continue;
      }
      parsedCandles.push({
        time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
    }

    const seenCandleTimes = new Set<number>();
    const dedupedCandles = parsedCandles
      .filter((c) => {
        if (seenCandleTimes.has(c.time as number)) return false;
        seenCandleTimes.add(c.time as number);
        return true;
      })
      .sort((a, b) => (a.time as number) - (b.time as number));

    candleSeries.setData(dedupedCandles);

    const volumeData: HistogramData<UTCTimestamp>[] = [];
    for (const candle of candles) {
      const time = candleTimeSeconds(candle);
      if (time === null) {
        continue;
      }
      volumeData.push({
        time,
        value: candle.volume,
        color: candle.close >= candle.open ? "#4CAF7D66" : "#E05A5A66",
      });
    }

    const seenVolumeTimes = new Set<number>();
    const dedupedVolume = volumeData
      .filter((c) => {
        if (seenVolumeTimes.has(c.time as number)) return false;
        seenVolumeTimes.add(c.time as number);
        return true;
      })
      .sort((a, b) => (a.time as number) - (b.time as number));

    volumeSeries.setData(dedupedVolume);
    chart.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) {
      return;
    }

    clearOverlays();

    if (!showAnalysisOverlays) {
      overlayCleanupRef.current = [];
      return;
    }

    const structureAllOff =
      !showGlobalLegs &&
      !showGlobalBos &&
      !showGlobalChochZone &&
      !showGlobalIchochZone &&
      !showPrimeLegs &&
      !showPrimeIchochZone &&
      !showWalkerDepthRects &&
      !showWalkerBosLines &&
      !showCandidateLegs &&
      !showCandidateChochZone &&
      !showCandidateIchochZone &&
      !showCandidatePrimeLegs &&
      !showCandidatePrimeChoch;
    const paperOverlayOn = Boolean(showPaperTradeOverlays && openPaperTrade);
    if (structureAllOff && !paperOverlayOn) {
      return;
    }

    const cleanupItems: Array<() => void> = [];
    const n = candles.length;
    if (n === 0) {
      overlayCleanupRef.current = cleanupItems;
      return;
    }

    const lastIdx = n - 1;

    const timeAt = (idx: number): UTCTimestamp | null => {
      if (idx < 0 || idx >= n) {
        return null;
      }
      return candleTimeSeconds(candles[idx]!);
    };

    // Layer 1 — outer leg diagonals (timestamps align to displayed candle slice, not full-series indices)
    if (showGlobalLegs !== false) {
      for (const leg of legs) {
        if (!leg.confirmed) {
          continue;
        }
        const startIdx = findCandleIndexByTime(candles, leg.start_timestamp);
        if (startIdx === -1) {
          continue;
        }
        let endIdx = findCandleIndexByTime(candles, leg.end_timestamp);
        if (endIdx === -1) {
          endIdx = lastIdx;
        }
        endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
        const startT = timeAt(startIdx);
        const endT = timeAt(endIdx);
        if (startT === null || endT === null) {
          continue;
        }
        if (startT === endT) {
          continue;
        }
        const startPrice = leg.start_price;
        const endPrice = leg.end_price ?? candles[endIdx]!.close;

        let color: string;
        if (trendIsDown) {
          color = leg.type === "impulse" ? "#EF5350" : "#26A69A";
        } else {
          color = leg.type === "impulse" ? "#26A69A" : "#EF5350";
        }

        const lineSeries = chart.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        });
        lineSeries.setData([
          { time: startT, value: startPrice },
          { time: endT, value: endPrice },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(lineSeries);
        });
      }
    }

    // Layer 2 — internal structure (black dashed), last confirmed impulse only
    const lastImpulseForInternals =
      [...legs].filter((l) => l.confirmed && l.type === "impulse").pop() ?? null;
    if (showPrimeLegs !== false) {
      for (const leg of legs as LegInput[]) {
        if (!leg.confirmed || leg.type !== "impulse") {
          continue;
        }
        if (leg !== lastImpulseForInternals) {
          continue;
        }

        for (const il of internalLegsList(leg)) {
          const startIdx = findCandleIndexByTime(candles, il.start_timestamp);
          if (startIdx === -1) {
            continue;
          }
          let endIdx = findCandleIndexByTime(candles, il.end_timestamp);
          if (endIdx === -1) {
            endIdx = lastIdx;
          }
          endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
          const startT = timeAt(startIdx);
          const endT = timeAt(endIdx);
          if (startT === null || endT === null) {
            continue;
          }
          if (startT === endT) {
            continue;
          }
          const startY = il.start_price;
          const endY =
            il.end_price !== null && il.end_price !== undefined ? il.end_price : candles[endIdx]!.close;

          const internalSeries = chart.addSeries(LineSeries, {
            color: "#434651",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          internalSeries.setData([
            { time: startT, value: startY },
            { time: endT, value: endY },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(internalSeries);
          });
        }
      }
    }

    // Layer 2b — developing move: last confirmed retracement end → current close (white dotted)
    if (provisionalDeveloping) {
      const pStart = findCandleIndexByTime(candles, provisionalDeveloping.start_timestamp);
      if (pStart !== -1) {
        const pStartT = timeAt(pStart);
        const pEndT = timeAt(lastIdx);
        const endPx = candles[lastIdx]!.close;
        if (pStartT !== null && pEndT !== null && pStartT !== pEndT) {
          const provSeries = chart.addSeries(LineSeries, {
            color: "#FFFFFF",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
            title: "",
          });
          provSeries.setData([
            { time: pStartT, value: provisionalDeveloping.start_price },
            { time: pEndT, value: endPx },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(provSeries);
          });
        }
      }
    }

    // Layer 3 — global BOS segments (impulse end → break bar or last bar)
    if (showGlobalBos !== false) {
      for (const level of bosLevels) {
        const startIdx = findCandleIndexByTime(candles, level.start_timestamp);
        if (startIdx === -1) {
          continue;
        }
        let endIdx = lastIdx;
        if (typeof level.end_index === "number" && Number.isFinite(level.end_index)) {
          const ei = Math.trunc(level.end_index);
          if (ei >= 0 && ei < n) {
            endIdx = ei;
          }
        } else if (level.broken && level.end_timestamp) {
          const ei = findCandleIndexByTime(candles, level.end_timestamp);
          if (ei !== -1) {
            endIdx = ei;
          }
        }
        endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
        const startT = timeAt(startIdx);
        const endT = timeAt(endIdx);
        if (startT === null || endT === null) {
          continue;
        }
        if (startT === endT) {
          continue;
        }
        const baseBosColor = (level.color && level.color.trim()) || "#2196F3";
        const bosSeries = chart.addSeries(LineSeries, {
          color: level.broken ? hexWithAlphaByte(baseBosColor, "88") : baseBosColor,
          lineWidth: level.broken ? 1 : 2,
          lineStyle: level.broken ? LineStyle.Dotted : LineStyle.Solid,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        });
        bosSeries.setData([
          { time: startT, value: level.price },
          { time: endT, value: level.price },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(bosSeries);
        });
      }
    }

    // Layer 3b — CHoCH rectangles from analysis (global amber, internal teal — fixed palette)
    const analysisChochBands: Array<{ zone: StructureChochZone; baseColor: string; title: string; showProp: boolean }> = [];
    if (showGlobalChochZone !== false && globalChochZone) {
      analysisChochBands.push({
        zone: globalChochZone,
        baseColor: CHART_GLOBAL_CHOCH_AMBER,
        title: "CHoCH",
        showProp: true,
      });
    }
    if (showPrimeIchochZone !== false && internalChochZone) {
      analysisChochBands.push({
        zone: internalChochZone,
        baseColor: CHART_INTERNAL_CHOCH_TEAL,
        title: "iCHoCH",
        showProp: true,
      });
    }
    for (const { zone, baseColor, title } of analysisChochBands) {
        const zStart = findCandleIndexByTime(candles, zone.start_timestamp);
        if (zStart === -1) {
          continue;
        }
        let zEnd = findCandleIndexByTime(candles, zone.end_timestamp);
        if (zEnd === -1) {
          zEnd = lastIdx;
        }
        zEnd = Math.min(Math.max(zEnd, zStart), lastIdx);
        const zST = timeAt(zStart);
        const zET = timeAt(zEnd);
        if (!zST || !zET || zST === zET) {
          continue;
        }
        const lower = Math.min(zone.lower_boundary, zone.upper_boundary);
        const upper = Math.max(zone.lower_boundary, zone.upper_boundary);
        if (!(upper > lower)) {
          continue;
        }
        const fillColor = hexWithAlphaByte(baseColor, "1A");
        const lineColor = hexWithAlphaByte(baseColor, "99");
        const band = chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: lower },
          topFillColor1: fillColor,
          topFillColor2: fillColor,
          bottomFillColor1: "#00000000",
          bottomFillColor2: "#00000000",
          topLineColor: "#00000000",
          bottomLineColor: "#00000000",
          lineWidth: 1,
          lineVisible: false,
          baseLineVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
          title: "",
        });
        band.setData([
          { time: zST, value: upper },
          { time: zET, value: upper },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(band);
        });
        for (const bPrice of [upper, lower]) {
          const bLine = chart.addSeries(LineSeries, {
            color: lineColor,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
            title: bPrice === upper ? title : "",
          });
          bLine.setData([
            { time: zST, value: bPrice },
            { time: zET, value: bPrice },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(bLine);
          });
        }
      }

    // Layer 3c — CHoCH candidate move (teal BOS + bands on slice from pivot)
    if ((showCandidateLegs || showCandidateChochZone || showCandidateIchochZone || showCandidatePrimeLegs || showCandidatePrimeChoch) && candidateMoveTealStructure) {
      const tealLegs = candidateMoveTealStructure.legs ?? [];
      if (showCandidateLegs !== false) {
        for (const leg of tealLegs) {
          if (!leg.confirmed) {
            continue;
          }
          const startIdx = findCandleIndexByTime(candles, leg.start_timestamp);
          if (startIdx === -1) {
            continue;
          }
          let endIdx = findCandleIndexByTime(candles, leg.end_timestamp);
          if (endIdx === -1) {
            endIdx = lastIdx;
          }
          endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
          const startT = timeAt(startIdx);
          const endT = timeAt(endIdx);
          if (startT === null || endT === null) {
            continue;
          }
          const effectiveEndT = startT === endT
            ? timeAt(Math.min(endIdx + 1, lastIdx))
            : endT;
          if (effectiveEndT === null) {
            continue;
          }

          const isCandidateStyle = leg.render_style === "candidate";
          const color = isCandidateStyle
            ? leg.type === "impulse"
              ? "#26A69A"
              : "#EF5350"
            : STRUCTURE_CANDIDATE_MOVE;

          const tealLegSeries = chart.addSeries(LineSeries, {
            color,
            lineWidth: 2,
            lineStyle: isCandidateStyle ? LineStyle.Dashed : LineStyle.Solid,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          tealLegSeries.setData([
            { time: startT, value: leg.start_price },
            { time: effectiveEndT, value: leg.end_price ?? candles[endIdx]!.close },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(tealLegSeries);
          });
        }
      }

      const tealBos = candidateMoveTealStructure.bos_levels ?? [];
      if (showCandidateChochZone !== false) {
        for (const level of tealBos) {
        const startIdx = findCandleIndexByTime(candles, level.start_timestamp);
        if (startIdx === -1) {
          continue;
        }
        let endIdx = lastIdx;
        // Slice stack uses bar indices relative to the pivot window; do not use end_index on the full chart.
        if (level.end_timestamp) {
          const ei = findCandleIndexByTime(candles, level.end_timestamp);
          if (ei !== -1) {
            endIdx = ei;
          }
        }
        endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
        const startT = timeAt(startIdx);
        const endT = timeAt(endIdx);
        if (startT === null || endT === null || startT === endT) {
          continue;
        }
        const baseTeal = (level.color && level.color.trim()) || STRUCTURE_CANDIDATE_MOVE;
        const tealBosSeries = chart.addSeries(LineSeries, {
          color: level.broken ? hexWithAlphaByte(baseTeal, "88") : baseTeal,
          lineWidth: level.broken ? 1 : 2,
          lineStyle: level.broken ? LineStyle.Dotted : LineStyle.Solid,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
          title: "cand BOS",
        });
        tealBosSeries.setData([
          { time: startT, value: level.price },
          { time: endT, value: level.price },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(tealBosSeries);
        });
      }
      }

      const tealChochBands: Array<{ zone: StructureChochZone; title: string }> = [];
      if (showCandidateIchochZone !== false && candidateMoveTealStructure.internal_choch_zone) {
        tealChochBands.push({
          zone: candidateMoveTealStructure.internal_choch_zone,
          title: "cand iCHoCH",
        });
      }
      for (const { zone, title } of tealChochBands) {
          const zStart = findCandleIndexByTime(candles, zone.start_timestamp);
          if (zStart === -1) {
            continue;
          }
          let zEnd = findCandleIndexByTime(candles, zone.end_timestamp);
          if (zEnd === -1) {
            zEnd = lastIdx;
          }
          zEnd = Math.min(Math.max(zEnd, zStart), lastIdx);
          const zST = timeAt(zStart);
          const zET = timeAt(zEnd);
          if (!zST || !zET || zST === zET) {
            continue;
          }
          const lower = Math.min(zone.lower_boundary, zone.upper_boundary);
          const upper = Math.max(zone.lower_boundary, zone.upper_boundary);
          if (!(upper > lower)) {
            continue;
          }
          const baseTeal = CHART_INTERNAL_CHOCH_TEAL;
          const fillColor = hexWithAlphaByte(baseTeal, "0D");
          const lineColor = hexWithAlphaByte(baseTeal, "66");
          const band = chart.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: lower },
            topFillColor1: fillColor,
            topFillColor2: fillColor,
            bottomFillColor1: "#00000000",
            bottomFillColor2: "#00000000",
            topLineColor: "#00000000",
            bottomLineColor: "#00000000",
            lineWidth: 1,
            lineVisible: false,
            baseLineVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
            title: "",
          });
          band.setData([
            { time: zST, value: upper },
            { time: zET, value: upper },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(band);
          });
          for (const bPrice of [upper, lower]) {
            const bLine = chart.addSeries(LineSeries, {
              color: lineColor,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              lastValueVisible: false,
              priceLineVisible: false,
              crosshairMarkerVisible: false,
              title: bPrice === upper ? title : "",
            });
            bLine.setData([
              { time: zST, value: bPrice },
              { time: zET, value: bPrice },
            ]);
            cleanupItems.push(() => {
              chart.removeSeries(bLine);
            });
          }
        }

      // Candidate prime impulse internals (white dotted) and prime CHoCH zone.
      if (candidatePrimeImpulse) {
        const cPrimeInternalLegs = candidatePrimeImpulse.internal_structure?.legs ?? [];
        if (showCandidatePrimeLegs !== false) {
          for (const il of cPrimeInternalLegs) {
          if (!il.confirmed) {
            continue;
          }
          const startIdx = findCandleIndexByTime(candles, il.start_timestamp);
          if (startIdx === -1) {
            continue;
          }
          let endIdx = findCandleIndexByTime(candles, il.end_timestamp);
          if (endIdx === -1) {
            endIdx = lastIdx;
          }
          endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
          const startT = timeAt(startIdx);
          const endT = timeAt(endIdx);
          if (!startT || !endT || startT === endT) {
            continue;
          }
          const cPrimeInternalSeries = chart.addSeries(LineSeries, {
            color: "#FFFFFF",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          cPrimeInternalSeries.setData([
            { time: startT, value: il.start_price },
            { time: endT, value: il.end_price ?? candles[endIdx]!.close },
          ]);
          cleanupItems.push(() => {
            chart.removeSeries(cPrimeInternalSeries);
          });
        }
        }

        const cPrimeZone =
          showCandidatePrimeChoch !== false
            ? candidatePrimeChochZone ??
              candidatePrimeImpulse.choch_zone ??
              null
            : null;
        if (cPrimeZone) {
          const zoneStartIdx = findCandleIndexByTime(
            candles,
            candidatePrimeImpulse.start_timestamp,
          );
          const zStart = zoneStartIdx !== -1 ? timeAt(zoneStartIdx) : timeAt(0);
          const zEnd = timeAt(lastIdx);
          const lower = Math.min(cPrimeZone.lower_boundary, cPrimeZone.upper_boundary);
          const upper = Math.max(cPrimeZone.lower_boundary, cPrimeZone.upper_boundary);
          if (zStart && zEnd && zStart !== zEnd && upper > lower) {
            const zoneFill = hexWithAlphaByte("#FF9800", "1A");
            const zoneLine = hexWithAlphaByte("#FF9800", "66");
            const cPrimeBand = chart.addSeries(BaselineSeries, {
              baseValue: { type: "price", price: lower },
              topFillColor1: zoneFill,
              topFillColor2: zoneFill,
              bottomFillColor1: "#00000000",
              bottomFillColor2: "#00000000",
              topLineColor: "#00000000",
              bottomLineColor: "#00000000",
              lineWidth: 1,
              lineVisible: false,
              baseLineVisible: false,
              lastValueVisible: false,
              priceLineVisible: false,
              crosshairMarkerVisible: false,
              title: "",
            });
            cPrimeBand.setData([
              { time: zStart, value: upper },
              { time: zEnd, value: upper },
            ]);
            cleanupItems.push(() => {
              chart.removeSeries(cPrimeBand);
            });
            for (const bPrice of [upper, lower]) {
              const cPrimeBoundary = chart.addSeries(LineSeries, {
                color: zoneLine,
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                lastValueVisible: false,
                priceLineVisible: false,
                crosshairMarkerVisible: false,
              });
              cPrimeBoundary.setData([
                { time: zStart, value: bPrice },
                { time: zEnd, value: bPrice },
              ]);
              cleanupItems.push(() => {
                chart.removeSeries(cPrimeBoundary);
              });
            }
          }
        }
      }
    }

    // Layer 4 — global CHoCH line disabled (global_choch_zone band replaces line)

    // Layer 5 — CHoCH zone rectangles (BaselineSeries fills between base = lower and value = upper;
    // lightweight-charts v5 AreaSeries fills to pane bottom, so Baseline is used for the band.)
    if (showWalkerDepthRects !== false && chochZones && chochZones.length > 0) {
      for (const zone of chochZones) {
        if (Number(zone.depth) !== 1) {
          continue;
        }
        const startIdx = findCandleIndexByTime(candles, zone.start_timestamp);
        if (startIdx === -1) {
          continue;
        }
        let endIdx = findCandleIndexByTime(candles, zone.end_timestamp);
        if (endIdx === -1) {
          endIdx = lastIdx;
        }
        endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
        const startTime = timeAt(startIdx);
        const endTime = timeAt(endIdx);
        if (startTime === null || endTime === null) {
          continue;
        }
        if (startTime === endTime) {
          continue;
        }
        const lower = Math.min(zone.lower_boundary, zone.upper_boundary);
        const upper = Math.max(zone.lower_boundary, zone.upper_boundary);
        if (!(upper > lower)) {
          continue;
        }
        const fillColor = hexWithAlphaByte(CHART_CHOCH_DEPTH1_BLUE, "26");
        const lineColor = hexWithAlphaByte(CHART_CHOCH_DEPTH1_BLUE, "99");

        const bandSeries = chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: lower },
          topFillColor1: fillColor,
          topFillColor2: fillColor,
          bottomFillColor1: "#00000000",
          bottomFillColor2: "#00000000",
          topLineColor: "#00000000",
          bottomLineColor: "#00000000",
          lineWidth: 1,
          lineVisible: false,
          baseLineVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
          title: "",
        });
        bandSeries.setData([
          { time: startTime, value: upper },
          { time: endTime, value: upper },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(bandSeries);
        });

        const upperSeries = chart.addSeries(LineSeries, {
          color: lineColor,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: `D${zone.depth} CHoCH`,
        });
        upperSeries.setData([
          { time: startTime, value: upper },
          { time: endTime, value: upper },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(upperSeries);
        });

        const lowerSeries = chart.addSeries(LineSeries, {
          color: lineColor,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        lowerSeries.setData([
          { time: startTime, value: lower },
          { time: endTime, value: lower },
        ]);
        cleanupItems.push(() => {
          chart.removeSeries(lowerSeries);
        });
      }
    }

    // Layer 5b — Walker depth CHoCH zones (BaselineSeries, full chart width)
    if (showWalkerDepthRects !== false && walkerLevels && walkerLevels.length > 0) {
      for (const level of walkerLevels) {
        const depth = level.depth ?? 1;
        const color = WALKER_DEPTH_COLORS[depth] ?? "#607D8B";
        const zone = level.choch_zone;
        if (!zone) continue;

        const lower = Math.min(zone.lower_boundary, zone.upper_boundary);
        const upper = Math.max(zone.lower_boundary, zone.upper_boundary);
        if (!(upper > lower)) continue;

        const startT = timeAt(0);
        const endT = timeAt(lastIdx);
        if (!startT || !endT) continue;

        const fillColor = hexWithAlphaByte(color, "0D");
        const lineColor = hexWithAlphaByte(color, "55");

        const bandSeries = chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: lower },
          topFillColor1: fillColor,
          topFillColor2: fillColor,
          bottomFillColor1: "#00000000",
          bottomFillColor2: "#00000000",
          topLineColor: "#00000000",
          bottomLineColor: "#00000000",
          lineWidth: 1,
          lineVisible: false,
          baseLineVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
          title: "",
        });
        bandSeries.setData([
          { time: startT, value: upper },
          { time: endT, value: upper },
        ]);
        cleanupItems.push(() => chart.removeSeries(bandSeries));

        for (const bPrice of [upper, lower]) {
          const bLine = chart.addSeries(LineSeries, {
            color: lineColor,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          bLine.setData([
            { time: startT, value: bPrice },
            { time: endT, value: bPrice },
          ]);
          cleanupItems.push(() => chart.removeSeries(bLine));
        }
      }
    }

    // Layer 5c — BOS classification dotted lines
    if (showWalkerBosLines !== false && walkerLevels && bosClassifications) {
      for (const level of walkerLevels) {
        const depth = level.depth ?? 1;
        const key = `depth_${depth}`;
        const classification = bosClassifications[key] ?? "broken";
        const color = BOS_CLASS_COLORS[classification] ?? "#FFFFFF";
        const structLvl = level.structural_level;
        if (!structLvl?.price) continue;

        const bosStartIdx = Math.floor(candles.length * 0.3);
        const startT = timeAt(bosStartIdx);
        const endT = timeAt(lastIdx);
        if (!startT || !endT || startT === endT) continue;

        const bosSeries = chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        });
        bosSeries.setData([
          { time: startT, value: structLvl.price },
          { time: endT, value: structLvl.price },
        ]);
        cleanupItems.push(() => chart.removeSeries(bosSeries));
      }
    }

    // Layer 5d — Candidate walker depth CHoCH zones (BaselineSeries, full chart width)
    if (showWalkerDepthRects !== false && candidateWalker?.levels && candidateWalker.levels.length > 0) {
      for (const level of candidateWalker.levels) {
        const depth = level.depth ?? 1;
        const color = WALKER_DEPTH_COLORS[depth] ?? "#607D8B";
        const zone = level.choch_zone;
        if (!zone) continue;

        const lower = Math.min(zone.lower_boundary, zone.upper_boundary);
        const upper = Math.max(zone.lower_boundary, zone.upper_boundary);
        if (!(upper > lower)) continue;

        const startT = timeAt(0);
        const endT = timeAt(lastIdx);
        if (!startT || !endT) continue;

        const fillColor = hexWithAlphaByte(color, "09");
        const lineColor = hexWithAlphaByte(color, "44");

        const bandSeries = chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: lower },
          topFillColor1: fillColor,
          topFillColor2: fillColor,
          bottomFillColor1: "#00000000",
          bottomFillColor2: "#00000000",
          topLineColor: "#00000000",
          bottomLineColor: "#00000000",
          lineWidth: 1,
          lineVisible: false,
          baseLineVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
          title: "",
        });
        bandSeries.setData([
          { time: startT, value: upper },
          { time: endT, value: upper },
        ]);
        cleanupItems.push(() => chart.removeSeries(bandSeries));

        for (const bPrice of [upper, lower]) {
          const bLine = chart.addSeries(LineSeries, {
            color: lineColor,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          bLine.setData([
            { time: startT, value: bPrice },
            { time: endT, value: bPrice },
          ]);
          cleanupItems.push(() => chart.removeSeries(bLine));
        }
      }
    }

    // Layer 6 — Trend start overlay (standalone test visualization)
    if (trendStartOverlay) {
      const startIdx = findCandleIndexByTime(candles, trendStartOverlay.start_timestamp);
      const endIdx = candles.length - 1;
      if (startIdx !== -1) {
        const startT = timeAt(startIdx);
        const endT = timeAt(endIdx);
        if (startT !== null && endT !== null && startT !== endT) {
          const trendLine = chart.addSeries(LineSeries, {
            color: "#4A4E5A",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
            title: `TREND ${trendStartOverlay.trend.toUpperCase()}`,
          });
          trendLine.setData([
            { time: startT, value: trendStartOverlay.start_price },
            { time: endT, value: trendStartOverlay.current_price },
          ]);
          cleanupItems.push(() => chart.removeSeries(trendLine));
        }
      }
    }

    // Layer 7 — Windowed trend structure: legs, BOS (window CHoCH band omitted — analysis zones only)
    if (trendWindowStructure) {
      const wLegs = trendWindowStructure.legs ?? [];
      const lastWImpulseForInternals =
        [...wLegs].filter((l) => l.confirmed && l.type === "impulse").pop() ?? null;

      // 7a — Red/green leg diagonal lines (colors follow parent `trend`, not window-local trend)
      if (showGlobalLegs !== false) {
        for (const leg of wLegs) {
          if (!leg.confirmed) continue;
          const startIdx = findCandleIndexByTime(candles, leg.start_timestamp);
          if (startIdx === -1) continue;
          let endIdx = findCandleIndexByTime(candles, leg.end_timestamp);
          if (endIdx === -1) endIdx = lastIdx;
          endIdx = Math.min(Math.max(endIdx, startIdx), lastIdx);
          const startT = timeAt(startIdx);
          const endT = timeAt(endIdx);
          if (!startT || !endT || startT === endT) continue;
          const color = trendIsDown
            ? leg.type === "impulse"
              ? "#EF5350"
              : "#26A69A"
            : leg.type === "impulse"
              ? "#26A69A"
              : "#EF5350";
          const legSeries = chart.addSeries(LineSeries, {
            color,
            lineWidth: 2,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
          });
          legSeries.setData([
            { time: startT, value: leg.start_price },
            { time: endT, value: leg.end_price ?? candles[endIdx]!.close },
          ]);
          cleanupItems.push(() => chart.removeSeries(legSeries));

          // 7b — Internal dashed lines inside last confirmed impulse only
          if (leg.type === "impulse" && leg === lastWImpulseForInternals) {
            for (const il of leg.internal_legs ?? []) {
              const ilStart = findCandleIndexByTime(candles, il.start_timestamp);
              if (ilStart === -1) continue;
              let ilEnd = findCandleIndexByTime(candles, il.end_timestamp);
              if (ilEnd === -1) ilEnd = endIdx;
              ilEnd = Math.min(Math.max(ilEnd, ilStart), endIdx);
              const ilT = timeAt(ilStart);
              const ilET = timeAt(ilEnd);
              if (!ilT || !ilET || ilT === ilET) continue;
              const ilSeries = chart.addSeries(LineSeries, {
                color: "#434651",
                lineWidth: 1,
                lineStyle: LineStyle.Dashed,
                lastValueVisible: false,
                priceLineVisible: false,
                crosshairMarkerVisible: false,
              });
              ilSeries.setData([
                { time: ilT, value: il.start_price },
                { time: ilET, value: il.end_price ?? candles[ilEnd]!.close },
              ]);
              cleanupItems.push(() => chart.removeSeries(ilSeries));
            }
          }
        }
      }

      // 7d — BOS levels
      if (showGlobalBos !== false) {
        for (const bos of trendWindowStructure.bos_levels ?? []) {
          const bStart = findCandleIndexByTime(candles, bos.start_timestamp);
          if (bStart === -1) continue;
          let bEnd = lastIdx;
          if (typeof bos.end_index === "number" && Number.isFinite(bos.end_index)) {
            const ei = Math.trunc(bos.end_index);
            if (ei >= 0 && ei < n) {
              bEnd = ei;
            }
          } else if (bos.broken && bos.end_timestamp) {
            const ei = findCandleIndexByTime(candles, bos.end_timestamp);
            if (ei !== -1) bEnd = ei;
          }
          bEnd = Math.min(Math.max(bEnd, bStart), lastIdx);
          const bST = timeAt(bStart);
          const bET = timeAt(bEnd);
          if (!bST || !bET || bST === bET) continue;
          const bosSeries = chart.addSeries(LineSeries, {
            color: bos.broken ? "#2196F388" : "#2196F3",
            lineWidth: bos.broken ? 1 : 2,
            lineStyle: bos.broken ? LineStyle.Dotted : LineStyle.Solid,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
            title: bos.broken ? "BOS ✗" : "BOS",
          });
          bosSeries.setData([
            { time: bST, value: bos.price },
            { time: bET, value: bos.price },
          ]);
          cleanupItems.push(() => chart.removeSeries(bosSeries));
        }
      }
    }

    if (paperOverlayOn && openPaperTrade) {
      const t0 = timeAt(0);
      const t1Raw = timeAt(lastIdx);
      if (t0 && t1Raw) {
        const t1 = t0 === t1Raw ? (((t0 as number) + 1) as UTCTimestamp) : t1Raw;
        const entry = openPaperTrade.entry_price;
        const stop = openPaperTrade.stop_price;
        const tp = openPaperTrade.take_profit_price;
        const fmt = (p: number) => {
          if (Math.abs(p) >= 1000) return p.toFixed(2);
          if (Math.abs(p) >= 10) return p.toFixed(4);
          return p.toFixed(5);
        };
        if (tp != null && Number.isFinite(tp)) {
          const lower = Math.min(stop, tp);
          const upper = Math.max(stop, tp);
          if (upper > lower) {
            const zoneBand = chart.addSeries(BaselineSeries, {
              baseValue: { type: "price", price: lower },
              topFillColor1: "rgba(123,97,255,0.05)",
              topFillColor2: "rgba(123,97,255,0.05)",
              bottomFillColor1: "#00000000",
              bottomFillColor2: "#00000000",
              topLineColor: "#00000000",
              bottomLineColor: "#00000000",
              lineWidth: 1,
              lineVisible: false,
              baseLineVisible: false,
              lastValueVisible: false,
              priceLineVisible: false,
              crosshairMarkerVisible: false,
            });
            zoneBand.setData([
              { time: t0, value: upper },
              { time: t1, value: upper },
            ]);
            cleanupItems.push(() => chart.removeSeries(zoneBand));
          }
        }
        const addPaperHLine = (price: number, color: string, title: string) => {
          const s = chart.addSeries(LineSeries, {
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lastValueVisible: true,
            priceLineVisible: true,
            crosshairMarkerVisible: false,
            title,
          });
          s.setData([
            { time: t0, value: price },
            { time: t1, value: price },
          ]);
          cleanupItems.push(() => chart.removeSeries(s));
        };
        addPaperHLine(entry, "#7B61FF", `ENTRY ${fmt(entry)}`);
        addPaperHLine(stop, "#FF1744", `STOP ${fmt(stop)}`);
        if (tp != null && Number.isFinite(tp)) {
          addPaperHLine(tp, "#00C853", `TP ${fmt(tp)}`);
        }
      }
    }

    overlayCleanupRef.current = cleanupItems;

    return () => {
      clearOverlays();
    };
  }, [
    candles,
    trendIsDown,
    legs,
    bosLevels,
    chochLevel,
    chochZones,
    globalChochZone,
    internalChochZone,
    candidateMoveTealStructure,
    provisionalDeveloping,
    trendStartOverlay,
    trendWindowStructure,
    walkerLevels,
    bosClassifications,
    showGlobalLegs,
    showGlobalBos,
    showGlobalChochZone,
    showGlobalIchochZone,
    showPrimeLegs,
    showPrimeIchochZone,
    showWalkerDepthRects,
    showWalkerBosLines,
    showCandidateLegs,
    showCandidateChochZone,
    showCandidateIchochZone,
    showCandidatePrimeLegs,
    showCandidatePrimeChoch,
    candidatePrimeImpulse,
    candidatePrimeChochZone,
    candidateWalker,
    showAnalysisOverlays,
    openPaperTrade,
    showPaperTradeOverlays,
  ]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
