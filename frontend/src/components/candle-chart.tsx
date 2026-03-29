"use client";

import { useEffect, useRef } from "react";
import {
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

import type { CandleBar, ChartStructuralLevel } from "@/lib/types";

interface CandleChartProps {
  candles: CandleBar[];
  candleTimestamps: Array<{ time: string }>;
  structuralLevels: ChartStructuralLevel[];
  showDrawings: boolean;
}

function depthHighTitle(depth: number): string {
  if (depth === 1) return "D1 CHoCH HIGH";
  if (depth === 2) return "D2 CHoCH HIGH";
  if (depth === 3) return "D3 CHoCH HIGH";
  return `D${depth} CHoCH HIGH`;
}

function depthLowTitle(depth: number): string {
  if (depth === 1) return "D1 CHoCH LOW";
  if (depth === 2) return "D2 CHoCH LOW";
  if (depth === 3) return "D3 CHoCH LOW";
  return `D${depth} CHoCH LOW`;
}

export default function CandleChart({ candles, candleTimestamps, structuralLevels, showDrawings }: CandleChartProps) {
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
      const time = Math.floor(new Date(candle.time).getTime() / 1000) as UTCTimestamp;
      if (!Number.isFinite(time)) {
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
      const time = Math.floor(new Date(candle.time).getTime() / 1000) as UTCTimestamp;
      if (!Number.isFinite(time)) {
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

    // Keep a minimal dependency on timestamp map so index->timestamp mapping
    // remains explicit in caller contracts even if candles already carry time.
    if (candleTimestamps.length === 0) {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().fitContent();
    }
  }, [candles, candleTimestamps]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries) {
      return;
    }

    clearOverlays();

    if (!showDrawings) {
      return;
    }

    const cleanupItems: Array<() => void> = [];

    for (const level of structuralLevels) {
      if (level.chochZone) {
        const zone = level.chochZone;
        const upperLine = candleSeries.createPriceLine({
          price: zone.upper,
          color: level.color,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: depthHighTitle(level.depth),
        });

        const lowerLine = candleSeries.createPriceLine({
          price: zone.lower,
          color: level.color,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: depthLowTitle(level.depth),
        });

        const midpointLine = candleSeries.createPriceLine({
          price: (zone.upper + zone.lower) / 2,
          color: `${level.color}44`,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
          title: "",
        });

        cleanupItems.push(() => {
          candleSeries.removePriceLine(upperLine);
          candleSeries.removePriceLine(lowerLine);
          candleSeries.removePriceLine(midpointLine);
        });
      }

      if (level.impulseStart && level.impulseEnd) {
        const impulseSeries = chart.addSeries(LineSeries, {
          color: level.color,
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        impulseSeries.setData([
          {
            time: level.impulseStart.time as UTCTimestamp,
            value: level.impulseStart.price,
          },
          {
            time: level.impulseEnd.time as UTCTimestamp,
            value: level.impulseEnd.price,
          },
        ]);

        cleanupItems.push(() => {
          chart.removeSeries(impulseSeries);
        });
      }

      if (typeof level.bosPrice === "number") {
        const isDown = level.impulseStart && level.impulseEnd
          ? level.impulseEnd.price < level.impulseStart.price
          : false;
        const bosLine = candleSeries.createPriceLine({
          price: level.bosPrice,
          color: level.bosColor ?? (isDown ? "#EF5350" : "#26A69A"),
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: "BOS",
        });

        cleanupItems.push(() => {
          candleSeries.removePriceLine(bosLine);
        });
      }
    }

    overlayCleanupRef.current = cleanupItems;

    return () => {
      clearOverlays();
    };
  }, [structuralLevels, showDrawings]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
