"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type {
  PaperAccount,
  PaperPerformance,
  AccountTargets,
} from "@/lib/types";
import { Tooltip } from "@/components/ui/tooltip";

const MONO = "'IBM Plex Mono', monospace";
const BG = "#0D0F14";
const SURFACE = "#111318";
const BORDER = "#1E222D";

const MARKET_STATES = [
  "WAITING",
  "RETRACEMENT",
  "DEPTH_BUILDING",
  "CHOCH_ZONE_ACTIVE",
  "CHOCH_TESTED",
  "CANDIDATE_ACTIVE",
  "CANDIDATE_CHOCH_TESTED",
  "ENTRY_ZONE",
];

const TP_MODES = ["global_bos", "partial", "trailing"];
const TIMEFRAMES = ["15m", "30m", "1h", "4h"];

function SectionTitle({ children }: { children: string }) {
  return (
    <div
      style={{
        fontFamily: MONO,
        fontSize: 9,
        letterSpacing: "0.16em",
        color: "#787B86",
        textTransform: "uppercase",
        padding: "16px 20px 8px 20px",
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      {children}
    </div>
  );
}

function FieldLabel({
  children,
  tooltip,
}: {
  children: string;
  tooltip?: string;
}) {
  const label = (
    <div
      style={{
        fontFamily: MONO,
        fontSize: 8,
        letterSpacing: "0.1em",
        color: "#4A4D58",
        textTransform: "uppercase",
        marginBottom: 4,
        cursor: tooltip ? "help" : undefined,
      }}
    >
      {children}
    </div>
  );
  if (!tooltip) return label;
  return <Tooltip content={tooltip}>{label}</Tooltip>;
}

function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 0.01,
}: {
  value: number | null | undefined;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <input
      type="number"
      value={value ?? ""}
      min={min}
      max={max}
      step={step}
      onChange={(e) => {
        const parsed = parseFloat(e.target.value);
        if (Number.isFinite(parsed)) onChange(parsed);
      }}
      style={{
        width: "100%",
        background: "#0A0C10",
        border: `1px solid ${BORDER}`,
        color: "#D1D4DC",
        fontFamily: MONO,
        fontSize: 11,
        padding: "5px 8px",
        borderRadius: 2,
        outline: "none",
        boxSizing: "border-box",
      }}
    />
  );
}

function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: "100%",
        background: "#0A0C10",
        border: `1px solid ${BORDER}`,
        color: "#D1D4DC",
        fontFamily: MONO,
        fontSize: 10,
        padding: "5px 8px",
        borderRadius: 2,
        outline: "none",
        cursor: "pointer",
      }}
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o.toUpperCase()}
        </option>
      ))}
    </select>
  );
}

function ToggleSwitch({
  value,
  onChange,
  label,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
      }}
    >
      <span
        style={{
          fontFamily: MONO,
          fontSize: 8,
          color: "#4A4D58",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        style={{
          width: 32,
          height: 16,
          borderRadius: 8,
          background: value ? "#F5A623" : "#1E222D",
          border: "none",
          cursor: "pointer",
          position: "relative",
          flexShrink: 0,
          transition: "background 0.15s",
        }}
      >
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: "50%",
            background: "#0D0F14",
            position: "absolute",
            top: 2,
            left: value ? 18 : 2,
            transition: "left 0.15s",
          }}
        />
      </button>
    </div>
  );
}

type MetricRow = {
  key: keyof AccountTargets;
  perfKey: keyof PaperPerformance;
  label: string;
  tooltip: string;
  defaultTarget: number;
  higherIsBetter: boolean;
  format: (v: number) => string;
};

