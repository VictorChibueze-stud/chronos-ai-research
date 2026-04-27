"use client";

import type { CSSProperties } from "react";

const mono: CSSProperties = {
  fontFamily: "'IBM Plex Mono', monospace",
};

function Bar({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={`skeleton-bar ${className}`} style={style} aria-hidden />;
}

/** Full-page dim shell (universe, market initial load). */
export function FullBleedPageSkeleton({ label = "LOADING" }: { label?: string }) {
  return (
    <div
      className="flex h-full min-h-[240px] flex-col gap-4 bg-background-surface p-6"
      style={mono}
      aria-busy
      aria-label={label}
    >
      <Bar className="h-4 w-48 max-w-[50%]" />
      <Bar className="h-3 w-72 max-w-[70%]" />
      <div className="mt-4 grid flex-1 grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <Bar key={i} className="h-24 w-full" />
        ))}
      </div>
    </div>
  );
}

/** Scanner: KPI strip + filters + table rows. */
export function ScannerTableSkeleton() {
  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg-base)]" style={mono} aria-busy aria-label="Loading scanner">
      <div className="flex border-b border-[var(--border-default)] px-5 py-4" style={{ background: "var(--bg-elevated)" }}>
        <div className="flex flex-1 gap-0">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="flex flex-1 flex-col items-center border-r border-[var(--border-subtle)] py-2 last:border-r-0">
              <Bar className="mb-2 h-7 w-12" />
              <Bar className="h-2 w-20" />
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 border-b border-[var(--border-subtle)] px-5 py-2">
        <Bar className="h-6 w-24" />
        <Bar className="h-6 w-32" />
        <Bar className="h-6 w-40" />
      </div>
      <div className="flex flex-1 flex-col overflow-hidden px-5 py-2">
        <Bar className="mb-2 h-8 w-full" />
        {Array.from({ length: 8 }).map((_, i) => (
          <Bar key={i} className="mb-1 h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

/** Signals table / simple lists. */
export function SimpleListSkeleton({ rows = 10 }: { rows?: number }) {
  return (
    <div className="flex min-h-[220px] flex-col gap-2 bg-[var(--bg-base)] p-2" style={mono} aria-busy aria-label="Loading list">
      <Bar className="h-8 w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <Bar key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

/** Integrations-style stacked cards. */
export function IntegrationsPageSkeleton() {
  return (
    <div className="min-h-full bg-background-base p-4" style={mono} aria-busy aria-label="Loading integrations">
      <Bar className="mb-3 h-12 w-full max-w-2xl" />
      {Array.from({ length: 4 }).map((_, i) => (
        <Bar key={i} className="mb-3 h-36 w-full" />
      ))}
    </div>
  );
}
