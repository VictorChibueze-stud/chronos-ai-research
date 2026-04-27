"use client";

import type { CSSProperties, ReactNode } from "react";

const mono: CSSProperties = {
  fontFamily: "'IBM Plex Mono', monospace",
  fontSize: 10,
  letterSpacing: "0.08em",
};

export function PulseDot({
  color,
  pulse = false,
  size = 6,
}: {
  color: string;
  pulse?: boolean;
  size?: number;
}) {
  return (
    <span
      className="inline-block shrink-0 rounded-full"
      style={{
        width: size,
        height: size,
        background: color,
        boxShadow: pulse ? `0 0 6px ${color}` : undefined,
        animation: pulse ? "live-pulse 1.4s ease-in-out infinite" : undefined,
      }}
      aria-hidden
    />
  );
}

export function LiveStatusRow({
  variant,
  showSecondaryBusyDot = false,
  label = "LIVE",
  rightSlot,
  className = "",
}: {
  variant: "live" | "idle" | "busy";
  showSecondaryBusyDot?: boolean;
  label?: string;
  rightSlot?: ReactNode;
  className?: string;
}) {
  const liveColor = variant === "idle" ? "var(--text-dim)" : "#4CAF7D";
  const primaryPulse = variant === "live";
  const secondaryVisible = variant !== "idle" && showSecondaryBusyDot;

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="flex items-center gap-1.5">
        <PulseDot color={liveColor} pulse={primaryPulse} />
        <span className="inline-flex min-h-[6px] min-w-[6px] shrink-0 items-center justify-center" aria-hidden>
          {secondaryVisible ? <PulseDot color="#F5A623" pulse size={6} /> : null}
        </span>
        <span style={{ ...mono, color: "var(--text-muted)" }}>{label}</span>
      </div>
      {rightSlot != null ? <div className="flex items-center gap-3">{rightSlot}</div> : null}
    </div>
  );
}

export function LiveStatusMeta({
  children,
  dim = false,
}: {
  children: ReactNode;
  dim?: boolean;
}) {
  return (
    <span style={{ ...mono, color: dim ? "#2A2D36" : "var(--text-muted)" }}>
      {children}
    </span>
  );
}
