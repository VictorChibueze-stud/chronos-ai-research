"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, X } from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import type { PaperAccount, PaperPerformance, PaperTrade } from "@/lib/types";

const BG = "#0D0F14";
const BORDER = "#1E222D";
const MONO = '"IBM Plex Mono", monospace';

function formatUsd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function formatPriceCompact(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (Math.abs(n) >= 10) return n.toFixed(2);
  return n.toFixed(4);
}

function tradeDuration(openAt: string, closeAt: string | null): string {
  const start = new Date(openAt).getTime();
  const end = closeAt ? new Date(closeAt).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
  const ms = Math.max(0, end - start);
  const days = Math.floor(ms / 86400000);
  const hours = Math.floor((ms % 86400000) / 3600000);
  if (!closeAt) return `open ${days}d`;
  return `${days}d ${hours}h`;
}

type StatusFilter = "ALL" | PaperTrade["status"];

function statusUi(status: PaperTrade["status"]): {
  bar: string;
  pill: string;
  label: string;
} {
  switch (status) {
    case "closed_tp":
      return { bar: "#00C853", pill: "#00C853", label: "TP" };
    case "closed_sl":
      return { bar: "#FF1744", pill: "#FF1744", label: "SL" };
    case "open":
      return { bar: "#F5A623", pill: "#F5A623", label: "OPEN" };
    case "closed_manual":
    case "closed_time":
    default:
      return { bar: "#787B86", pill: "#787B86", label: status === "closed_manual" ? "MANUAL" : "TIME" };
  }
}

function directionUi(dir: string): { arrow: string; label: string; color: string } {
  const d = dir.toLowerCase();
  if (d === "long" || d === "up") return { arrow: "\u25B2", label: "LONG", color: "#26A69A" };
  return { arrow: "\u25BC", label: "SHORT", color: "#FF1744" };
}

const STATUS_BUTTONS: { key: StatusFilter; label: string }[] = [
  { key: "ALL", label: "ALL" },
  { key: "open", label: "OPEN" },
  { key: "closed_tp", label: "TP HIT" },
  { key: "closed_sl", label: "SL HIT" },
  { key: "closed_manual", label: "MANUAL" },
  { key: "closed_time", label: "TIME" },
];

type UniverseKey = "multi_asset" | "synthetic" | "crypto";

const UNIVERSE_TABS: Array<{ key: UniverseKey | "ALL"; label: string; icon: string }> = [
  { key: "ALL", label: "ALL UNIVERSES", icon: "◆" },
  { key: "multi_asset", label: "MULTI-ASSET", icon: "◈" },
  { key: "synthetic", label: "SYNTHETIC", icon: "⬡" },
  { key: "crypto", label: "CRYPTO", icon: "₿" },
];

const SYNTHETIC_PREFIXES_TRADES = [
  "R_", "1HZ", "BOOM", "CRASH", "JD",
  "OTC_", "STEP", "WLD", "RB", "RDBULL", "STPRNG",
];

function _inferUniverseFrontend(symbol: string, category?: string | null): UniverseKey {
  const sym = (symbol || "").toUpperCase();
  if (sym.endsWith("USDT") || sym.endsWith("BTC")) return "crypto";
  if (SYNTHETIC_PREFIXES_TRADES.some((p) => sym.startsWith(p))) return "synthetic";
  const c = (category || "").toLowerCase();
  if (c === "synthetic") return "synthetic";
  if (c === "crypto") return "crypto";
  return "multi_asset";
}

function TradeCloseDot(props: {
  cx?: number;
  cy?: number;
  payload?: { trade_pnl?: number | null };
}) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null) return null;
  if (payload?.trade_pnl == null) return null;
  return <circle cx={cx} cy={cy} r={4} fill="#7B61FF" stroke="#0D0F14" strokeWidth={1} />;
}

