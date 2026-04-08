"use client";

import type { CSSProperties } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";

export type PanelEdgeCollapseVariant = "horizontal" | "vertical";

export interface PanelEdgeCollapseToggleProps {
  expanded: boolean;
  onClick: () => void;
  variant: PanelEdgeCollapseVariant;
  "aria-label": string;
  title: string;
  "aria-expanded"?: boolean;
  "aria-controls"?: string;
  className?: string;
  style?: CSSProperties;
}

export function PanelEdgeCollapseToggle({
  expanded,
  onClick,
  variant,
  "aria-label": ariaLabel,
  title,
  "aria-expanded": ariaExpanded,
  "aria-controls": ariaControls,
  className,
  style,
}: PanelEdgeCollapseToggleProps) {
  const icon =
    variant === "horizontal"
      ? expanded
        ? <ChevronUp className="h-3.5 w-3.5" strokeWidth={2} />
        : <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
      : expanded
        ? <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} />
        : <ChevronLeft className="h-3.5 w-3.5" strokeWidth={2} />;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      title={title}
      aria-expanded={ariaExpanded}
      aria-controls={ariaControls}
      className={`inline-flex h-6 w-6 shrink-0 items-center justify-center border border-[var(--border-strong)] bg-[var(--bg-elevated)] text-[var(--text-secondary)] transition-colors hover:border-[var(--amber)] hover:text-[var(--amber)] ${className ?? ""}`}
      style={style}
    >
      {icon}
    </button>
  );
}
