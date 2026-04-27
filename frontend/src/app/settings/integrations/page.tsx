"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { CircleHelp, Inbox } from "lucide-react";

import { IntegrationsPageSkeleton } from "@/components/ui/page-skeleton";
import { api } from "@/lib/api";
import { Tooltip } from "@/components/ui/tooltip";
import type {
  BrokerConnectionTestResponse,
  BrokerIntegrationStatus,
  ExecutionEventItem,
  ExecutionOrderSummary,
  ExecutionStatusResponse,
  FromSignalRequest,
  IntegrationsStatusResponse,
  NormalizedOrderIntent,
  OrderSubmissionResponse,
} from "@/lib/types";

type BrokerKey = "binance" | "deriv" | "ftmo";

const MONO = '"IBM Plex Mono", monospace' as const;

const BROKER_LABELS: Record<BrokerKey, string> = {
  binance: "BINANCE",
  deriv: "DERIV",
  ftmo: "FTMO",
};

const TOOLTIP_BINANCE_KEY =
  "Your Binance API key. Found in Account → API Management. Needs Read and Spot permissions.";
const TOOLTIP_BINANCE_SECRET =
  "Your Binance API secret. Shown once when you create the key in API Management. Store securely.";
const TOOLTIP_DERIV_KEY =
  "Deriv account API app ID if required by your integration; trading auth typically uses the API token.";
const TOOLTIP_DERIV_TOKEN =
  "Deriv API token from your Deriv account (app settings / API token). Used for WebSocket and trading APIs.";
const TOOLTIP_FTMO_KEY =
  "FTMO API credentials from your FTMO dashboard for the integration endpoint.";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toUTCString().replace("GMT", "UTC");
}

const inputStyle: CSSProperties = {
  background: "var(--bg-input)",
  border: "1px solid var(--border-default)",
  color: "var(--text-primary)",
  padding: "8px 10px",
  fontSize: 10,
  fontFamily: MONO,
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const credentialInputStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: "var(--bg-elevated)",
  border: "1px solid var(--border-default)",
  borderRadius: 0,
  color: "var(--text-primary)",
  padding: "8px 10px",
  fontSize: 11,
  fontFamily: MONO,
  outline: "none",
  boxSizing: "border-box",
};

const sectionLabelStyle: CSSProperties = {
  fontFamily: MONO,
  fontSize: 9,
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  color: "var(--text-dim)",
  marginBottom: 8,
};

function truncateId(s: string, max = 12): string {
  if (s.length <= max) return s;
  return `${s.slice(0, 6)}…${s.slice(-4)}`;
}

