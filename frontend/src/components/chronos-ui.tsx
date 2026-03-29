"use client";

import { clsx, type ClassValue } from "clsx";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Area, AreaChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { twMerge } from "tailwind-merge";

export const C = {
  bg1: "#0D0F14", bg2: "#111318", bg3: "#1C1E24",
  border: "#1C1E24", border2: "#2A2E39",
  text1: "#E8E8EC", text2: "#C8C8D0", text3: "#6B6F7A", text4: "#3A3D48",
  amber: "#F5A623", amberDim: "#C8851A",
  bull: "#4CAF7D", bear: "#E05A5A",
  blue: "#3A6BFF",
  mono: "'IBM Plex Mono', monospace",
};

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ScoreBarProps {
  value: number;
}

interface PhaseStepsProps {
  step: number;
  total: number;
  direction: string;
}

interface DirectionTagProps {
  direction: string;
}

interface PhaseBadgeProps {
  phase: string;
}

interface TFBadgeProps {
  label: string;
}

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  highlight?: boolean;
}

interface ScoreRingProps {
  value: number;
  size?: number;
}

interface StatRowProps {
  label: string;
  value: string | number;
  valueColor?: string;
}

interface RingMetricProps {
  value: number;
  label: string;
  color?: string;
  size?: number;
}

interface EquityCurveProps {
  trades: any[];
}

interface EquityCurvePoint {
  index: number;
  tradeIndex: number;
  equity: number;
  peak: number;
  drawdown: number;
  inDrawdown: boolean;
}

interface EquityCurveTooltipProps {
  active?: boolean;
  payload?: Array<{ payload: EquityCurvePoint }>;
}

interface LabelProps {
  children: ReactNode;
  color?: string;
}

interface ValProps {
  children: ReactNode;
  color?: string;
  size?: number;
}

const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

const tokenTextColorClasses: Record<string, string> = {
  "#3A3D48": "text-text4",
  "#E8E8EC": "text-text1",
  "#C8C8D0": "text-text2",
  "#6B6F7A": "text-text3",
  "#F5A623": "text-brand-amber",
  "#C8851A": "text-brand-amberDim",
  "#5C4A1E": "text-[#5C4A1E]",
  "#4CAF7D": "text-signal-bull",
  "#E05A5A": "text-signal-bear",
  "#3A6BFF": "text-signal-blue",
  "#1C1E24": "text-border-faint",
  "#2A2E39": "text-border-strong",
};

const tokenBgColorClasses: Record<string, string> = {
  "#111318": "bg-background-panel",
  "#1C1E24": "bg-background-surface",
  "#F5A623": "bg-brand-amber",
  "#C8851A": "bg-brand-amberDim",
  "#5C4A1E": "bg-[#5C4A1E]",
  "#E05A5A": "bg-signal-bear",
};

const valSizeClasses: Record<number, string> = {
  11: "text-[11px]",
  13: "text-[13px]",
};

function Label({ children, color = "#3A3D48" }: LabelProps) {
  return (
    <span className={cn("font-mono text-[9px] tracking-[0.12em]", tokenTextColorClasses[color] ?? "text-text4")}>
      {children}
    </span>
  );
}

function Val({ children, color = "#E8E8EC", size = 13 }: ValProps) {
  return (
    <span className={cn("font-mono font-semibold", valSizeClasses[size] ?? "text-[13px]", tokenTextColorClasses[color] ?? "text-text1")}>
      {children}
    </span>
  );
}

export function ScoreBar({ value }: ScoreBarProps) {
  const fillColor = value >= 80 ? C.amber : value >= 60 ? C.amberDim : "#5C4A1E";
  const valueTextColor = value >= 80 ? C.amber : value >= 60 ? C.amberDim : C.text3;
  return (
    <div className="flex items-center gap-2">
      <div className="h-[3px] w-20 overflow-hidden rounded-[2px] bg-background-surface">
        <div
          className={cn("h-full transition-[width] duration-700 ease-out", tokenBgColorClasses[fillColor] ?? "bg-brand-amber")}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className={cn("min-w-7 font-mono text-[13px] font-bold", tokenTextColorClasses[valueTextColor] ?? "text-text3")}>
        {value}
      </span>
    </div>
  );
}