function TradesPageSkeleton() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: "16px 20px",
        fontFamily: "'IBM Plex Mono', monospace",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8,
        }}
      >
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              height: 120,
              background: "#111318",
              borderRadius: 2,
              animation: "card-pulse 1.5s ease-in-out infinite",
            }}
          />
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(8, 1fr)",
          gap: 6,
        }}
      >
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <div
            key={i}
            style={{
              height: 52,
              background: "#111318",
              borderRadius: 2,
              animation: "card-pulse 1.5s ease-in-out infinite",
            }}
          />
        ))}
      </div>
      <div
        style={{
          height: 180,
          background: "#111318",
          borderRadius: 2,
          animation: "card-pulse 1.5s ease-in-out infinite",
        }}
      />
      <style>{`@keyframes card-pulse{0%,100%{opacity:0.3}50%{opacity:0.6}}`}</style>
    </div>
  );
}

export default function TradesPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [performance, setPerformance] = useState<PaperPerformance | null>(null);
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [symbolInput, setSymbolInput] = useState("");
  const [symbolDebounced, setSymbolDebounced] = useState("");
  const [limit, setLimit] = useState<50 | 100 | 500>(50);
  const [closingId, setClosingId] = useState<number | null>(null);
  const [activeUniverse, setActiveUniverse] = useState<UniverseKey | "ALL">("ALL");

  useEffect(() => {
    const t = setTimeout(() => setSymbolDebounced(symbolInput.trim()), 350);
    return () => clearTimeout(t);
  }, [symbolInput]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const universeParam = activeUniverse === "ALL" ? undefined : activeUniverse;
      const [acc, perf, trParams] = await Promise.all([
        api.getPaperAccounts(),
        api.getPaperPerformance(selectedAccountId ?? undefined, universeParam),
        api.getPaperTrades({
          account_id: selectedAccountId ?? undefined,
          status: statusFilter === "ALL" ? undefined : statusFilter,
          limit,
          symbol: symbolDebounced ? symbolDebounced.toUpperCase() : undefined,
        }),
      ]);
      setAccounts(Array.isArray(acc) ? acc : []);
      setPerformance(perf);
      setTrades(Array.isArray(trParams) ? trParams : []);
    } catch {
      setAccounts([]);
      setPerformance(null);
      setTrades([]);
    } finally {
      setLoading(false);
    }
  }, [selectedAccountId, statusFilter, limit, symbolDebounced, activeUniverse]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const sortedAccounts = useMemo(() => {
    const filtered = activeUniverse === "ALL"
      ? accounts
      : accounts.filter((a) => {
          const u = (a.universe as UniverseKey | null | undefined) ?? null;
          return u === activeUniverse;
        });
    return [...filtered].sort((a, b) => a.id - b.id);
  }, [accounts, activeUniverse]);

  const filteredTrades = useMemo(() => {
    if (activeUniverse === "ALL") return trades;
    return trades.filter(
      (t) => _inferUniverseFrontend(t.symbol) === activeUniverse,
    );
  }, [trades, activeUniverse]);

  const chartData = useMemo(() => {
    const curve = performance?.pnl_curve ?? [];
    return curve
      .filter((p) => p.timestamp)
      .map((p) => ({
        ...p,
        t: new Date(p.timestamp).getTime(),
      }))
      .sort((a, b) => a.t - b.t);
  }, [performance]);

  const totalPnl = performance?.total_pnl_usd ?? 0;
  const fillPositive = totalPnl >= 0;

  async function handleCloseTrade(id: number) {
    setClosingId(id);
    try {
      await api.closePaperTrade(id);
      await refresh();
    } catch {
      // silent
    } finally {
      setClosingId(null);
    }
  }

  const filterButtonStyle = (active: boolean): CSSProperties => ({
    padding: "4px 10px",
    fontSize: 10,
    letterSpacing: "0.08em",
    fontFamily: MONO,
    border: `1px solid ${active ? "#F5A623" : BORDER}`,
    background: active ? "#F5A623" : "transparent",
    color: active ? "#0D0F14" : "#787B86",
    cursor: "pointer",
    textTransform: "uppercase",
    borderRadius: 2,
  });

  return (
    <div
      style={{
        minHeight: "100vh",
        background: BG,
        color: "#D1D4DC",
        fontFamily: MONO,
        padding: "24px 28px 40px",
      }}
    >
      <style>{`@keyframes trades-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div
            style={{
              fontSize: 11,
              letterSpacing: "0.15em",
              color: "#F5A623",
              textTransform: "uppercase",
              fontWeight: 700,
            }}
          >
            TRADE HISTORY
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: "#787B86", letterSpacing: "0.06em" }}>
            PAPER TRADING · ALL ACCOUNTS
          </div>
        </div>
        <button
          type="button"
          aria-label="Refresh"
          onClick={() => void refresh()}
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            border: `1px solid ${BORDER}`,
            background: "#111318",
            color: "#F5A623",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <RefreshCw
            size={16}
            strokeWidth={2}
            style={loading ? { animation: "trades-spin 0.9s linear infinite" } : undefined}
          />
        </button>
      </div>

      {/* Universe tab bar */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: `1px solid ${BORDER}`,
          background: "#0D0F14",
          padding: 0,
          marginBottom: 16,
        }}
      >
        {UNIVERSE_TABS.map((tab) => (
          <button
            key={`universe-tab-${tab.key}`}
            type="button"
            onClick={() => {
              setActiveUniverse(tab.key);
              setSelectedAccountId(null);
            }}
            style={{
              padding: "10px 18px",
              background: "transparent",
              border: "none",
              borderBottom: activeUniverse === tab.key
                ? "2px solid #F5A623"
                : "2px solid transparent",
              color: activeUniverse === tab.key ? "#F5A623" : "#4A4D58",
              fontFamily: MONO,
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span style={{ fontSize: 12 }}>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {loading && accounts.length === 0 ? <TradesPageSkeleton /> : null}

      {/* Account cards */}
      <div
        style={{
          display: loading && accounts.length === 0 ? "none" : "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {sortedAccounts.map((a) => {
          const active = selectedAccountId === a.id;
          const pnlPos = a.total_pnl_usd >= 0;
          return (
            <button
              key={a.id}
              type="button"
              onClick={() => setSelectedAccountId(active ? null : a.id)}
              style={{
                textAlign: "left",
                padding: 14,
                background: "#111318",
                border: `1px solid ${BORDER}`,
                borderLeft: active ? "3px solid #F5A623" : `1px solid ${BORDER}`,
                cursor: "pointer",
                transition: "border-color 120ms, background 120ms",
                fontFamily: MONO,
                color: "inherit",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#2A3140";
                e.currentTarget.style.background = "#141820";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = BORDER;
                e.currentTarget.style.background = "#111318";
              }}
            >
              <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "#787B86", marginBottom: 8 }}>
                {a.name.toUpperCase()}
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#FFFFFF" }}>{formatUsd(a.balance_usd)}</div>
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: pnlPos ? "#00C853" : "#FF1744" }}>
                  {pnlPos ? "+" : ""}
                  {formatUsd(a.total_pnl_usd)}
                </span>
                <span style={{ fontSize: 11, color: "#787B86" }}>
                  ({pnlPos ? "+" : ""}
                  {a.total_pnl_pct.toFixed(1)}%)
                </span>
                {a.is_paused_drawdown ? (
                  <span
                    style={{
                      fontSize: 8,
                      letterSpacing: "0.08em",
                      padding: "2px 6px",
                      background: "rgba(245,166,35,0.15)",
                      border: "1px solid #F5A623",
                      color: "#F5A623",
                    }}
                  >
                    PAUSED
                  </span>
                ) : null}
              </div>
              <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ flex: 1, height: 4, background: "#1E222D", borderRadius: 1, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${Math.min(100, a.win_rate_pct)}%`,
                      height: "100%",
                      background: "#7B61FF",
                    }}
                  />
                </div>
                <span style={{ fontSize: 10, color: "#787B86" }}>{a.win_rate_pct.toFixed(0)}%</span>
              </div>
              <div style={{ marginTop: 8, fontSize: 10, color: "#787B86" }}>
                OPEN POSITIONS{" "}
                <span
                  style={{
                    marginLeft: 6,
                    padding: "1px 6px",
                    borderRadius: 2,
                    background: "rgba(123,97,255,0.2)",
                    color: "#B8A9FF",
                  }}
                >
                  {a.open_positions}
                </span>
              </div>
            </button>
          );
        })}
        {sortedAccounts.length === 0 && !loading ? (
          <div style={{ gridColumn: "1 / -1", fontSize: 11, color: "#787B86" }}>No paper accounts configured.</div>
        ) : null}
      </div>

      {/* Risk-adjusted performance metrics */}
      {performance && performance.total_closed_trades > 0 ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))",
            gap: 8,
            padding: "12px 0",
            borderBottom: `1px solid ${BORDER}`,
            marginBottom: 12,
          }}
        >
          {(
            [
              {
                label: "SHARPE",
                value:
                  performance.sharpe_ratio != null
                    ? performance.sharpe_ratio.toFixed(2)
                    : "—",
                tooltip:
                  "Annualized risk-adjusted return. >1 good, >2 excellent",
                color:
                  (performance.sharpe_ratio ?? 0) > 1 ? "#00C853" : "#787B86",
              },
              {
                label: "SORTINO",
                value:
                  performance.sortino_ratio != null
                    ? performance.sortino_ratio.toFixed(2)
                    : "—",
                tooltip:
                  "Like Sharpe but only penalizes downside volatility",
                color:
                  (performance.sortino_ratio ?? 0) > 1 ? "#00C853" : "#787B86",
              },
              {
                label: "CALMAR",
                value:
                  performance.calmar_ratio != null
                    ? performance.calmar_ratio.toFixed(2)
                    : "—",
                tooltip: "Annualized return divided by max drawdown",
                color:
                  (performance.calmar_ratio ?? 0) > 0 ? "#00C853" : "#787B86",
              },
              {
                label: "PROFIT FACTOR",
                value:
                  performance.profit_factor != null
                    ? performance.profit_factor.toFixed(2)
                    : "—",
                tooltip:
                  "Gross profit divided by gross loss. >1.5 is good",
                color:
                  (performance.profit_factor ?? 0) > 1.5
                    ? "#00C853"
                    : (performance.profit_factor ?? 0) > 1
                      ? "#F5A623"
                      : "#EF5350",
              },
              {
                label: "WIN RATE",
                value:
                  performance.win_rate_pct != null
                    ? `${performance.win_rate_pct.toFixed(1)}%`
                    : "—",
                tooltip:
                  "Percentage of closed trades that were profitable",
                color:
                  (performance.win_rate_pct ?? 0) > 50 ? "#00C853" : "#F5A623",
              },
              {
                label: "AVG R:R",
                value:
                  performance.risk_reward_ratio != null
                    ? performance.risk_reward_ratio.toFixed(2)
                    : "—",
                tooltip: "Average win divided by average loss",
                color:
                  (performance.risk_reward_ratio ?? 0) > 1.5
                    ? "#00C853"
                    : "#787B86",
              },
              {
                label: "MAX DD",
                value:
                  performance.max_drawdown_pct != null
                    ? `${performance.max_drawdown_pct.toFixed(1)}%`
                    : "—",
                tooltip:
                  "Largest peak-to-trough decline as % of initial balance",
                color:
                  (performance.max_drawdown_pct ?? 0) > 10
                    ? "#EF5350"
                    : "#787B86",
              },
              {
                label: "DD DURATION",
                value:
                  performance.max_drawdown_duration_days != null
                    ? `${performance.max_drawdown_duration_days}d`
                    : "—",
                tooltip:
                  "Longest period spent below previous equity peak",
                color: "#787B86",
              },
            ] as const
          ).map((stat) => (
            <div
              key={stat.label}
              title={stat.tooltip}
              style={{
                background: "#111318",
                border: `1px solid ${BORDER}`,
                borderRadius: 2,
                padding: "8px 10px",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 7,
                  letterSpacing: "0.1em",
                  color: "#4A4D58",
                  textTransform: "uppercase",
                }}
              >
                {stat.label}
              </div>
              <div
                style={{
                  fontFamily: MONO,
                  fontSize: 14,
                  fontWeight: 700,
                  color: stat.color,
                }}
              >
                {stat.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Equity curve */}
      <div
        style={{
          height: 180,
          minHeight: 180,
          minWidth: 0,
          marginBottom: 20,
          background: BG,
          border: `1px solid ${BORDER}`,
          display: loading && accounts.length === 0 ? "none" : "block",
        }}
      >
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="pnlFillPos" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#7B61FF" stopOpacity={0.08} />
                <stop offset="100%" stopColor="#7B61FF" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="pnlFillNeg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#FF1744" stopOpacity={0.08} />
                <stop offset="100%" stopColor="#FF1744" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1a1f28" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tick={{ fill: "#787B86", fontSize: 9, fontFamily: MONO }}
              tickFormatter={(v) => {
                const d = new Date(v);
                return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { month: "short", day: "numeric" });
              }}
              axisLine={{ stroke: BORDER }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#787B86", fontSize: 9, fontFamily: MONO }}
              tickFormatter={(v) => `$${v}`}
              axisLine={{ stroke: BORDER }}
              tickLine={false}
              width={56}
            />
            <ReferenceLine y={0} stroke="#434651" strokeDasharray="4 4" />
            <RechartsTooltip
              contentStyle={{
                background: "#111318",
                border: `1px solid ${BORDER}`,
                fontFamily: MONO,
                fontSize: 10,
              }}
              labelFormatter={(v) => String(v)}
              formatter={(value, _name, item) => {
                const v = typeof value === "number" ? formatUsd(value) : String(value ?? "");
                const sym = (item?.payload as { symbol?: string } | undefined)?.symbol ?? "";
                return [v, sym];
              }}
            />
            <Area
              type="stepAfter"
              dataKey="cumulative_pnl"
              stroke="none"
              fill={fillPositive ? "url(#pnlFillPos)" : "url(#pnlFillNeg)"}
              fillOpacity={1}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="cumulative_pnl"
              stroke="#7B61FF"
              strokeWidth={2}
              dot={<TradeCloseDot />}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 9, color: "#787B86", marginRight: 4 }}>ACCOUNT</span>
          <button
            type="button"
            style={filterButtonStyle(selectedAccountId === null)}
            onClick={() => setSelectedAccountId(null)}
          >
            ALL
          </button>
          {sortedAccounts.map((a) => (
            <button
              key={`f-${a.id}`}
              type="button"
              style={filterButtonStyle(selectedAccountId === a.id)}
              onClick={() => setSelectedAccountId(a.id)}
            >
              {a.name.toUpperCase()}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span style={{ fontSize: 9, color: "#787B86", marginRight: 4 }}>STATUS</span>
          {STATUS_BUTTONS.map((b) => (
            <button
              key={b.key}
              type="button"
              style={filterButtonStyle(statusFilter === b.key)}
              onClick={() => setStatusFilter(b.key)}
            >
              {b.label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
          <input
            type="text"
            placeholder="SYMBOL"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            style={{
              background: "#111318",
              border: `1px solid ${BORDER}`,
              color: "#D1D4DC",
              padding: "6px 10px",
              fontSize: 11,
              fontFamily: MONO,
              minWidth: 140,
            }}
          />
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 9, color: "#787B86" }}>LIMIT</span>
            {([50, 100, 500] as const).map((n) => (
              <button key={n} type="button" style={filterButtonStyle(limit === n)} onClick={() => setLimit(n)}>
                {n}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Table */}
      {filteredTrades.length === 0 && !loading ? (
        <div style={{ padding: "48px 24px", textAlign: "center" }}>
          <div style={{ fontSize: 12, letterSpacing: "0.12em", color: "#787B86" }}>NO PAPER TRADES YET</div>
          <div style={{ marginTop: 10, fontSize: 10, color: "#4A4D58", maxWidth: 360, marginInline: "auto" }}>
            Paper trading engine will open positions when entry conditions are met.
          </div>
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          {filteredTrades.map((trade) => {
            const su = statusUi(trade.status);
            const dir = directionUi(trade.direction);
            const pnl = trade.pnl_usd;
            const pnlPct = trade.pnl_pct;
            return (
              <div
                key={trade.id}
                role="button"
                tabIndex={0}
                onClick={() => router.push(`/market?symbol=${encodeURIComponent(trade.symbol)}&timeframe=1d`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    router.push(`/market?symbol=${encodeURIComponent(trade.symbol)}&timeframe=1d`);
                  }
                }}
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "4px minmax(72px,0.9fr) minmax(88px,0.7fr) minmax(100px,0.8fr) minmax(48px,0.4fr) minmax(200px,1.2fr) minmax(44px,0.35fr) minmax(72px,0.5fr) minmax(88px,0.6fr) minmax(72px,0.5fr) minmax(56px,0.4fr) minmax(40px,0.35fr)",
                  gap: 8,
                  alignItems: "center",
                  padding: "10px 8px",
                  cursor: "pointer",
                  background: "transparent",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(255,255,255,0.02)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                <div style={{ width: 4, alignSelf: "stretch", background: su.bar, borderRadius: 1 }} />
                <div style={{ fontSize: 13, fontWeight: 700, color: "#FFFFFF" }}>{trade.symbol}</div>
                <div style={{ fontSize: 11, fontWeight: 700, color: dir.color }}>
                  {dir.arrow} {dir.label}
                </div>
                <div>
                  {trade.market_state_at_entry ? (
                    <span
                      style={{
                        fontSize: 8,
                        letterSpacing: "0.06em",
                        padding: "2px 6px",
                        background: "#1E222D",
                        color: "#787B86",
                      }}
                    >
                      {trade.market_state_at_entry}
                    </span>
                  ) : (
                    <span style={{ fontSize: 9, color: "#434651" }}>—</span>
                  )}
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#F5A623" }}>
                  {trade.score_at_entry != null ? formatPriceCompact(trade.score_at_entry) : "—"}
                </div>
                <div style={{ fontSize: 9, color: "#9CA3AF", display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <span>E {formatPriceCompact(trade.entry_price)}</span>
                  <span>S {formatPriceCompact(trade.stop_price)}</span>
                  <span>
                    TP {trade.take_profit_price != null ? formatPriceCompact(trade.take_profit_price) : "—"}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: "#787B86" }}>{trade.lot_size.toFixed(4)}</div>
                <div style={{ fontSize: 10, color: "#787B86" }}>{formatUsd(trade.risk_amount_usd)}</div>
                <div>
                  {pnl != null ? (
                    <>
                      <div
                        style={{
                          fontSize: 14,
                          fontWeight: 700,
                          color: pnl >= 0 ? "#00C853" : "#FF1744",
                        }}
                      >
                        {pnl >= 0 ? "+" : ""}
                        {formatUsd(pnl)}
                      </div>
                      {pnlPct != null ? (
                        <div style={{ fontSize: 9, color: "#787B86" }}>
                          ({pnlPct >= 0 ? "+" : ""}
                          {pnlPct.toFixed(2)}%)
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div style={{ fontSize: 11, color: "#787B86" }}>—</div>
                  )}
                </div>
                <div style={{ fontSize: 10, color: "#787B86" }}>{tradeDuration(trade.open_at, trade.close_at)}</div>
                <div>
                  <span
                    style={{
                      fontSize: 8,
                      letterSpacing: "0.06em",
                      padding: "3px 8px",
                      borderRadius: 999,
                      background: `${su.pill}22`,
                      color: su.pill,
                      border: `1px solid ${su.pill}`,
                    }}
                  >
                    {su.label}
                  </span>
                </div>
                <div
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                  style={{ display: "flex", justifyContent: "center" }}
                >
                  {trade.status === "open" ? (
                    <button
                      type="button"
                      aria-label="Close trade"
                      disabled={closingId === trade.id}
                      onClick={() => void handleCloseTrade(trade.id)}
                      style={{
                        border: `1px solid ${BORDER}`,
                        background: "#111318",
                        color: "#FF1744",
                        cursor: closingId === trade.id ? "wait" : "pointer",
                        padding: 4,
                        borderRadius: 2,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <X size={14} />
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