function ExecutionBadge({
  label,
  value,
  valueColor,
  borderColor,
}: {
  label: string;
  value: string;
  valueColor: string;
  borderColor: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      <span style={{ fontFamily: MONO, fontSize: 8, letterSpacing: "0.12em", color: "var(--text-dim)" }}>{label}</span>
      <span
        style={{
          fontFamily: MONO,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          padding: "6px 12px",
          border: `1px solid ${borderColor}`,
          borderRadius: 0,
          color: valueColor,
          background: "var(--bg-base)",
          display: "inline-block",
          width: "fit-content",
          maxWidth: "100%",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function CredentialFieldRow({
  fieldLabel,
  value,
  onChange,
  placeholder,
  tooltip,
}: {
  fieldLabel: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  tooltip: string;
}) {
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <span style={{ fontFamily: MONO, fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--text-dim)" }}>
        {fieldLabel}
      </span>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          style={credentialInputStyle}
          autoComplete="off"
        />
        <Tooltip content={tooltip}>
          <button
            type="button"
            aria-label={`Help: ${fieldLabel}`}
            style={{
              flexShrink: 0,
              width: 28,
              height: 28,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "1px solid var(--border-strong)",
              borderRadius: 0,
              background: "var(--bg-elevated)",
              color: "var(--text-dim)",
              cursor: "help",
              padding: 0,
            }}
          >
            <CircleHelp size={14} strokeWidth={2} aria-hidden />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}

function BrokerConnectionCard({
  broker,
  status,
  onTest,
}: {
  broker: BrokerKey;
  status: BrokerIntegrationStatus | undefined;
  onTest: (broker: BrokerKey, payload: { api_key?: string; api_secret?: string; token?: string }) => Promise<BrokerConnectionTestResponse>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [token, setToken] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<BrokerConnectionTestResponse | null>(null);

  const connected = status?.connected ?? false;
  const lastSync = status?.last_sync ?? null;

  const showApiSecret = broker === "binance";
  const showToken = broker === "deriv";

  return (
    <section style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: 14, display: "flex", flexDirection: "column", gap: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", fontFamily: MONO, letterSpacing: "0.04em" }}>
            {BROKER_LABELS[broker]}
          </span>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              flexShrink: 0,
              background: connected ? "#26A69A" : "var(--text-muted)",
              boxShadow: connected ? "0 0 6px rgba(38,166,154,0.5)" : "none",
            }}
            title={connected ? "Connected" : "Not connected"}
          />
        </div>
        <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: MONO, letterSpacing: "0.06em", textAlign: "right" }}>
          {formatTimestamp(lastSync)}
        </span>
      </div>

      <div style={{ height: 1, background: "var(--border-default)", marginBottom: 12 }} />

      <div style={sectionLabelStyle}>CREDENTIALS</div>
      <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
        <CredentialFieldRow
          fieldLabel="API KEY"
          value={apiKey}
          onChange={setApiKey}
          placeholder={`${BROKER_LABELS[broker]} API KEY`}
          tooltip={broker === "binance" ? TOOLTIP_BINANCE_KEY : broker === "deriv" ? TOOLTIP_DERIV_KEY : TOOLTIP_FTMO_KEY}
        />
        {showApiSecret ? (
          <CredentialFieldRow
            fieldLabel="API SECRET"
            value={apiSecret}
            onChange={setApiSecret}
            placeholder="BINANCE API SECRET"
            tooltip={TOOLTIP_BINANCE_SECRET}
          />
        ) : null}
        {showToken ? (
          <CredentialFieldRow
            fieldLabel="API TOKEN / OAUTH TOKEN"
            value={token}
            onChange={setToken}
            placeholder="DERIV TOKEN"
            tooltip={TOOLTIP_DERIV_TOKEN}
          />
        ) : null}
      </div>

      <div style={{ height: 1, background: "var(--border-default)", marginBottom: 12 }} />

      <div style={sectionLabelStyle}>STATUS</div>
      <div style={{ display: "grid", gap: 6, marginBottom: 12 }}>
        <div style={{ fontFamily: MONO, fontSize: 11, color: connected ? "#26A69A" : "#EF5350", fontWeight: 600, letterSpacing: "0.08em" }}>
          {connected ? "CONNECTED" : "DISCONNECTED"}
        </div>
        <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)" }}>
          {/* API exposes last_sync only — no separate "last successful connection" field */}
          Last sync: {formatTimestamp(lastSync)}
        </div>
        {status?.message ? (
          <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", lineHeight: 1.45 }}>{status.message}</div>
        ) : null}
        {status?.account?.balance != null ? (
          <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)" }}>
            Balance: {status.account.balance} {status.account.currency ?? ""}
          </div>
        ) : null}
        {status?.account?.challenge_status ? (
          <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)" }}>Challenge: {status.account.challenge_status}</div>
        ) : null}
      </div>

      <button
        type="button"
        className="integrations-test-connection"
        disabled={testing}
        onClick={async () => {
          setTesting(true);
          try {
            const result = await onTest(broker, {
              api_key: apiKey || undefined,
              api_secret: apiSecret || undefined,
              token: token || undefined,
            });
            setTestResult(result);
          } finally {
            setTesting(false);
          }
        }}
      >
        {testing ? "TESTING..." : "TEST CONNECTION"}
      </button>
      {testResult ? (
        <div style={{ marginTop: 8, fontFamily: MONO, fontSize: 9, color: testResult.ok ? "#26A69A" : "#EF5350", lineHeight: 1.4 }}>
          {testResult.message}
        </div>
      ) : null}
    </section>
  );
}

