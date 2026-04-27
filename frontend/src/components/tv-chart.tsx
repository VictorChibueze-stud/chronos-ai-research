"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import type { BinanceCandle } from "@/lib/binance";
import type { ChartZone } from "@/lib/types";

interface TvChartProps {
  data: BinanceCandle[];
  zones: ChartZone[];
}

export function TvChart({ data, zones }: TvChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "var(--bg-surface)" },
        textColor: "var(--text-primary)",
        fontFamily: "'IBM Plex Mono', monospace",
      },
      grid: {
        vertLines: { color: "var(--border-default)" },
        horzLines: { color: "var(--border-default)" },
      },
      crosshair: { mode: 0 },
      rightPriceScale: {
        borderColor: "var(--border-default)",
      },
      timeScale: {
        borderColor: "var(--border-default)",
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#089981",
      borderUpColor: "#089981",
      wickUpColor: "#089981",
      downColor: "#f23645",
      borderDownColor: "#f23645",
      wickDownColor: "#f23645",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry || !chartRef.current) {
        return;
      }
      chartRef.current.applyOptions({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      });
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) {
      return;
    }

    seriesRef.current.setData(
      data.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) {
      return;
    }

    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    for (const zone of zones) {
      const line = series.createPriceLine({
        price: zone.price,
        color: zone.color,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        title: zone.title,
      });
      priceLinesRef.current.push(line);
    }
  }, [zones]);

  return <div ref={containerRef} className="h-full w-full" />;
}