const METRIC_ROWS: MetricRow[] = [
  {
    key: "sharpe_target",
    perfKey: "sharpe_ratio",
    label: "SHARPE RATIO",
    tooltip: "Annualized risk-adjusted return. Target >1.5",
    defaultTarget: 1.5,
    higherIsBetter: true,
    format: (v) => v.toFixed(2),
  },
  {
    key: "sortino_target",
    perfKey: "sortino_ratio",
    label: "SORTINO RATIO",
    tooltip: "Like Sharpe but only penalizes downside. Target >2.0",
    defaultTarget: 2.0,
    higherIsBetter: true,
    format: (v) => v.toFixed(2),
  },
  {
    key: "calmar_target",
    perfKey: "calmar_ratio",
    label: "CALMAR RATIO",
    tooltip: "Annualized return / max drawdown. Target >1.0",
    defaultTarget: 1.0,
    higherIsBetter: true,
    format: (v) => v.toFixed(2),
  },
  {
    key: "profit_factor_target",
    perfKey: "profit_factor",
    label: "PROFIT FACTOR",
    tooltip: "Gross wins / gross losses. Target >1.5",
    defaultTarget: 1.5,
    higherIsBetter: true,
    format: (v) => v.toFixed(2),
  },
  {
    key: "win_rate_target",
    perfKey: "win_rate_pct",
    label: "WIN RATE %",
    tooltip: "Percentage of profitable trades. Target >45%",
    defaultTarget: 45,
    higherIsBetter: true,
    format: (v) => `${v.toFixed(1)}%`,
  },
  {
    key: "risk_reward_target",
    perfKey: "risk_reward_ratio",
    label: "AVG R:R",
    tooltip: "Average win / average loss. Target >1.5",
    defaultTarget: 1.5,
    higherIsBetter: true,
    format: (v) => v.toFixed(2),
  },
  {
    key: "max_dd_pct_target",
    perfKey: "max_drawdown_pct",
    label: "MAX DRAWDOWN %",
    tooltip: "Peak to trough loss. Lower is better",
    defaultTarget: 10,
    higherIsBetter: false,
    format: (v) => `${v.toFixed(1)}%`,
  },
];

