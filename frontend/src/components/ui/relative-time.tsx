"use client";

import type { CSSProperties } from "react";

import { Tooltip } from "@/components/ui/tooltip";
import { formatExactUtc, formatRelativeTime } from "@/lib/format-display";

export function RelativeTimeWithTooltip({
  iso,
  fallback = "—",
  className,
  style,
}: {
  iso: string | null | undefined;
  fallback?: string;
  className?: string;
  style?: CSSProperties;
}) {
  const relative = iso ? formatRelativeTime(iso) : fallback;
  const exact = formatExactUtc(iso);

  if (!iso) {
    return (
      <span className={className} style={style}>
        {fallback}
      </span>
    );
  }

  return (
    <Tooltip content={exact}>
      <span className={className} style={{ cursor: "default", ...style }}>
        {relative}
      </span>
    </Tooltip>
  );
}