export function PhaseSteps({ step, total, direction }: PhaseStepsProps) {
  return (
    <div className="flex items-center gap-[3px]">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-2 w-2 rounded-[1px] border",
            i < step
              ? direction === "LONG"
                ? "border-transparent bg-brand-amber"
                : "border-transparent bg-signal-bear"
              : "border-border-strong bg-background-surface",
          )}
        />
      ))}
    </div>
  );
}

export function TFBadge({ label }: TFBadgeProps) {
  return (
    <span className="rounded-[2px] border border-border-strong px-[5px] py-[2px] font-mono text-[10px] tracking-[0.05em] text-text3">
      {label}
    </span>
  );
}

export function DirectionTag({ direction }: DirectionTagProps) {
  const isLong = direction === "LONG";
  return (
    <span
      className={cn(
        "rounded-[2px] border px-[7px] py-[3px] font-mono text-[10px] font-bold tracking-[0.08em]",
        isLong
          ? "border-brand-amber/25 bg-brand-amber/10 text-brand-amber"
          : "border-signal-bear/25 bg-signal-bear/10 text-signal-bear",
      )}
    >
      {direction}
    </span>
  );
}

export function PhaseBadge({ phase }: PhaseBadgeProps) {
  const isImpulse = phase === "IMPULSE";
  return (
    <span
      className={cn(
        "rounded-[2px] border border-border-strong px-[7px] py-[3px] font-mono text-[10px] tracking-[0.06em]",
        isImpulse ? "bg-white/[0.04] text-text2" : "bg-white/[0.02] text-text3",
      )}
    >
      {phase}
    </span>
  );
}

export function StatCard({ label, value, sub, highlight }: StatCardProps) {
  return (
    <div
      className={cn(
        "flex-1 border border-[#1C1E24] bg-background-panel px-[18px] py-[14px]",
        highlight ? "border-t-2 border-t-brand-amber" : "border-t border-t-[#1C1E24]",
      )}
    >
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-[#4A4D58]">{label}</div>
      <div className={cn("font-mono text-[22px] font-bold leading-none", highlight ? "text-brand-amber" : "text-text1")}>
        {value}
      </div>
      {sub && <div className="mt-1 font-mono text-[10px] text-[#4A4D58]">{sub}</div>}
    </div>
  );
}

export function ScoreRing({ value, size = 86 }: ScoreRingProps) {
  const color = value >= 80 ? "#F5A623" : value >= 60 ? "#C8851A" : "#5C4A1E";
  const r = 36, stroke = 5;
  const circ = 2 * Math.PI * r;
  const filled = (value / 100) * circ;
  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width={size} height={size} viewBox="0 0 86 86">
        <circle cx={43} cy={43} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-border-faint" />
        <circle cx={43} cy={43} r={r} fill="none" stroke="currentColor" strokeWidth={stroke}
          className={tokenTextColorClasses[color] ?? "text-brand-amber"}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeDashoffset={circ / 4}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 1s ease" }}
        />
        <text
          x={43}
          y={47}
          textAnchor="middle"
          fill="currentColor"
          className={tokenTextColorClasses[color] ?? "text-brand-amber"}
          style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700 }}
        >
          {value}
        </text>
      </svg>
      <Label color={color}>TREND SCORE</Label>
    </div>
  );
}

export function StatRow({ label, value, valueColor }: StatRowProps) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0" }}>
      <Label>{label}</Label>
      <Val color={valueColor || "#C8C8D0"} size={11}>{value}</Val>
    </div>
  );
}

function formatEquityTick(value: number) {
  if (Math.abs(value) >= 1000) {
    const abbreviated = value / 1000;
    const decimals = Number.isInteger(abbreviated) ? 0 : 1;
    return `$${abbreviated.toFixed(decimals)}k`;
  }

  return `$${Math.round(value)}`;
}