export default function RiskPage() {
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [performances, setPerformances] = useState<
    Record<number, PaperPerformance>
  >({});
  const [drafts, setDrafts] = useState<
    Record<number, Partial<PaperAccount>>
  >({});
  const [targetDrafts, setTargetDrafts] = useState<
    Record<number, AccountTargets>
  >({});
  const [saving, setSaving] = useState<Record<number, boolean>>({});
  const [savingTargets, setSavingTargets] = useState<
    Record<number, boolean>
  >({});
  const [notices, setNotices] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const accts = await api.getPaperAccounts();
      setAccounts(accts);
      const draftsInit: Record<number, Partial<PaperAccount>> = {};
      for (const a of accts) {
        draftsInit[a.id] = {
          risk_per_trade_pct: a.risk_per_trade_pct,
          drawdown_limit_pct: a.drawdown_limit_pct,
          max_concurrent_positions: a.max_concurrent_positions,
          scale_by_score: a.scale_by_score,
          entry_timeframe: a.entry_timeframe,
          min_market_state: a.min_market_state,
          tp_mode: a.tp_mode,
          time_exit_days: a.time_exit_days,
        };
      }
      setDrafts(draftsInit);

      for (const a of accts) {
        api
          .getPaperPerformance(a.id)
          .then((p) =>
            setPerformances((prev) => ({ ...prev, [a.id]: p })),
          )
          .catch(() => {});

        api
          .getAccountTargets(a.id)
          .then((t) => {
            setTargetDrafts((prev) => ({ ...prev, [a.id]: { ...t } }));
          })
          .catch(() => {});
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const patchDraft = (
    id: number,
    field: keyof PaperAccount,
    value: unknown,
  ) => {
    setDrafts((prev) => ({
      ...prev,
      [id]: { ...prev[id], [field]: value },
    }));
  };

  const patchTargetDraft = (
    id: number,
    field: keyof AccountTargets,
    value: number,
  ) => {
    setTargetDrafts((prev) => ({
      ...prev,
      [id]: { ...prev[id], [field]: value },
    }));
  };

  const flashNotice = (key: string, text: string) => {
    setNotices((prev) => ({ ...prev, [key]: text }));
    setTimeout(() => {
      setNotices((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }, 3000);
  };

  const saveAccount = async (id: number) => {
    setSaving((prev) => ({ ...prev, [id]: true }));
    try {
      await api.updatePaperAccountSettings(id, drafts[id] ?? {});
      flashNotice(`a${id}`, "SAVED");
      await load();
    } catch {
      flashNotice(`a${id}`, "SAVE FAILED");
    } finally {
      setSaving((prev) => ({ ...prev, [id]: false }));
    }
  };

  const saveTargets = async (id: number) => {
    setSavingTargets((prev) => ({ ...prev, [id]: true }));
    try {
      await api.updateAccountTargets(id, targetDrafts[id] ?? {});
      flashNotice(`t${id}`, "TARGETS SAVED");
    } catch {
      flashNotice(`t${id}`, "SAVE FAILED");
    } finally {
      setSavingTargets((prev) => ({ ...prev, [id]: false }));
    }
  };

  const resumeAccount = async (id: number) => {
    await api.updatePaperAccountSettings(id, {
      is_paused_drawdown: false,
    });
    await load();
  };

  if (loading) {
    return (
      <div
        style={{
          background: BG,
          height: "100%",
          display: "flex",
          flexDirection: "column",
          gap: 12,
          padding: 20,
        }}
      >
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              height: 200,
              background: SURFACE,
              borderRadius: 2,
              animation: "card-pulse 1.5s ease-in-out infinite",
              animationDelay: `${i * 0.1}s`,
            }}
          />
        ))}
        <style>{`@keyframes card-pulse{0%,100%{opacity:0.3}50%{opacity:0.6}}`}</style>
      </div>
    );
  }

  return (
    <div
      style={{
        background: BG,
        height: "100%",
        overflowY: "auto",
        fontFamily: MONO,
      }}
    >
      {/* SECTION 1 — ACCOUNT RISK CONFIGURATION */}
      <SectionTitle>ACCOUNT RISK CONFIGURATION</SectionTitle>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: 12,
          padding: "12px 20px",
        }}
      >
        {accounts.map((account) => {
          const draft = drafts[account.id] ?? {};
          const perf = performances[account.id];
          const isPaused = account.is_paused_drawdown;
          const currentDD = perf?.max_drawdown_pct ?? 0;
          const ddNotice = notices[`a${account.id}`];

          return (
            <div
              key={account.id}
              style={{
                background: SURFACE,
                border: `1px solid ${
                  isPaused ? "#F5A62360" : BORDER
                }`,
                borderRadius: 2,
                padding: "14px 16px",
              }}
            >
              {/* Header */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 14,
                }}
              >
                <div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: "#D1D4DC",
                      marginBottom: 3,
                    }}
                  >
                    {account.name.toUpperCase()}
                  </div>
                  <div style={{ fontSize: 9, color: "#4A4D58" }}>
                    ${account.balance_usd.toLocaleString()}
                    {" · "}
                    {(account.universe ?? "")
                      .toUpperCase()
                      .replace("_", "-")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  {isPaused && (
                    <button
                      type="button"
                      onClick={() => resumeAccount(account.id)}
                      style={{
                        padding: "4px 10px",
                        background: "transparent",
                        border: "1px solid #F5A623",
                        color: "#F5A623",
                        fontFamily: MONO,
                        fontSize: 8,
                        letterSpacing: "0.1em",
                        cursor: "pointer",
                        borderRadius: 2,
                      }}
                    >
                      RESUME
                    </button>
                  )}
                  <div
                    style={{
                      padding: "3px 8px",
                      background: isPaused ? "#F5A62320" : "#00C85320",
                      border: `1px solid ${
                        isPaused ? "#F5A623" : "#00C853"
                      }`,
                      borderRadius: 2,
                      fontSize: 8,
                      color: isPaused ? "#F5A623" : "#00C853",
                      letterSpacing: "0.1em",
                    }}
                  >
                    {isPaused ? "● PAUSED" : "● ACTIVE"}
                  </div>
                </div>
              </div>

              {/* Drawdown indicator */}
              {perf && (
                <div
                  style={{
                    marginBottom: 14,
                    padding: "8px 10px",
                    background: "#0A0C10",
                    border: `1px solid ${BORDER}`,
                    borderRadius: 2,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 6,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 8,
                        color: "#4A4D58",
                        letterSpacing: "0.1em",
                      }}
                    >
                      CURRENT DRAWDOWN
                    </span>
                    <span
                      style={{
                        fontSize: 9,
                        color:
                          currentDD > account.drawdown_limit_pct * 0.8
                            ? "#EF5350"
                            : "#787B86",
                      }}
                    >
                      {currentDD.toFixed(1)}% /{" "}
                      {account.drawdown_limit_pct}%
                    </span>
                  </div>
                  <div
                    style={{
                      height: 3,
                      background: "#1E222D",
                      borderRadius: 2,
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        width: `${Math.min(
                          100,
                          (currentDD / Math.max(0.0001, account.drawdown_limit_pct)) * 100,
                        )}%`,
                        background:
                          currentDD > account.drawdown_limit_pct * 0.8
                            ? "#EF5350"
                            : "#F5A623",
                        borderRadius: 2,
                        transition: "width 0.3s",
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Field grid */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 10,
                }}
              >
                <div>
                  <FieldLabel tooltip="% of account balance risked per trade">
                    RISK PER TRADE %
                  </FieldLabel>
                  <NumberInput
                    value={draft.risk_per_trade_pct ?? null}
                    onChange={(v) =>
                      patchDraft(account.id, "risk_per_trade_pct", v)
                    }
                    min={0.01}
                    max={5}
                    step={0.01}
                  />
                </div>

                <div>
                  <FieldLabel tooltip="Auto-pause account when drawdown reaches this %">
                    DRAWDOWN LIMIT %
                  </FieldLabel>
                  <NumberInput
                    value={draft.drawdown_limit_pct ?? null}
                    onChange={(v) =>
                      patchDraft(account.id, "drawdown_limit_pct", v)
                    }
                    min={1}
                    max={50}
                    step={0.5}
                  />
                </div>

                <div>
                  <FieldLabel tooltip="Max open positions at any one time">
                    MAX POSITIONS
                  </FieldLabel>
                  <NumberInput
                    value={draft.max_concurrent_positions ?? null}
                    onChange={(v) =>
                      patchDraft(
                        account.id,
                        "max_concurrent_positions",
                        Math.round(v),
                      )
                    }
                    min={1}
                    max={20}
                    step={1}
                  />
                </div>

                <div>
                  <FieldLabel tooltip="Entry signal confirmed on this timeframe">
                    ENTRY TIMEFRAME
                  </FieldLabel>
                  <SelectInput
                    value={draft.entry_timeframe ?? "15m"}
                    onChange={(v) =>
                      patchDraft(account.id, "entry_timeframe", v)
                    }
                    options={TIMEFRAMES}
                  />
                </div>

                <div>
                  <FieldLabel tooltip="Minimum market state required before entry">
                    MIN STATE
                  </FieldLabel>
                  <SelectInput
                    value={draft.min_market_state ?? "CANDIDATE_ACTIVE"}
                    onChange={(v) =>
                      patchDraft(account.id, "min_market_state", v)
                    }
                    options={MARKET_STATES}
                  />
                </div>

                <div>
                  <FieldLabel tooltip="How take profit is determined">
                    TP MODE
                  </FieldLabel>
                  <SelectInput
                    value={draft.tp_mode ?? "global_bos"}
                    onChange={(v) =>
                      patchDraft(account.id, "tp_mode", v)
                    }
                    options={TP_MODES}
                  />
                </div>
              </div>

              <div style={{ marginTop: 10 }}>
                <ToggleSwitch
                  value={draft.scale_by_score ?? false}
                  onChange={(v) =>
                    patchDraft(account.id, "scale_by_score", v)
                  }
                  label="SCALE RISK BY SCORE"
                />
              </div>

              {/* Save row */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  marginTop: 14,
                }}
              >
                <button
                  type="button"
                  onClick={() => saveAccount(account.id)}
                  disabled={saving[account.id]}
                  style={{
                    padding: "6px 16px",
                    background: "#F5A623",
                    border: "none",
                    color: "#0D0F14",
                    fontFamily: MONO,
                    fontSize: 9,
                    letterSpacing: "0.1em",
                    cursor: saving[account.id] ? "not-allowed" : "pointer",
                    borderRadius: 2,
                    textTransform: "uppercase",
                  }}
                >
                  {saving[account.id] ? "SAVING..." : "SAVE"}
                </button>
                {ddNotice && (
                  <span
                    style={{
                      fontSize: 9,
                      color:
                        ddNotice === "SAVED" ? "#00C853" : "#EF5350",
                      letterSpacing: "0.08em",
                    }}
                  >
                    {ddNotice}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* SECTION 2 — PERFORMANCE TARGETS */}
      <SectionTitle>PERFORMANCE TARGETS</SectionTitle>

      <div style={{ padding: "12px 20px" }}>
        {accounts.map((account) => {
          const perf = performances[account.id];
          const tDraft = targetDrafts[account.id] ?? {};
          const targetNotice = notices[`t${account.id}`];

          return (
            <div
              key={account.id}
              style={{
                background: SURFACE,
                border: `1px solid ${BORDER}`,
                borderRadius: 2,
                padding: "14px 16px",
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#D1D4DC",
                  marginBottom: 12,
                  display: "flex",
                  justifyContent: "space-between",
                }}
              >
                {account.name.toUpperCase()}
                <span
                  style={{
                    fontSize: 8,
                    color: "#4A4D58",
                    fontWeight: 400,
                  }}
                >
                  {perf?.total_closed_trades ?? 0} CLOSED TRADES
                </span>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: 8,
                  marginBottom: 14,
                }}
              >
                {METRIC_ROWS.map((metric) => {
                  const rawCurrent = perf
                    ? (perf[metric.perfKey] as number | undefined)
                    : undefined;
                  const current =
                    rawCurrent === undefined ||
                    rawCurrent === null ||
                    !Number.isFinite(rawCurrent)
                      ? null
                      : rawCurrent;
                  const target =
                    tDraft[metric.key] ?? metric.defaultTarget;
                  const met =
                    current !== null
                      ? metric.higherIsBetter
                        ? current >= target
                        : current <= target
                      : null;

                  return (
                    <div
                      key={metric.key}
                      style={{
                        background: "#0A0C10",
                        border: `1px solid ${BORDER}`,
                        borderRadius: 2,
                        padding: "8px 10px",
                      }}
                    >
                      <Tooltip content={metric.tooltip}>
                        <div
                          style={{
                            fontSize: 7,
                            color: "#4A4D58",
                            letterSpacing: "0.1em",
                            marginBottom: 6,
                            cursor: "help",
                          }}
                        >
                          {metric.label}
                        </div>
                      </Tooltip>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          marginBottom: 6,
                        }}
                      >
                        <span
                          style={{
                            fontSize: 14,
                            fontWeight: 700,
                            color:
                              met === null
                                ? "#4A4D58"
                                : met
                                ? "#00C853"
                                : "#EF5350",
                          }}
                        >
                          {current !== null
                            ? metric.format(current)
                            : "—"}
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            color:
                              met === null
                                ? "#2A2E39"
                                : met
                                ? "#00C853"
                                : "#EF5350",
                          }}
                        >
                          {met === null ? "—" : met ? "✓" : "✗"}
                        </span>
                      </div>
                      <div>
                        <div
                          style={{
                            fontSize: 7,
                            color: "#2A2E39",
                            marginBottom: 2,
                          }}
                        >
                          TARGET
                        </div>
                        <input
                          type="number"
                          value={target}
                          step={0.1}
                          onChange={(e) => {
                            const parsed = parseFloat(e.target.value);
                            if (Number.isFinite(parsed)) {
                              patchTargetDraft(
                                account.id,
                                metric.key,
                                parsed,
                              );
                            }
                          }}
                          style={{
                            width: "100%",
                            background: "#0D0F14",
                            border: `1px solid ${BORDER}`,
                            color: "#787B86",
                            fontFamily: MONO,
                            fontSize: 9,
                            padding: "3px 6px",
                            borderRadius: 2,
                            outline: "none",
                            boxSizing: "border-box",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <button
                  type="button"
                  onClick={() => saveTargets(account.id)}
                  disabled={savingTargets[account.id]}
                  style={{
                    padding: "5px 14px",
                    background: "transparent",
                    border: `1px solid #F5A623`,
                    color: "#F5A623",
                    fontFamily: MONO,
                    fontSize: 8,
                    letterSpacing: "0.1em",
                    cursor: savingTargets[account.id]
                      ? "not-allowed"
                      : "pointer",
                    borderRadius: 2,
                  }}
                >
                  {savingTargets[account.id]
                    ? "SAVING..."
                    : "SAVE TARGETS"}
                </button>
                {targetNotice && (
                  <span
                    style={{
                      fontSize: 9,
                      color:
                        targetNotice === "TARGETS SAVED"
                          ? "#00C853"
                          : "#EF5350",
                      letterSpacing: "0.08em",
                    }}
                  >
                    {targetNotice}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* SECTION 3 — UNIVERSE DRAWDOWN STATUS */}
      <SectionTitle>UNIVERSE DRAWDOWN STATUS</SectionTitle>

      <div style={{ padding: "12px 20px 24px 20px" }}>
        <div
          style={{
            background: SURFACE,
            border: `1px solid ${BORDER}`,
            borderRadius: 2,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "1fr 1fr 80px 80px 80px 120px",
              padding: "8px 16px",
              borderBottom: `1px solid ${BORDER}`,
            }}
          >
            {[
              "UNIVERSE",
              "BALANCE",
              "DD %",
              "LIMIT",
              "STATUS",
              "PROGRESS",
            ].map((h) => (
              <div
                key={h}
                style={{
                  fontSize: 8,
                  color: "#4A4D58",
                  letterSpacing: "0.1em",
                }}
              >
                {h}
              </div>
            ))}
          </div>

          {accounts.map((account, i) => {
            const perf = performances[account.id];
            const dd = perf?.max_drawdown_pct ?? 0;
            const limit = account.drawdown_limit_pct;
            const ratio = limit > 0 ? dd / limit : 0;
            const statusColor = account.is_paused_drawdown
              ? "#F5A623"
              : ratio > 0.8
              ? "#EF5350"
              : "#00C853";
            const statusLabel = account.is_paused_drawdown
              ? "PAUSED"
              : ratio > 0.8
              ? "AT RISK"
              : "ACTIVE";

            return (
              <div
                key={account.id}
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "1fr 1fr 80px 80px 80px 120px",
                  padding: "12px 16px",
                  borderBottom:
                    i < accounts.length - 1
                      ? `1px solid ${BORDER}`
                      : "none",
                  alignItems: "center",
                }}
              >
                <div>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: "#D1D4DC",
                    }}
                  >
                    {account.name.toUpperCase()}
                  </div>
                  <div
                    style={{
                      fontSize: 8,
                      color: "#4A4D58",
                      marginTop: 2,
                    }}
                  >
                    {(account.universe ?? "")
                      .toUpperCase()
                      .replace("_", "-")}
                  </div>
                </div>
                <div style={{ fontSize: 11, color: "#D1D4DC" }}>
                  ${account.balance_usd.toLocaleString()}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: statusColor,
                    fontWeight: 700,
                  }}
                >
                  {dd.toFixed(1)}%
                </div>
                <div style={{ fontSize: 11, color: "#787B86" }}>
                  {limit}%
                </div>
                <div
                  style={{
                    fontSize: 9,
                    color: statusColor,
                    letterSpacing: "0.08em",
                  }}
                >
                  ● {statusLabel}
                </div>
                <div
                  style={{
                    height: 4,
                    background: "#1E222D",
                    borderRadius: 2,
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${Math.min(100, ratio * 100)}%`,
                      background: statusColor,
                      borderRadius: 2,
                      transition: "width 0.3s",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
