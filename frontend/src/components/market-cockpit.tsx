"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

import type { AnalysisResponse, CandleBar, ChartStructuralLevel, Setup } from "@/lib/types";

const CandleChart = dynamic(() => import("@/components/candle-chart"), { ssr: false });

interface MarketCockpitProps {
  setup: Setup;
  candles: CandleBar[];
  analysisData?: AnalysisResponse;
  activeTimeframe: string;
  onTimeframeChange: (tf: string) => void;
  onNavigate: (symbol: string) => void;
  candlesLoading?: boolean;
  isSwitchingTimeframe?: boolean;
}

const TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d"] as const;

function formatPrice(value: number): string {
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (Math.abs(value) >= 10) {
    return value.toFixed(2);
  }
  return value.toFixed(4);
}

function trendColor(trend: Setup["trend"]): string {
  if (trend === "up") return "#00C853";
  if (trend === "down") return "#FF1744";
  return "#787B86";
}

function phaseTone(phase: Setup["current_phase"]): string {
  return phase === "retracement" ? "#F5A623" : "#787B86";
}

function structureBadgeLabel(setup: Setup): string {
  if (!setup.active_bos) {
    return "NO BREAK";
  }

  if (setup.active_bos.break_type === "true") return "TRUE BREAK";
  if (setup.active_bos.break_type === "false") return "FALSE BREAK";
  if (setup.active_bos.break_type === "broken") return "BROKEN";
  return "PENDING";
}

function alignmentTone(value: string): { bg: string; border: string; text: string } {
  const normalized = value.toLowerCase();
  if (normalized === "up") {
    return { bg: "rgba(0,200,83,0.10)", border: "rgba(0,200,83,0.24)", text: "#00C853" };
  }
  if (normalized === "down") {
    return { bg: "rgba(255,23,68,0.10)", border: "rgba(255,23,68,0.24)", text: "#FF1744" };
  }
  return { bg: "#2A2E39", border: "#363A45", text: "#787B86" };
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function ValueText({ children, color = "#D1D4DC" }: { children: React.ReactNode; color?: string }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 700, color, fontFamily: '"IBM Plex Mono", monospace' }}>{children}</div>
  );
}

function renderEmaStatus(setup: Setup) {
  if (setup.ema_signal === "LONG") {
    return {
      color: "#4CAF7D",
      text: "EMA 9 × EMA 21 — LONG SIGNAL",
    };
  }

  if (setup.ema_signal === "SHORT") {
    return {
      color: "#E05A5A",
      text: "EMA 9 × EMA 21 — SHORT SIGNAL",
    };
  }

  return null;
}

