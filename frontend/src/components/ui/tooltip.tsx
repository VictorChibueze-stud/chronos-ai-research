"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import type { CSSProperties } from "react";

interface TooltipProviderProps {
  children: ReactNode;
}

interface TooltipProps {
  content: string;
  children: ReactNode;
  /** Wider, wrapping bubble for long text (e.g. signal waiting_for). */
  multiline?: boolean;
  bubbleStyle?: CSSProperties;
}

export function TooltipProvider({ children }: TooltipProviderProps) {
  return <>{children}</>;
}

export function Tooltip({ content, children, multiline, bubbleStyle }: TooltipProps) {
  const [visible, setVisible] = useState(false);

  return (
    <span
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      <span
        style={{
          position: "absolute",
          left: "50%",
          bottom: "calc(100% + 6px)",
          transform: "translateX(-50%)",
          padding: "4px 8px",
          border: "1px solid #363A45",
          background: "#1E222D",
          color: "#D1D4DC",
          fontSize: 9,
          letterSpacing: "0.04em",
          whiteSpace: multiline ? "pre-wrap" : "nowrap",
          maxWidth: multiline ? 300 : undefined,
          wordBreak: multiline ? "break-word" : undefined,
          pointerEvents: "none",
          opacity: visible ? 1 : 0,
          transition: "opacity 120ms ease",
          zIndex: 40,
          ...bubbleStyle,
        }}
      >
        {content}
      </span>
    </span>
  );
}