function EquityCurveTooltip({ active, payload }: EquityCurveTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0].payload;

  return (
    <div
      className="min-w-[168px] rounded-md border border-white/10 bg-[#10141dcc] px-3 py-2 text-text1 shadow-[0_18px_40px_rgba(0,0,0,0.42)] backdrop-blur-md"
      style={{ backdropFilter: "blur(14px)" }}
    >
      <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-text4">
        {point.tradeIndex === 0 ? "Start" : `Trade ${point.tradeIndex}`}
      </div>
      <div className="mt-1 font-mono text-[16px] font-bold text-brand-amber">
        {point.equity.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
      </div>
      <div className="mt-2 flex items-center justify-between gap-4 font-mono text-[10px] text-text3">
        <span>Drawdown</span>
        <span className={point.drawdown > 0 ? "text-signal-bear" : "text-signal-bull"}>
          {point.drawdown > 0 ? "-" : "+"}
          {Math.abs(point.drawdown).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
        </span>
      </div>
    </div>
  );
}

export function EquityCurve({ trades }: EquityCurveProps) {
  const gradientId = `${useId().replace(/:/g, "")}-equity-gradient`;
  const [isMounted, setIsMounted] = useState(false);
  const chartData: EquityCurvePoint[] = [{ index: 0, tradeIndex: 0, equity: 10000, peak: 10000, drawdown: 0, inDrawdown: false }];

  useEffect(() => {
    setIsMounted(true);
  }, []);

  let runningPeak = 10000;
  for (let index = 0; index < trades.length; index += 1) {
    const trade = trades[index];
    const equity = Number(trade?.equity ?? runningPeak);
    runningPeak = Math.max(runningPeak, equity);
    chartData.push({
      index: index + 1,
      tradeIndex: index + 1,
      equity,
      peak: runningPeak,
      drawdown: runningPeak - equity,
      inDrawdown: equity < runningPeak,
    });
  }

  const drawdownBands: Array<{ start: number; end: number }> = [];
  let bandStart: number | null = null;

  for (let index = 1; index < chartData.length; index += 1) {
    const point = chartData[index];
    if (point.inDrawdown && bandStart === null) {
      bandStart = chartData[index - 1].index;
    }

    if (!point.inDrawdown && bandStart !== null) {
      drawdownBands.push({ start: bandStart, end: point.index });
      bandStart = null;
    }
  }

  if (bandStart !== null) {
    drawdownBands.push({ start: bandStart, end: chartData[chartData.length - 1].index });
  }

  if (!isMounted) {
    return <div className="h-full min-h-[160px] w-full min-w-0 bg-background-base" />;
  }

  return (
    <div className="h-full min-h-[160px] w-full min-w-0 bg-background-base">
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={160}>
        <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F5A623" stopOpacity={0.34} />
              <stop offset="72%" stopColor="#F5A623" stopOpacity={0.08} />
              <stop offset="100%" stopColor="#F5A623" stopOpacity={0} />
            </linearGradient>
          </defs>

          {drawdownBands.map((band, index) => (
            <ReferenceArea
              key={`${band.start}-${band.end}-${index}`}
              x1={band.start}
              x2={band.end}
              fill="rgba(224,90,90,0.10)"
              fillOpacity={1}
              ifOverflow="extendDomain"
              strokeOpacity={0}
            />
          ))}

          <XAxis
            dataKey="index"
            axisLine={false}
            tickLine={false}
            minTickGap={24}
            tick={{ fill: C.text4, fontFamily: C.mono, fontSize: 10 }}
            tickFormatter={(value: number) => (value === 0 ? "S" : `${value}`)}
          />
          <YAxis
            width={56}
            axisLine={false}
            tickLine={false}
            tick={{ fill: C.text4, fontFamily: C.mono, fontSize: 9 }}
            tickFormatter={formatEquityTick}
            domain={[
              (dataMin: number) => Math.floor((dataMin - 150) / 100) * 100,
              (dataMax: number) => Math.ceil((dataMax + 150) / 100) * 100,
            ]}
          />
          <Tooltip
            cursor={{ stroke: "rgba(245,166,35,0.24)", strokeWidth: 1, strokeDasharray: "4 4" }}
            content={<EquityCurveTooltip />}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#F5A623"
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            activeDot={{ r: 4, fill: "#F5A623", stroke: "#0D0F14", strokeWidth: 2 }}
            dot={false}
            isAnimationActive
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RingMetric({ value, label, color = "#F5A623", size = 72 }: RingMetricProps) {
  const r = size / 2 - 6, stroke = 5;
  const circ = 2 * Math.PI * r;
  const filled = (Math.min(value, 100) / 100) * circ;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-border-faint" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke}
          className={tokenTextColorClasses[color] ?? "text-brand-amber"}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeDashoffset={circ / 4} strokeLinecap="round" />
        <text x={size/2} y={size/2 + 5} textAnchor="middle" fill="currentColor"
          className={tokenTextColorClasses[color] ?? "text-brand-amber"}
          style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: size * 0.22, fontWeight: 700 }}>
          {value}%
        </text>
      </svg>
      <Label color={color}>{label}</Label>
    </div>
  );
}