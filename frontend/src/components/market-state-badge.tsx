"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { MarketStateHistoryItem } from "@/lib/types";
import { MarketContextPanelCompact } from "@/components/market-context-panel-compact";

interface StateConfig {
  color: string;
  label: string;
  description: string;
  pulse: boolean;
}

const STATE_CONFIG: Record<string, StateConfig> = {
  WAITING:               { color: "var(--state-waiting)",   label: "WAITING",      description: "Global trend identified, no retracement yet",           pulse: false },
  RETRACEMENT:           { color: "var(--state-entry)",     label: "RETRACEM.",    description: "Prime retracement in progress",                          pulse: true  },
  DEPTH_BUILDING:        { color: "var(--state-depth)",     label: "DEPTH",        description: "Walker finding depth levels in retracement",             pulse: true  },
  CHOCH_ZONE_ACTIVE:     { color: "var(--state-choch)",     label: "CHOCH ZONE",   description: "CHoCH zone identified — waiting for price",              pulse: false },
  CHOCH_TESTED:          { color: "var(--state-choch)",     label: "CHOCH TEST",   description: "Price has entered CHoCH zone",                           pulse: true  },
  CANDIDATE_ACTIVE:      { color: "var(--state-candidate)", label: "CANDIDATE",    description: "Candidate impulse forming",                              pulse: true  },
  CANDIDATE_CHOCH_TESTED:{ color: "var(--state-choch)",     label: "CAND CHOCH",   description: "Candidate internal CHoCH has been tested",               pulse: true  },
  ENTRY_ZONE:            { color: "var(--state-entry)",     label: "ENTRY ZONE",   description: "All conditions met — entry zone active",                 pulse: true  },
  CANDIDATE_CONFIRMED:   { color: "var(--state-confirmed)", label: "CONFIRMED",    description: "Candidate BOS broken — trend continuation confirmed",    pulse: true  },
  STRUCTURE_BROKEN:      { color: "var(--bear)",            label: "BROKEN",       description: "Global BOS broken — structural shift",                   pulse: false },
};

const DEFAULT_CONFIG: StateConfig = {
  color: "var(--state-waiting)",
  label: "UNKNOWN",
  description: "Unknown state",
  pulse: false,
};

function getConfig(state: string): StateConfig {
  return STATE_CONFIG[state] ?? DEFAULT_CONFIG;
}

// ── MarketStateBadge ──────────────────────────────────────────────────────

export interface MarketStateBadgeProps {
  state: string;
  onClick?: () => void;
  large?: boolean;
}

export function MarketStateBadge({ state, onClick, large }: MarketStateBadgeProps) {
  const cfg = getConfig(state);
  const [hover, setHover] = useState(false);

  const fontSize = large ? 12 : 9;
  const padding = large ? "4px 10px" : "2px 7px";
  const dotSize = large ? 7 : 5;

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: cfg.pulse ? (large ? 6 : 4) : 0,
        padding,
        background: "transparent",
        border: `1px solid ${cfg.color}`,
        borderRadius: 2,
        cursor: onClick ? "pointer" : "default",
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize,
        fontWeight: 600,
        letterSpacing: "0.1em",
        color: cfg.color,
        transition: "border-color 0.15s, box-shadow 0.15s",
        boxShadow: hover && onClick ? `0 0 0 1px ${cfg.color}66` : "none",
        outline: "none",
        flexShrink: 0,
      }}
    >
      {cfg.pulse && (
        <span
          style={{
            width: dotSize,
            height: dotSize,
            borderRadius: "50%",
            background: cfg.color,
            flexShrink: 0,
            animation: "live-pulse 2s ease-in-out infinite",
          }}
        />
      )}
      {cfg.label}
    </button>
  );
}

// ── Pipeline row ──────────────────────────────────────────────────────────

interface PipelineStage {
  key: string;
  label: string;
  status: "complete" | "active" | "pending";
  detail?: string;
}