export default function IntegrationsSettingsPage() {
  const [pageReady, setPageReady] = useState(false);
  const [statusData, setStatusData] = useState<IntegrationsStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [executionStatus, setExecutionStatus] = useState<ExecutionStatusResponse | null>(null);
  const [executionOrders, setExecutionOrders] = useState<ExecutionOrderSummary[]>([]);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [orderEvents, setOrderEvents] = useState<ExecutionEventItem[] | null>(null);
  const [eventsLoading, setEventsLoading] = useState(false);

  const [fsSymbol, setFsSymbol] = useState("R_10");
  const [fsTimeframe, setFsTimeframe] = useState("1h");
  const [fsStake, setFsStake] = useState("10");
  const [fsSubmitting, setFsSubmitting] = useState(false);

  const [moSymbol, setMoSymbol] = useState("R_10");
  const [moSide, setMoSide] = useState<"long" | "short">("long");
  const [moStake, setMoStake] = useState("10");
  const [moDuration, setMoDuration] = useState("5");
  const [moDurationUnit, setMoDurationUnit] = useState<NormalizedOrderIntent["duration_unit"]>("t");
  const [moProvider, setMoProvider] = useState<NormalizedOrderIntent["provider"]>("deriv");
  const [moSubmitting, setMoSubmitting] = useState(false);

  const [lastSubmission, setLastSubmission] = useState<OrderSubmissionResponse | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const byBroker = useMemo(() => {
    const map = new Map<BrokerKey, BrokerIntegrationStatus>();
    for (const row of statusData?.brokers ?? []) {
      map.set(row.broker, row);
    }
    return map;
  }, [statusData]);

  async function refreshIntegrations() {
    try {
      const payload = await api.getIntegrationsStatus();
      setStatusData(payload);
      setError(null);
    } catch {
      setError("Failed to load integration status.");
    }
  }

  async function refreshExecutionData(preserveSelection: number | null = selectedOrderId) {
    try {
      const [st, ord] = await Promise.all([api.getExecutionStatus(), api.getExecutionOrders(30)]);
      setExecutionStatus(st);
      setExecutionOrders(ord.items);
      setExecutionError(null);
      if (preserveSelection != null) {
        setEventsLoading(true);
        try {
          const ev = await api.getExecutionOrderEvents(preserveSelection);
          setOrderEvents(ev.items);
          setSelectedOrderId(preserveSelection);
        } catch {
          setOrderEvents(null);
          setSelectedOrderId(null);
        } finally {
          setEventsLoading(false);
        }
      }
    } catch {
      setExecutionError("Failed to load execution status or orders (is the API running?).");
      setExecutionStatus(null);
      setExecutionOrders([]);
      setOrderEvents(null);
      setSelectedOrderId(null);
    }
  }

  async function refreshAll() {
    await Promise.all([refreshIntegrations(), refreshExecutionData(selectedOrderId)]);
  }

  async function selectOrder(id: number) {
    setSelectedOrderId(id);
    setEventsLoading(true);
    setOrderEvents(null);
    try {
      const ev = await api.getExecutionOrderEvents(id);
      setOrderEvents(ev.items);
    } catch {
      setOrderEvents([]);
    } finally {
      setEventsLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await Promise.all([refreshIntegrations(), refreshExecutionData(null)]);
      } finally {
        if (!cancelled) setPageReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  async function runTest(
    broker: BrokerKey,
    payload: { api_key?: string; api_secret?: string; token?: string },
  ): Promise<BrokerConnectionTestResponse> {
    let result: BrokerConnectionTestResponse;
    if (broker === "binance") {
      result = await api.testBinanceConnection(payload);
    } else if (broker === "deriv") {
      result = await api.testDerivConnection(payload);
    } else {
      result = await api.testFtmoConnection(payload);
    }
    await refreshAll();
    return result;
  }

  async function submitFromSignal() {
    setSubmissionError(null);
    setLastSubmission(null);
    setFsSubmitting(true);
    try {
      const stake = Number(fsStake);
      const body: FromSignalRequest = {
        symbol: fsSymbol.trim(),
        timeframe: fsTimeframe.trim() || "1h",
        stake_amount: Number.isFinite(stake) && stake > 0 ? stake : 10,
      };
      const res = await api.postExecutionFromSignal(body);
      setLastSubmission(res);
      await refreshExecutionData(res.ok ? selectedOrderId : null);
    } catch (e) {
      setSubmissionError(e instanceof Error ? e.message : String(e));
    } finally {
      setFsSubmitting(false);
    }
  }

  async function submitManualOrder() {
    setSubmissionError(null);
    setLastSubmission(null);
    setMoSubmitting(true);
    try {
      const stake = Number(moStake);
      const dur = Number(moDuration);
      const body: NormalizedOrderIntent = {
        symbol: moSymbol.trim(),
        side: moSide,
        stake_amount: Number.isFinite(stake) && stake > 0 ? stake : 10,
        provider: moProvider,
        duration: Number.isFinite(dur) && dur >= 1 ? dur : 5,
        duration_unit: moDurationUnit ?? "t",
      };
      const res = await api.postExecutionOrder(body);
      setLastSubmission(res);
      await refreshExecutionData(res.ok ? selectedOrderId : null);
    } catch (e) {
      setSubmissionError(e instanceof Error ? e.message : String(e));
    } finally {
      setMoSubmitting(false);
    }
  }

  const brokers: BrokerKey[] = ["binance", "deriv", "ftmo"];

  const btnGhost: CSSProperties = {
    border: "1px solid var(--border-subtle)",
    background: "transparent",
    color: "var(--text-dim)",
    padding: "6px 10px",
    fontSize: 10,
    letterSpacing: "0.08em",
    fontFamily: MONO,
    cursor: "pointer",
  };

  const btnAccent: CSSProperties = {
    border: "1px solid #F5A623",
    background: "transparent",
    color: "#F5A623",
    padding: "6px 10px",
    fontSize: 10,
    letterSpacing: "0.08em",
    fontFamily: MONO,
    cursor: "pointer",
  };

  const providerUpper = executionStatus?.execution_provider?.trim()
    ? executionStatus.execution_provider.toUpperCase()
    : "—";

  if (!pageReady) {
    return <IntegrationsPageSkeleton />;
  }

  return (
    <div style={{ padding: 16, background: "var(--bg-base)", minHeight: "100%", color: "var(--text-primary)", fontFamily: MONO }}>
      <style>{`
        .integrations-test-connection {
          width: 100%;
          font-family: ${MONO};
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          padding: 10px 12px;
          border: 1px solid #F5A623;
          border-radius: 0;
          background: transparent;
          color: #F5A623;
          cursor: pointer;
        }
        .integrations-test-connection:hover:not(:disabled) {
          background: #F5A623;
          color: var(--bg-base);
        }
        .integrations-test-connection:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
      `}</style>
      <div style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: "10px 12px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.12em" }}>SETTINGS / INTEGRATIONS</span>
          <span style={{ fontSize: 12, color: "var(--text-primary)", letterSpacing: "0.04em" }}>
            Configure broker API credentials, execution paper trading, and connectivity tests.
          </span>
        </div>
        <Tooltip content="Reload integration and execution status">
          <button type="button" onClick={() => void refreshAll()} style={btnGhost}>
            REFRESH
          </button>
        </Tooltip>
      </div>

      {error ? (
        <div style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", color: "#EF5350", padding: 10, fontSize: 10, marginBottom: 12 }}>
          {error}
        </div>
      ) : null}

      {executionError ? (
        <div style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", color: "#F5A623", padding: 10, fontSize: 10, marginBottom: 12 }}>
          {executionError}
        </div>
      ) : null}

      {/* Zone 1 — EXECUTION STATUS */}
      <section style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: 14, marginBottom: 12 }}>
        <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.12em", marginBottom: 12 }}>EXECUTION STATUS</div>

        {executionStatus ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end", marginBottom: 10 }}>
            <ExecutionBadge
              label="EXECUTION"
              value={executionStatus.execution_enabled ? "ENABLED" : "DISABLED"}
              valueColor={executionStatus.execution_enabled ? "#26A69A" : "#EF5350"}
              borderColor={executionStatus.execution_enabled ? "#26A69A" : "#EF5350"}
            />
            <ExecutionBadge
              label="MODE"
              value={executionStatus.execution_paper_only ? "PAPER" : "LIVE"}
              valueColor={executionStatus.execution_paper_only ? "#26A69A" : "#EF5350"}
              borderColor={executionStatus.execution_paper_only ? "#26A69A" : "#EF5350"}
            />
            <ExecutionBadge label="PROVIDER" value={providerUpper} valueColor="#F5A623" borderColor="#F5A623" />
          </div>
        ) : !executionError ? (
          <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)", marginBottom: 10 }}>Loading execution status…</div>
        ) : (
          <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)", marginBottom: 10 }}>—</div>
        )}

        <p style={{ margin: "0 0 14px", fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", lineHeight: 1.5 }}>
          Edit .env and restart to change execution settings
        </p>

        <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.1em", marginBottom: 8 }}>RECENT ORDERS</div>

        {executionOrders.length === 0 ? (
          <div
            style={{
              border: "1px solid var(--border-subtle)",
              background: "var(--bg-base)",
              padding: 28,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              textAlign: "center",
            }}
          >
            <Inbox size={28} strokeWidth={1.25} color="var(--text-muted)" aria-hidden />
            <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--text-dim)" }}>No orders yet</span>
            <span style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)", maxWidth: 280, lineHeight: 1.45 }}>
              Orders will appear here once execution is enabled
            </span>
          </div>
        ) : (
          <div style={{ overflowX: "auto", border: "1px solid var(--border-subtle)", background: "var(--bg-base)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: MONO, fontSize: 10 }}>
              <thead>
                <tr style={{ color: "var(--text-dim)", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px", fontWeight: 400 }}>TIMESTAMP</th>
                  <th style={{ padding: "8px 10px", fontWeight: 400 }}>SYMBOL</th>
                  <th style={{ padding: "8px 10px", fontWeight: 400 }}>SIDE</th>
                  <th style={{ padding: "8px 10px", fontWeight: 400 }}>STATUS</th>
                </tr>
              </thead>
              <tbody>
                {executionOrders.map((row, i) => {
                  const stripe = i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent";
                  const selected = selectedOrderId === row.id;
                  return (
                    <tr
                      key={row.id}
                      onClick={() => void selectOrder(row.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          void selectOrder(row.id);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      style={{
                        cursor: "pointer",
                        background: selected ? "var(--border-subtle)" : stripe,
                        color: "var(--text-primary)",
                      }}
                    >
                      <td style={{ padding: "8px 10px" }}>{formatTimestamp(row.created_at)}</td>
                      <td style={{ padding: "8px 10px" }}>{row.symbol}</td>
                      <td style={{ padding: "8px 10px" }}>{row.side}</td>
                      <td style={{ padding: "8px 10px" }}>{row.status}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {executionOrders.length > 0 ? (
          <div style={{ marginTop: 10 }}>
            {selectedOrderId != null ? (
              <div style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-base)", padding: 10 }}>
                <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", marginBottom: 6 }}>
                  EVENTS FOR ORDER #{selectedOrderId}
                  {eventsLoading ? " (loading…)" : ""}
                </div>
                {!eventsLoading && orderEvents && orderEvents.length === 0 ? (
                  <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)" }}>No events.</div>
                ) : null}
                {!eventsLoading && orderEvents && orderEvents.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: 16, fontFamily: MONO, fontSize: 9, color: "var(--text-primary)" }}>
                    {orderEvents.map((ev) => (
                      <li key={ev.id} style={{ marginBottom: 6 }}>
                        <span style={{ color: "#F5A623" }}>{ev.event_type}</span>
                        {ev.message ? ` — ${ev.message}` : ""}
                        <span style={{ color: "var(--text-muted)" }}> @ {formatTimestamp(ev.created_at)}</span>
                        {ev.payload && Object.keys(ev.payload).length > 0 ? (
                          <details style={{ marginTop: 4 }}>
                            <summary style={{ cursor: "pointer", color: "var(--text-dim)" }}>payload</summary>
                            <pre style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 8, overflow: "auto", color: "var(--text-dim)" }}>
                              {JSON.stringify(ev.payload, null, 2)}
                            </pre>
                          </details>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-muted)" }}>Select a row to view events.</div>
            )}
          </div>
        ) : null}
      </section>

      {/* Zone 2 — BROKER CONNECTIONS */}
      <div style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.12em", marginBottom: 10 }}>BROKER CONNECTIONS</div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 12,
          marginBottom: 12,
        }}
        className="integrations-broker-grid"
      >
        <style>{`
          @media (max-width: 1000px) {
            .integrations-broker-grid { grid-template-columns: 1fr !important; }
          }
        `}</style>
        {brokers.map((broker) => (
          <BrokerConnectionCard key={broker} broker={broker} status={byBroker.get(broker)} onTest={runTest} />
        ))}
      </div>

      <details style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", padding: 14 }}>
        <summary style={{ fontFamily: MONO, fontSize: 10, color: "#F5A623", cursor: "pointer", letterSpacing: "0.08em" }}>
          ADVANCED — SUBMIT ORDERS
        </summary>
        <p style={{ fontFamily: MONO, fontSize: 9, color: "#EF5350", lineHeight: 1.5, margin: "10px 0" }}>
          Warning: With <code style={{ color: "var(--text-dim)" }}>EXECUTION_ENABLED=1</code> and a valid Deriv token, requests are sent to the broker
          (demo vs real depends on your token). Use only on accounts you intend to trade.
        </p>

        <div style={{ display: "grid", gap: 12, marginTop: 10 }}>
          <div style={{ border: "1px solid var(--border-subtle)", padding: 10, background: "var(--bg-base)" }}>
            <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", marginBottom: 8 }}>FROM SIGNAL (cached candles + bridge)</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>SYMBOL</span>
                <input type="text" value={fsSymbol} onChange={(e) => setFsSymbol(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>TIMEFRAME</span>
                <input type="text" value={fsTimeframe} onChange={(e) => setFsTimeframe(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>STAKE</span>
                <input type="text" value={fsStake} onChange={(e) => setFsStake(e.target.value)} style={inputStyle} />
              </label>
            </div>
            <Tooltip content="Submit order from signal bridge payload">
              <button
                type="button"
                disabled={fsSubmitting}
                onClick={() => void submitFromSignal()}
                style={{ ...btnAccent, marginTop: 10, cursor: fsSubmitting ? "wait" : "pointer" }}
              >
                {fsSubmitting ? "SUBMITTING…" : "SUBMIT FROM SIGNAL"}
              </button>
            </Tooltip>
          </div>

          <div style={{ border: "1px solid var(--border-subtle)", padding: 10, background: "var(--bg-base)" }}>
            <div style={{ fontFamily: MONO, fontSize: 9, color: "var(--text-dim)", marginBottom: 8 }}>MANUAL ORDER (Deriv proposal + buy)</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 8 }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>SYMBOL</span>
                <input type="text" value={moSymbol} onChange={(e) => setMoSymbol(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>SIDE</span>
                <select value={moSide} onChange={(e) => setMoSide(e.target.value as "long" | "short")} style={inputStyle}>
                  <option value="long">long</option>
                  <option value="short">short</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>STAKE</span>
                <input type="text" value={moStake} onChange={(e) => setMoStake(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>DURATION</span>
                <input type="text" value={moDuration} onChange={(e) => setMoDuration(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>DURATION UNIT</span>
                <select
                  value={moDurationUnit}
                  onChange={(e) => setMoDurationUnit(e.target.value as NormalizedOrderIntent["duration_unit"])}
                  style={inputStyle}
                >
                  <option value="t">t</option>
                  <option value="s">s</option>
                  <option value="m">m</option>
                  <option value="h">h</option>
                  <option value="d">d</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ fontFamily: MONO, fontSize: 8, color: "var(--text-dim)" }}>PROVIDER</span>
                <select
                  value={moProvider}
                  onChange={(e) => setMoProvider(e.target.value as NormalizedOrderIntent["provider"])}
                  style={inputStyle}
                >
                  <option value="deriv">deriv</option>
                  <option value="stub">stub</option>
                </select>
              </label>
            </div>
            <Tooltip content="Submit manual order intent to execution API">
              <button
                type="button"
                disabled={moSubmitting}
                onClick={() => void submitManualOrder()}
                style={{ ...btnAccent, marginTop: 10, cursor: moSubmitting ? "wait" : "pointer" }}
              >
                {moSubmitting ? "SUBMITTING…" : "SUBMIT MANUAL ORDER"}
              </button>
            </Tooltip>
          </div>
        </div>

        {submissionError ? (
          <div style={{ marginTop: 10, fontFamily: MONO, fontSize: 9, color: "#EF5350", lineHeight: 1.4 }}>{submissionError}</div>
        ) : null}
        {lastSubmission ? (
          <div
            style={{
              marginTop: 10,
              fontFamily: MONO,
              fontSize: 9,
              color: lastSubmission.ok ? "#26A69A" : "#EF5350",
              lineHeight: 1.4,
            }}
          >
            Result: ok={String(lastSubmission.ok)} status={lastSubmission.status} client_order_id=
            {truncateId(lastSubmission.client_order_id, 20)}
            {lastSubmission.message ? ` — ${lastSubmission.message}` : ""}
          </div>
        ) : null}
      </details>
    </div>
  );
}
