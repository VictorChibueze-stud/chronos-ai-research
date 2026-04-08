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
  CandidateMoveTealStructure,
  ChochLevel,
  ChochZone,
  StructureChochZone,
  TrendLeg,
  TrendWindowStructure,
} from "@/lib/types";
import {
  CHART_CHOCH_DEPTH1_BLUE,
  CHART_GLOBAL_CHOCH_AMBER,
  CHART_INTERNAL_CHOCH_TEAL,
  STRUCTURE_CANDIDATE_MOVE,
} from "@/lib/structure-colors";

/** API may send Python `internal_structure.legs` until fully normalized. */
type LegInput = TrendLeg & { internal_structure?: { legs?: TrendLeg[] } };

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
  showBOS?: boolean;
  showCHoCH?: boolean;
  showLines?: boolean;
  /** When false, only candles/volume render; structural overlays load after parent analysis is ready. */
  showAnalysisOverlays?: boolean;
  isSwitchingTimeframe?: boolean;
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
  showBOS = true,
  showCHoCH = true,
  showLines = true,
  showAnalysisOverlays = true,
  isSwitchingTimeframe: _isSwitchingTimeframe = false,
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

    if (showLines === false && showBOS === false && showCHoCH === false) {
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
    if (showLines !== false) {
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
    if (showLines !== false) {
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
    if (showBOS !== false) {
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
    const analysisChochBands: Array<{ zone: StructureChochZone; baseColor: string; title: string }> = [];
    if (globalChochZone) {
      analysisChochBands.push({
        zone: globalChochZone,
        baseColor: CHART_GLOBAL_CHOCH_AMBER,
        title: "CHoCH",
      });
    }
    if (internalChochZone) {
      analysisChochBands.push({
        zone: internalChochZone,
        baseColor: CHART_INTERNAL_CHOCH_TEAL,
        title: "iCHoCH",
      });
    }
    if (showCHoCH !== false) {
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
    }

    // Layer 3c — CHoCH candidate move (teal BOS + bands on slice from pivot)
    if (candidateMoveTealStructure) {
      const tealBos = candidateMoveTealStructure.bos_levels ?? [];
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
      const tealChochBands: Array<{ zone: StructureChochZone; title: string }> = [];
      if (candidateMoveTealStructure.internal_choch_zone) {
        tealChochBands.push({
          zone: candidateMoveTealStructure.internal_choch_zone,
          title: "cand iCHoCH",
        });
      }
      if (showCHoCH !== false) {
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
      }
    }

    // Layer 4 — global CHoCH line disabled (global_choch_zone band replaces line)

    // Layer 5 — CHoCH zone rectangles (BaselineSeries fills between base = lower and value = upper;
    // lightweight-charts v5 AreaSeries fills to pane bottom, so Baseline is used for the band.)
    if (showCHoCH !== false && chochZones && chochZones.length > 0) {
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
      if (showLines !== false) {
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
      if (showBOS !== false) {
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
    showBOS,
    showCHoCH,
    showLines,
    showAnalysisOverlays,
  ]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