export function MarketCockpit({
  setup,
  candles,
  analysisData,
  activeTimeframe,
  onTimeframeChange,
  onNavigate,
  candlesLoading: _candlesLoading = false,
  isSwitchingTimeframe = false,
}: MarketCockpitProps) {
  const [marketInput, setMarketInput] = useState(String(setup.symbol || ""));
  const [showDrawings, setShowDrawings] = useState(true);
  const [showInternalStructure, setShowInternalStructure] = useState(false);

  useEffect(() => {
    setMarketInput(String(setup.symbol || ""));
  }, [setup.symbol]);

  const structuralState = analysisData?.structural_state ?? setup.structural_state_json;
  const structuralLevels = structuralState?.levels ?? [];
  const activeTrend = String(analysisData?.global_trend ?? setup.trend ?? "up").toLowerCase();
  const isDownTrend = activeTrend === "down";
  const zoneMapColor = isDownTrend ? "#EF5350" : "#26A69A";
  const zoneMapLabel = isDownTrend ? "DOWN ↓" : "UP ↑";
  const depthValue = analysisData?.max_depth_reached ?? setup.pullback_depth;
  const mitigationValue = analysisData?.total_mitigation_count ?? setup.total_mitigation_count;
  const waitingForText = analysisData?.waiting_for ?? setup.waiting_for;

  const chartStructuralLevels: ChartStructuralLevel[] = structuralLevels.map((level) => {
    const depthColors = ["#2962FF", "#26A69A", "#F5A623"];
    const color = depthColors[(Math.max(1, level.depth) - 1) % 3];
    const startIdx = level.first_impulse_global_start;
    const endIdx = level.first_impulse_global_end;
    const startCandle = typeof startIdx === "number" ? candles[startIdx] : undefined;
    const endCandle = typeof endIdx === "number" ? candles[endIdx] : undefined;

    const startPrice = level.first_impulse?.start_price;
    const endPrice = level.first_impulse?.end_price;

    return {
      depth: level.depth,
      color,
      chochZone:
        typeof level.choch_zone?.lower_boundary === "number" && typeof level.choch_zone?.upper_boundary === "number"
          ? {
            lower: level.choch_zone.lower_boundary,
            upper: level.choch_zone.upper_boundary,
          }
          : null,
      bosPrice: level.structural_level?.price ?? null,
      bosColor: isDownTrend ? "#EF5350" : "#26A69A",
      impulseStart:
        startCandle && typeof startPrice === "number"
          ? {
            price: startPrice,
            time: Math.floor(new Date(startCandle.time).getTime() / 1000),
          }
          : null,
      impulseEnd:
        endCandle && typeof endPrice === "number"
          ? {
            price: endPrice,
            time: Math.floor(new Date(endCandle.time).getTime() / 1000),
          }
          : null,
    };
  });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        height: "100%",
        padding: 10,
        background: "#0D0F14",
        color: "#D1D4DC",
        fontFamily: '"IBM Plex Mono", monospace',
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid #1C1E24", background: "#111318", padding: "6px 8px" }}>
        <span style={{ fontSize: 9, color: "#787B86", letterSpacing: "0.1em", textTransform: "uppercase" }}>Market</span>
        <input
          type="text"
          placeholder="SEARCH MARKET..."
          value={marketInput}
          onChange={(e) => setMarketInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") {
              return;
            }
            onNavigate(marketInput);
          }}
          style={{
            width: 180,
            fontSize: 10,
            background: "#0B0D11",
            border: "1px solid #1E222D",
            color: "#D1D4DC",
            padding: "4px 10px",
            fontFamily: '"IBM Plex Mono", monospace',
            outline: "none",
          }}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(360px, 2fr)", gap: 16, minHeight: 0, flex: 1 }}>
      <section style={{ display: "flex", minHeight: 0, flexDirection: "column", border: "1px solid #1C1E24", background: "#111318" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid #1C1E24", padding: "8px 12px" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.04em", color: "#D1D4DC" }}>{setup.symbol}</div>
            <div style={{ marginTop: 4, fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>
              {setup.category} · {activeTimeframe} · {setup.broker}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 }}>
              <div style={{ fontSize: 10, letterSpacing: "0.12em", color: "#787B86", textTransform: "uppercase" }}>Zone Map</div>
              <button
                type="button"
                onClick={() => setShowDrawings((prev) => !prev)}
                style={{
                  fontSize: 8,
                  letterSpacing: "0.1em",
                  padding: "2px 8px",
                  border: "1px solid #1E222D",
                  background: "transparent",
                  color: showDrawings ? "#434651" : "#2A2E39",
                  cursor: "pointer",
                  textTransform: "uppercase",
                  fontFamily: '"IBM Plex Mono", monospace',
                }}
              >
                {showDrawings ? "DRAWINGS ON" : "DRAWINGS OFF"}
              </button>
            </div>
            <div style={{ marginTop: 4, fontSize: 13, fontWeight: 700, color: zoneMapColor }}>
              {zoneMapLabel}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", padding: "6px 16px", borderBottom: "1px solid #1C1E24", gap: 4 }}>
          {TIMEFRAMES.map((tf) => {
            const isActive = activeTimeframe === tf;
            return (
              <button
                key={tf}
                type="button"
                style={{
                  padding: "3px 8px",
                  fontSize: 10,
                  fontFamily: '"IBM Plex Mono", monospace',
                  letterSpacing: "0.06em",
                  background: isActive ? "#F5A623" : "transparent",
                  color: isActive ? "#0D0F14" : "#4A4D58",
                  border: isActive ? "1px solid #F5A623" : "1px solid #1C1E24",
                  borderRadius: 2,
                  cursor: "pointer",
                }}
                onClick={() => onTimeframeChange(tf)}
              >
                {tf.toUpperCase()}
              </button>
            );
          })}
        </div>

        <div style={{ flex: 1, minHeight: 0, padding: 16, position: "relative" }}>
          {isSwitchingTimeframe && (
            <div
              style={{
                position: "absolute",
                top: 16,
                left: 16,
                right: 16,
                height: 2,
                overflow: "hidden",
                pointerEvents: "none",
                zIndex: 8,
              }}
            >
              <div
                style={{
                  width: "40%",
                  height: "100%",
                  background: "linear-gradient(90deg, transparent, #F5A623, transparent)",
                  animation: "tf-loading 0.8s ease-in-out infinite",
                }}
              />
            </div>
          )}
          <CandleChart
            candles={candles}
            candleTimestamps={candles.map((c) => ({ time: c.time }))}
            structuralLevels={chartStructuralLevels}
            showDrawings={showDrawings}
          />
        </div>
      </section>

      <aside style={{ display: "flex", minHeight: 0, flexDirection: "column", gap: 8, overflowY: "auto" }}>
        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Trend Summary</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Trend</div>
              <ValueText color={trendColor(setup.trend)}>{setup.trend.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Phase</div>
              <ValueText color={phaseTone(setup.current_phase)}>{setup.current_phase.toUpperCase()}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>FSM State</div>
              <ValueText>{setup.fsm_state}</ValueText>
            </div>
            <div>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Score</div>
              <ValueText>{setup.trend_score}</ValueText>
            </div>
          </div>
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Retracement Analysis</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Depth</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>{depthValue}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Mitigations</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>{mitigationValue}</span>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "#787B86", textTransform: "uppercase" }}>Waiting For</div>
              <div style={{ marginTop: 8, fontSize: 12, lineHeight: 1.6, color: "#D1D4DC" }}>{waitingForText}</div>
            </div>
          </div>
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>Depth Levels</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {structuralLevels.map((level, index) => {
              const levelLower = level.choch_zone?.lower_boundary;
              const levelUpper = level.choch_zone?.upper_boundary;
              const activeLower = setup.active_choch_zone?.lower_boundary;
              const activeUpper = setup.active_choch_zone?.upper_boundary;
              const isActiveLevel =
                typeof levelLower === "number" &&
                typeof levelUpper === "number" &&
                levelLower === activeLower &&
                levelUpper === activeUpper;

              const depthColor = level.depth === 1
                ? "#3A6BFF"
                : level.depth === 2
                  ? "#4CAF7D"
                  : level.depth === 3
                    ? "#9B59B6"
                    : "#D1D4DC";

              return (
                <div
                  key={`depth-level-${level.depth}-${index}`}
                  style={{
                    border: "1px solid #1C1E24",
                    borderLeft: isActiveLevel ? "3px solid #F5A623" : "1px solid #1C1E24",
                    background: "#131722",
                    padding: 12,
                    boxShadow: isActiveLevel ? "0 0 12px rgba(245,166,35,0.25)" : "none",
                    animation: isActiveLevel ? "border-pulse-amber 3s ease-in-out infinite" : undefined,
                    position: "relative",
                    overflow: "hidden",
                  }}
                >
                  {isActiveLevel && (
                    <div
                      style={{
                        position: "absolute",
                        top: 8,
                        right: 8,
                        fontSize: 8,
                        color: "#F5A623",
                        letterSpacing: "0.14em",
                      }}
                    >
                      ACTIVE
                    </div>
                  )}
                  {!isActiveLevel && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: 0,
                        bottom: 0,
                        width: 2,
                        background: depthColor,
                        opacity: 0.3,
                      }}
                    />
                  )}
                  <div style={{ fontSize: 11, fontWeight: 700, color: depthColor, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                    DEPTH {level.depth}
                  </div>

                  <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>CHoCH Zone</div>
                      <div style={{ marginTop: 4, fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>
                        {typeof levelLower === "number" && typeof levelUpper === "number"
                          ? `${formatPrice(levelLower)} - ${formatPrice(levelUpper)}`
                          : "N/A"}
                      </div>
                    </div>

                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>BOS Structural Level</div>
                      <div style={{ marginTop: 4, fontSize: 12, fontWeight: 700, color: "#D1D4DC" }}>
                        {typeof level.structural_level?.price === "number" ? formatPrice(level.structural_level.price) : "N/A"}
                      </div>
                    </div>

                    <div>
                      <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Termination</div>
                      <div style={{ marginTop: 4, fontSize: 11, color: "#787B86" }}>
                        {level.termination_reason || "N/A"}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
            {structuralLevels.length === 0 && (
              <div
                style={{
                  border: "1px solid #1C1E24",
                  background: "#131722",
                  padding: 20,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                }}
              >
                <div style={{ fontSize: 20, color: "#2A2E39", lineHeight: 1 }}>-</div>
                <div style={{ fontSize: 9, color: "#2A2E39", letterSpacing: "0.14em" }}>NO STRUCTURAL DATA</div>
                <div style={{ fontSize: 9, color: "#1E222D" }}>MARKET IN IMPULSE PHASE</div>
              </div>
            )}
            <div style={{ border: "1px solid #1C1E24", background: "#131722", padding: 12 }}>
              <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>Break Type</div>
              <div style={{ marginTop: 8 }}>
                <span style={{ background: "#2A2E39", color: "#D1D4DC", border: "1px solid #363A45", padding: "4px 8px", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                  {structureBadgeLabel(setup)}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <button
            type="button"
            onClick={() => setShowInternalStructure((prev) => !prev)}
            style={{
              width: "100%",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              background: "transparent",
              border: "none",
              padding: 0,
              cursor: "pointer",
              color: "#F5A623",
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              fontFamily: '"IBM Plex Mono", monospace',
            }}
          >
            <span>{showInternalStructure ? "▼ INTERNAL STRUCTURE" : "▶ INTERNAL STRUCTURE"}</span>
          </button>

          {showInternalStructure && (
            <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
              {structuralLevels.length === 0 && (
                <div style={{ fontSize: 10, color: "#434651", fontFamily: '"IBM Plex Mono", monospace' }}>—</div>
              )}

              {structuralLevels.map((level, index) => {
                const depthColor = level.depth === 1 ? "#2962FF" : level.depth === 2 ? "#26A69A" : "#F5A623";
                const chochText =
                  typeof level.choch_zone?.lower_boundary === "number" && typeof level.choch_zone?.upper_boundary === "number"
                    ? `${level.choch_zone.lower_boundary.toFixed(4)} - ${level.choch_zone.upper_boundary.toFixed(4)}`
                    : "—";
                const bosText = typeof level.structural_level?.price === "number" ? level.structural_level.price.toFixed(4) : "—";
                const statusColor = level.choch_mitigated ? "#26A69A" : "#F5A623";
                const statusText = level.choch_mitigated ? "MITIGATED" : "WATCHING";
                const terminationText = level.termination_reason || "—";
                const tfText = level.internal_tf_used || "—";

                const rowLabelStyle = {
                  fontSize: 8,
                  color: "#434651",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase" as const,
                };
                const rowValueStyle = {
                  fontSize: 10,
                  color: "#D1D4DC",
                  fontFamily: '"IBM Plex Mono", monospace',
                };

                return (
                  <div
                    key={`internal-structure-${level.depth}-${index}`}
                    style={{
                      borderTop: index > 0 ? "1px solid #1E222D" : "none",
                      paddingTop: index > 0 ? 10 : 0,
                      display: "grid",
                      gap: 8,
                    }}
                  >
                    <div style={{ fontSize: 11, fontWeight: 700, color: depthColor, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                      DEPTH {level.depth}
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={rowLabelStyle}>Timeframe Used</span>
                      <span style={rowValueStyle}>{tfText}</span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={rowLabelStyle}>CHOCH Zone</span>
                      <span style={rowValueStyle}>{chochText}</span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={rowLabelStyle}>BOS Level</span>
                      <span style={rowValueStyle}>{bosText}</span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={rowLabelStyle}>Status</span>
                      <span style={{ ...rowValueStyle, color: statusColor }}>{statusText}</span>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <span style={rowLabelStyle}>Termination</span>
                      <span style={{ fontSize: 8, color: "#434651", fontFamily: '"IBM Plex Mono", monospace' }}>{terminationText}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>MTF Alignment</SectionLabel>
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {Object.entries(setup.mtf_alignment).map(([timeframe, direction]) => {
              const tone = alignmentTone(direction);
              return (
                <div key={timeframe} style={{ border: `1px solid ${tone.border}`, background: tone.bg, padding: 10 }}>
                  <div style={{ fontSize: 9, letterSpacing: "0.1em", color: "#787B86", textTransform: "uppercase" }}>{timeframe}</div>
                  <div style={{ marginTop: 6, fontSize: 12, fontWeight: 700, color: tone.text, textTransform: "uppercase" }}>{direction}</div>
                </div>
              );
            })}
          </div>
        </section>

        <section style={{ border: "1px solid #1C1E24", background: "#111318", padding: 12 }}>
          <SectionLabel>EMA Status</SectionLabel>
          {renderEmaStatus(setup) ? (
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: renderEmaStatus(setup)?.color,
                  animation: "live-pulse 1.5s ease-in-out infinite",
                  flexShrink: 0,
                }}
              />
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: renderEmaStatus(setup)?.color,
                }}
              >
                {renderEmaStatus(setup)?.text}
              </div>
            </div>
          ) : (
            <div style={{ marginTop: 12, display: "grid", gap: 6 }}>
              <div style={{ fontSize: 11, color: "#4A4D58" }}>Watching for EMA 9 / EMA 21 crossover</div>
              <div style={{ fontSize: 10, color: "#3A3D48" }}>Conditions: depth ≥ 1, active CHoCH zone</div>
            </div>
          )}
        </section>
      </aside>
      </div>
    </div>
  );
}