export default function AnalyticsPage() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        background: "var(--bg-base)",
        flexDirection: "column",
      }}
    >
      <div style={{ fontSize: 12, color: "var(--text-secondary)", letterSpacing: "0.2em", fontFamily: "inherit" }}>ANALYTICS</div>
      <div style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.08em", marginTop: 6 }}>MODULE UNDER CONSTRUCTION</div>
      <div style={{ width: 40, height: 1, background: "var(--border-subtle)", margin: "16px 0" }} />
      <div style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.08em" }}>AVAILABLE IN NEXT BUILD</div>
    </div>
  );
}