const PIPELINE_STAGES = [
  "WAITING",
  "RETRACEMENT",
  "DEPTH_BUILDING",
  "CHOCH_ZONE_ACTIVE",
  "CHOCH_TESTED",
  "CANDIDATE_ACTIVE",
  "CANDIDATE_CHOCH_TESTED",
  "ENTRY_ZONE",
];

function buildPipelineStages(currentState: string): PipelineStage[] {
  const activeIdx = PIPELINE_STAGES.indexOf(currentState);
  return PIPELINE_STAGES.map((s, i) => ({
    key: s,
    label: getConfig(s).label,
    status:
      currentState === "STRUCTURE_BROKEN"
        ? "pending"
        : i < activeIdx
          ? "complete"
          : i === activeIdx
            ? "active"
            : "pending",
    detail: getConfig(s).description,
  }));
}

// ── MarketStateDrawer ─────────────────────────────────────────────────────

export interface MarketStateDrawerProps {
  symbol: string;
  state: string;
  isOpen: boolean;
  onClose: () => void;
}

export function MarketStateDrawer({ symbol, state, isOpen, onClose }: MarketStateDrawerProps) {
  const [history, setHistory] = useState<MarketStateHistoryItem[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen || !symbol) return;
    setHistory(null);
    setHistoryLoading(true);
    api
      .getSetupStateHistory(symbol)
      .then((data) => setHistory(data))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [isOpen, symbol]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  const cfg = getConfig(state);
  const pipeline = buildPipelineStages(state);

  return (
    <>
      {/* Overlay */}
      <div
        role="presentation"
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 900,
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? "auto" : "none",
          transition: "opacity 250ms ease",
        }}
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 420,
          background: "var(--bg-base)",
          borderLeft: "1px solid var(--border-default)",
          zIndex: 901,
          transform: isOpen ? "translateX(0)" : "translateX(420px)",
          transition: "transform 250ms ease",
          display: "flex",
          flexDirection: "column",
          overflowY: "auto",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-default)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexShrink: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 16,
                fontWeight: 700,
                color: "#F5A623",
                letterSpacing: "0.04em",
              }}
            >
              {symbol || "—"}
            </span>
            <MarketStateBadge state={state} large />
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "none",
              border: "none",
              color: "var(--text-dim)",
              cursor: "pointer",
              fontSize: 18,
              lineHeight: 1,
              padding: "2px 4px",
              borderRadius: 2,
            }}
          >
            ✕
          </button>
        </div>

        {/* Strategy Pipeline */}
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--bg-elevated)" }}>
          <div
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 8,
              letterSpacing: "0.14em",
              color: "var(--text-dim)",
              textTransform: "uppercase",
              marginBottom: 14,
            }}
          >
            Strategy Pipeline
          </div>
          <div style={{ position: "relative", paddingLeft: 24 }}>
            {/* vertical line */}
            <div
              style={{
                position: "absolute",
                left: 7,
                top: 8,
                bottom: 8,
                width: 1,
                background: "var(--border-default)",
              }}
            />
            {pipeline.map((stage, i) => {
              const stageCfg = getConfig(stage.key);
              const dotColor =
                stage.status === "complete"
                  ? stageCfg.color
                  : stage.status === "active"
                    ? stageCfg.color
                    : "var(--border-default)";
              const textColor =
                stage.status === "complete"
                  ? "var(--text-dim)"
                  : stage.status === "active"
                    ? stageCfg.color
                    : "var(--border-default)";
              return (
                <div
                  key={stage.key}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    marginBottom: i < pipeline.length - 1 ? 10 : 0,
                    position: "relative",
                  }}
                >
                  {/* dot */}
                  <div
                    style={{
                      position: "absolute",
                      left: -24,
                      top: 4,
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: stage.status === "complete" ? dotColor : "none",
                      border: `1.5px solid ${dotColor}`,
                      flexShrink: 0,
                    }}
                  />
                  <div>
                    <div
                      style={{
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 10,
                        fontWeight: stage.status === "active" ? 700 : 400,
                        color: textColor,
                        letterSpacing: "0.06em",
                      }}
                    >
                      {stage.label}
                    </div>
                    {stage.status !== "pending" && (
                      <div
                        style={{
                          fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 8,
                          color: "var(--text-dim)",
                          marginTop: 1,
                          letterSpacing: "0.04em",
                        }}
                      >
                        {stage.detail}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* State description */}
        <div
          style={{
            padding: "12px 20px",
            borderBottom: "1px solid var(--bg-elevated)",
          }}
        >
          <div
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 9,
              color: cfg.color,
              letterSpacing: "0.06em",
              lineHeight: 1.5,
            }}
          >
            {cfg.description}
          </div>
        </div>

        {/* State History */}
        <div style={{ padding: "16px 20px", flex: 1 }}>
          <div
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 8,
              letterSpacing: "0.14em",
              color: "var(--text-dim)",
              textTransform: "uppercase",
              marginBottom: 14,
            }}
          >
            State History
          </div>

          {historyLoading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[...Array(5)].map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: 32,
                    background: "var(--bg-elevated)",
                    borderRadius: 2,
                    animation: "live-pulse 1.5s ease-in-out infinite",
                  }}
                />
              ))}
            </div>
          )}

          {!historyLoading && history !== null && history.length === 0 && (
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 9,
                color: "var(--text-dim)",
                letterSpacing: "0.06em",
              }}
            >
              No transitions recorded yet.
            </div>
          )}

          {!historyLoading && history !== null && history.length > 0 && (
            <div style={{ position: "relative", paddingLeft: 20 }}>
              {/* vertical timeline line */}
              <div
                style={{
                  position: "absolute",
                  left: 5,
                  top: 8,
                  bottom: 8,
                  width: 1,
                  background: "var(--border-default)",
                }}
              />
              {history.map((item, i) => {
                const itemCfg = getConfig(item.state);
                return (
                  <div
                    key={item.id}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      marginBottom: i < history.length - 1 ? 12 : 0,
                      position: "relative",
                    }}
                  >
                    {/* dot */}
                    <div
                      style={{
                        position: "absolute",
                        left: -20,
                        top: 5,
                        width: 7,
                        height: 7,
                        borderRadius: "50%",
                        background: itemCfg.color,
                        flexShrink: 0,
                      }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <MarketStateBadge state={item.state} />
                        {item.previous_state && (
                          <span
                            style={{
                              fontFamily: "'IBM Plex Mono', monospace",
                              fontSize: 8,
                              color: "var(--text-muted)",
                              letterSpacing: "0.04em",
                            }}
                          >
                            ← {getConfig(item.previous_state).label}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          fontFamily: "'IBM Plex Mono', monospace",
                          fontSize: 8,
                          color: "var(--text-dim)",
                          marginTop: 3,
                          letterSpacing: "0.04em",
                        }}
                      >
                        {new Date(item.transitioned_at).toUTCString().replace("GMT", "UTC")}
                        {item.score != null && (
                          <span style={{ marginLeft: 8 }}>
                            score: {item.score.toFixed(1)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Fundamentals context */}
        {isOpen && symbol && (
          <div style={{ padding: "0 20px 16px" }}>
            <MarketContextPanelCompact symbol={symbol} />
          </div>
        )}

        {/* Footer */}
        <div
          style={{
            padding: "12px 20px",
            borderTop: "1px solid var(--bg-elevated)",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
          }}
        >
          <a
            href={`/market?symbol=${symbol}`}
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 9,
              color: "#F5A623",
              letterSpacing: "0.08em",
              textDecoration: "none",
            }}
          >
            View market →
          </a>
        </div>
      </div>
    </>
  );
}

