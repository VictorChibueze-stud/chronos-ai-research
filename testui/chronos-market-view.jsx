import { useState, useEffect, useRef } from "react";

// ── Simulated OHLC price data ────────────────────────────────────────────────
function generateCandles(n = 80) {
  const candles = [];
  let price = 2280;
  for (let i = 0; i < n; i++) {
    const open = price + (Math.random() - 0.48) * 6;
    const move = (Math.random() - 0.42) * 18;
    const close = open + move;
    const high = Math.max(open, close) + Math.random() * 8;
    const low = Math.min(open, close) - Math.random() * 8;
    candles.push({ open, close, high, low, i });
    price = close;
  }
  return candles;
}

const CANDLES = generateCandles(80);

// Annotations overlaid on chart — your system's language
const ANNOTATIONS = [
  { type: "BOS",    x: 18, price: 2291, label: "BOS",         color: "#F5A623", dir: "BULL" },
  { type: "CHoCH",  x: 31, price: 2304, label: "CHoCH",       color: "#C8851A", dir: "BULL" },
  { type: "BOS",    x: 52, price: 2318, label: "BOS",         color: "#F5A623", dir: "BULL" },
  { type: "FALSE",  x: 42, price: 2311, label: "FALSE BREAK",  color: "#E05A5A", dir: "BEAR" },
  { type: "TRUE",   x: 60, price: 2326, label: "TRUE BREAK",   color: "#4CAF7D", dir: "BULL" },
];

const IMPULSE_ZONES = [
  { xStart: 14, xEnd: 22, label: "IMP 1", yTop: 2295, yBot: 2278 },
  { xStart: 34, xEnd: 46, label: "IMP 2", yTop: 2318, yBot: 2299 },
  { xStart: 55, xEnd: 70, label: "IMP 3", yTop: 2341, yBot: 2316 },
];

const RETRACEMENT_ZONES = [
  { xStart: 22, xEnd: 34, label: "RET 1", yTop: 2299, yBot: 2287 },
  { xStart: 46, xEnd: 55, label: "RET 2", yTop: 2316, yBot: 2307 },
];

// ── Chart Canvas ─────────────────────────────────────────────────────────────
function CandleChart({ candles, annotations, impulseZones, retracementZones, activeAnnotation, onAnnotationHover }) {
  const canvasRef = useRef(null);
  const W = 820, H = 340;
  const PAD = { top: 24, right: 20, bottom: 28, left: 52 };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, W, H);

    const allPrices = candles.flatMap(c => [c.high, c.low]);
    const minP = Math.min(...allPrices) - 4;
    const maxP = Math.max(...allPrices) + 4;
    const chartW = W - PAD.left - PAD.right;
    const chartH = H - PAD.top - PAD.bottom;
    const candleW = chartW / candles.length;

    const toX = (i) => PAD.left + (i + 0.5) * candleW;
    const toY = (p) => PAD.top + chartH - ((p - minP) / (maxP - minP)) * chartH;

    // Grid
    ctx.strokeStyle = "#1C1E24";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
      const y = PAD.top + (chartH / 5) * i;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      const price = maxP - ((maxP - minP) / 5) * i;
      ctx.fillStyle = "#3A3D48";
      ctx.font = "9px IBM Plex Mono";
      ctx.fillText(price.toFixed(2), 2, y + 3);
    }

    // Impulse zones
    impulseZones.forEach(z => {
      const x1 = PAD.left + z.xStart * candleW;
      const x2 = PAD.left + z.xEnd * candleW;
      const y1 = toY(z.yTop);
      const y2 = toY(z.yBot);
      ctx.fillStyle = "rgba(245,166,35,0.05)";
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeStyle = "rgba(245,166,35,0.2)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(245,166,35,0.5)";
      ctx.font = "8px IBM Plex Mono";
      ctx.fillText(z.label, x1 + 4, y1 + 11);
    });

    // Retracement zones
    retracementZones.forEach(z => {
      const x1 = PAD.left + z.xStart * candleW;
      const x2 = PAD.left + z.xEnd * candleW;
      const y1 = toY(z.yTop);
      const y2 = toY(z.yBot);
      ctx.fillStyle = "rgba(100,120,180,0.04)";
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeStyle = "rgba(100,120,180,0.15)";
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(100,120,180,0.5)";
      ctx.font = "8px IBM Plex Mono";
      ctx.fillText(z.label, x1 + 4, y1 + 11);
    });

    // Candles
    candles.forEach(c => {
      const x = toX(c.i);
      const bull = c.close >= c.open;
      const color = bull ? "#4CAF7D" : "#E05A5A";
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, toY(c.high));
      ctx.lineTo(x, toY(c.low));
      ctx.stroke();
      const bodyTop = toY(Math.max(c.open, c.close));
      const bodyH = Math.max(1, Math.abs(toY(c.open) - toY(c.close)));
      ctx.fillStyle = bull ? "rgba(76,175,125,0.7)" : "rgba(224,90,90,0.7)";
      ctx.fillRect(x - candleW * 0.3, bodyTop, candleW * 0.6, bodyH);
    });

    // Annotation lines
    annotations.forEach(a => {
      const x = toX(a.x);
      const y = toY(a.price);
      const isActive = activeAnnotation === a.label;
      ctx.strokeStyle = isActive ? a.color : a.color + "88";
      ctx.lineWidth = isActive ? 1.5 : 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      ctx.setLineDash([]);
      // Label pill
      const lw = ctx.measureText(a.label).width + 12;
      ctx.fillStyle = isActive ? a.color : a.color + "33";
      ctx.fillRect(x - lw / 2, y - 9, lw, 16);
      ctx.fillStyle = isActive ? "#0D0F14" : a.color;
      ctx.font = `${isActive ? "bold " : ""}8px IBM Plex Mono`;
      ctx.fillText(a.label, x - lw / 2 + 6, y + 3);
    });

  }, [candles, annotations, activeAnnotation]);

  return (
    <canvas
      ref={canvasRef}
      width={W}
      height={H}
      style={{ display: "block", width: "100%", height: "100%" }}
    />
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────
function Label({ children, color = "#3A3D48" }) {
  return <span style={{ fontSize: 9, color, letterSpacing: "0.12em", fontFamily: "'IBM Plex Mono', monospace" }}>{children}</span>;
}

function Val({ children, color = "#E8E8EC", size = 13 }) {
  return <span style={{ fontSize: size, color, fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600 }}>{children}</span>;
}

function Divider() {
  return <div style={{ height: 1, background: "#1C1E24", margin: "10px 0" }} />;
}

function ScoreMeter({ value }) {
  const color = value >= 80 ? "#F5A623" : value >= 60 ? "#C8851A" : "#5C4A1E";
  const r = 36, stroke = 5;
  const circ = 2 * Math.PI * r;
  const filled = (value / 100) * circ;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={86} height={86} viewBox="0 0 86 86">
        <circle cx={43} cy={43} r={r} fill="none" stroke="#1C1E24" strokeWidth={stroke} />
        <circle cx={43} cy={43} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeDashoffset={circ / 4}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 1s ease" }}
        />
        <text x={43} y={47} textAnchor="middle" fill={color}
          style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700 }}>{value}</text>
      </svg>
      <Label color={color}>TREND SCORE</Label>
    </div>
  );
}

function PhaseTimeline({ steps }) {
  return (
    <div style={{ display: "flex", gap: 0, alignItems: "stretch", width: "100%" }}>
      {steps.map((s, i) => (
        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{
            height: 4,
            background: s.done ? (s.type === "IMP" ? "#F5A623" : "#3A6BFF") : "#1C1E24",
            borderRadius: i === 0 ? "2px 0 0 2px" : i === steps.length - 1 ? "0 2px 2px 0" : 0,
            transition: "background 0.4s",
          }} />
          <Label color={s.done ? (s.type === "IMP" ? "#F5A623" : "#6B8FFF") : "#2A2D36"}>
            {s.label}
          </Label>
        </div>
      ))}
    </div>
  );
}

function AnnotationRow({ a, active, onHover }) {
  return (
    <div
      onMouseEnter={() => onHover(a.label)}
      onMouseLeave={() => onHover(null)}
      style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "7px 10px",
        background: active ? "rgba(245,166,35,0.05)" : "transparent",
        borderLeft: `2px solid ${active ? a.color : "transparent"}`,
        cursor: "pointer",
        transition: "all 0.2s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ width: 6, height: 6, borderRadius: 1, background: a.color }} />
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: active ? a.color : "#6B6F7A" }}>{a.label}</span>
      </div>
      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#3A3D48" }}>{a.price.toFixed(2)}</span>
    </div>
  );
}

function StatRow({ label, value, valueColor }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0" }}>
      <Label>{label}</Label>
      <Val color={valueColor || "#C8C8D0"} size={11}>{value}</Val>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function ChronosMarketView() {
  const [activeAnnotation, setActiveAnnotation] = useState(null);
  const [activeTab, setActiveTab] = useState("ANALYSIS");
  const [tf, setTf] = useState("H4");

  const TIMEFRAMES = ["MN", "W1", "D1", "H4", "H1", "M15"];
  const ALIGNED_TF = ["W1", "D1", "H4"];

  const TREND_STEPS = [
    { label: "IMP 1", type: "IMP", done: true },
    { label: "RET 1", type: "RET", done: true },
    { label: "IMP 2", type: "IMP", done: true },
    { label: "RET 2", type: "RET", done: true },
    { label: "IMP 3", type: "IMP", done: false },
  ];

  const TABS = ["ANALYSIS", "STRUCTURE", "HISTORY"];

  return (
    <div style={{ background: "#0D0F14", minHeight: "100vh", fontFamily: "'IBM Plex Mono', monospace", color: "#E8E8EC", display: "flex", flexDirection: "column" }}>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Syne:wght@700;800&display=swap" rel="stylesheet" />

      {/* Header */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 24px", borderBottom: "1px solid #1C1E24", background: "#0A0C10" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button style={{ background: "none", border: "1px solid #1C1E24", color: "#4A4D58", fontSize: 10, padding: "5px 10px", cursor: "pointer", borderRadius: 2, fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.06em" }}>← SCANNER</button>
          <div style={{ width: 1, height: 18, background: "#1C1E24" }} />
          <div>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 18, color: "#F5A623", letterSpacing: "0.04em" }}>XAUUSD</span>
            <span style={{ fontSize: 10, color: "#3A3D48", marginLeft: 10 }}>Gold / US Dollar</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 8 }}>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 700, color: "#E8E8EC" }}>2341.50</span>
            <span style={{ fontSize: 11, color: "#4CAF7D" }}>+1.24%</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {TIMEFRAMES.map(t => (
            <button key={t} onClick={() => setTf(t)} style={{
              padding: "5px 10px", fontSize: 10,
              background: tf === t ? (ALIGNED_TF.includes(t) ? "#F5A623" : "#1C1E24") : "transparent",
              color: tf === t ? (ALIGNED_TF.includes(t) ? "#0D0F14" : "#E8E8EC") : ALIGNED_TF.includes(t) ? "#C8851A" : "#3A3D48",
              border: `1px solid ${tf === t ? (ALIGNED_TF.includes(t) ? "#F5A623" : "#2A2D36") : ALIGNED_TF.includes(t) ? "#C8851A44" : "#1C1E24"}`,
              borderRadius: 2, cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace", letterSpacing: "0.06em",
            }}>{t}</button>
          ))}
          <div style={{ width: 1, height: 18, background: "#1C1E24" }} />
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#4CAF7D", boxShadow: "0 0 6px #4CAF7D" }} />
            <span style={{ fontSize: 9, color: "#3A3D48" }}>LIVE</span>
          </div>
        </div>
      </header>

      {/* Body */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Chart Area */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", borderRight: "1px solid #1C1E24", overflow: "hidden" }}>

          {/* Chart */}
          <div style={{ flex: 1, background: "#0D0F14", padding: "12px 8px 8px 8px", minHeight: 0, position: "relative" }}>
            {/* TradingView badge */}
            <div style={{ position: "absolute", top: 14, right: 14, fontSize: 9, color: "#2A2D36", zIndex: 2 }}>
              TRADINGVIEW CHART · CHRONOS OVERLAY
            </div>
            <CandleChart
              candles={CANDLES}
              annotations={ANNOTATIONS}
              impulseZones={IMPULSE_ZONES}
              retracementZones={RETRACEMENT_ZONES}
              activeAnnotation={activeAnnotation}
              onAnnotationHover={setActiveAnnotation}
            />
          </div>

          {/* Trend Phase Timeline */}
          <div style={{ padding: "14px 20px", borderTop: "1px solid #1C1E24", background: "#0A0C10" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <Label color="#4A4D58">TREND PHASE PROGRESSION</Label>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                  <div style={{ width: 10, height: 3, background: "#F5A623", borderRadius: 1 }} />
                  <Label color="#F5A623">IMPULSE</Label>
                </div>
                <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                  <div style={{ width: 10, height: 3, background: "#3A6BFF", borderRadius: 1 }} />
                  <Label color="#6B8FFF">RETRACEMENT</Label>
                </div>
              </div>
            </div>
            <PhaseTimeline steps={TREND_STEPS} />
            <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Label color="#2A2D36">CURRENT PHASE: AWAITING IMP 3 · ENTRY ZONE ACTIVE</Label>
              <div style={{
                padding: "4px 10px",
                background: "rgba(245,166,35,0.1)",
                border: "1px solid rgba(245,166,35,0.3)",
                borderRadius: 2,
                fontSize: 9, color: "#F5A623", letterSpacing: "0.1em",
              }}>⬆ LONG BIAS</div>
            </div>
          </div>
        </div>

        {/* Right Panel */}
        <div style={{ width: 280, display: "flex", flexDirection: "column", background: "#0A0C10", overflow: "hidden" }}>

          {/* Score */}
          <div style={{ padding: "20px 18px 14px", borderBottom: "1px solid #1C1E24", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <ScoreMeter value={94} />
            <div style={{ flex: 1, paddingLeft: 16 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div>
                  <Label>DIRECTION</Label>
                  <div style={{ marginTop: 3 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#F5A623", letterSpacing: "0.06em" }}>LONG ↑</span>
                  </div>
                </div>
                <Divider />
                <div>
                  <Label>MTF ALIGNMENT</Label>
                  <div style={{ display: "flex", gap: 4, marginTop: 5 }}>
                    {["W1","D1","H4"].map(t => (
                      <span key={t} style={{ fontSize: 9, padding: "2px 6px", background: "rgba(245,166,35,0.12)", border: "1px solid rgba(245,166,35,0.3)", borderRadius: 2, color: "#F5A623" }}>{t}</span>
                    ))}
                  </div>
                </div>
                <Divider />
                <div>
                  <Label>CONVICTION</Label>
                  <div style={{ marginTop: 3 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#F5A623" }}>HIGH</span>
                    <span style={{ fontSize: 9, color: "#3A3D48", marginLeft: 6 }}>3 / 3 TF</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div style={{ display: "flex", borderBottom: "1px solid #1C1E24" }}>
            {TABS.map(t => (
              <button key={t} onClick={() => setActiveTab(t)} style={{
                flex: 1, padding: "9px 4px",
                fontSize: 9, letterSpacing: "0.1em",
                background: "transparent",
                color: activeTab === t ? "#F5A623" : "#3A3D48",
                border: "none",
                borderBottom: `2px solid ${activeTab === t ? "#F5A623" : "transparent"}`,
                cursor: "pointer",
                fontFamily: "'IBM Plex Mono', monospace",
              }}>{t}</button>
            ))}
          </div>

          {/* Tab Content */}
          <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px" }}>

            {activeTab === "ANALYSIS" && (
              <div>
                <Label color="#4A4D58">MARKET STATS</Label>
                <div style={{ marginTop: 8 }}>
                  <StatRow label="CURRENT PRICE" value="2341.50" valueColor="#E8E8EC" />
                  <StatRow label="SESSION CHANGE" value="+1.24%" valueColor="#4CAF7D" />
                  <StatRow label="SESSION HIGH" value="2347.80" />
                  <StatRow label="SESSION LOW" value="2318.40" />
                  <StatRow label="ATR (14)" value="18.42" />
                </div>
                <Divider />
                <Label color="#4A4D58">TREND METRICS</Label>
                <div style={{ marginTop: 8 }}>
                  <StatRow label="TREND AGE" value="14 BARS" />
                  <StatRow label="IMPULSE COUNT" value="2 COMPLETE" valueColor="#F5A623" />
                  <StatRow label="RET DEPTH AVG" value="38.2%" />
                  <StatRow label="NEXT TARGET" value="2368.00" valueColor="#F5A623" />
                  <StatRow label="INVALIDATION" value="2291.00" valueColor="#E05A5A" />
                </div>
                <Divider />
                <Label color="#4A4D58">ENTRY ZONE</Label>
                <div style={{ marginTop: 8, padding: "10px", background: "rgba(245,166,35,0.05)", border: "1px solid rgba(245,166,35,0.15)", borderRadius: 2 }}>
                  <StatRow label="ZONE TOP" value="2338.00" valueColor="#F5A623" />
                  <StatRow label="ZONE BOT" value="2324.00" valueColor="#F5A623" />
                  <div style={{ marginTop: 8 }}>
                    <Label color="#F5A623">RETRACEMENT ENTRY ACTIVE</Label>
                  </div>
                </div>
              </div>
            )}

            {activeTab === "STRUCTURE" && (
              <div>
                <Label color="#4A4D58">STRUCTURAL ANNOTATIONS</Label>
                <div style={{ marginTop: 8 }}>
                  {ANNOTATIONS.map(a => (
                    <AnnotationRow
                      key={a.label}
                      a={a}
                      active={activeAnnotation === a.label}
                      onHover={setActiveAnnotation}
                    />
                  ))}
                </div>
                <Divider />
                <Label color="#4A4D58">ZONES</Label>
                <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                  {IMPULSE_ZONES.map(z => (
                    <div key={z.label} style={{ display: "flex", justifyContent: "space-between", padding: "6px 8px", background: "rgba(245,166,35,0.04)", border: "1px solid rgba(245,166,35,0.12)", borderRadius: 2 }}>
                      <Label color="#C8851A">{z.label}</Label>
                      <Label color="#3A3D48">{z.yBot.toFixed(0)} — {z.yTop.toFixed(0)}</Label>
                    </div>
                  ))}
                  {RETRACEMENT_ZONES.map(z => (
                    <div key={z.label} style={{ display: "flex", justifyContent: "space-between", padding: "6px 8px", background: "rgba(60,80,180,0.04)", border: "1px solid rgba(60,80,180,0.12)", borderRadius: 2 }}>
                      <Label color="#6B8FFF">{z.label}</Label>
                      <Label color="#3A3D48">{z.yBot.toFixed(0)} — {z.yTop.toFixed(0)}</Label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activeTab === "HISTORY" && (
              <div>
                <Label color="#4A4D58">SCAN HISTORY</Label>
                <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 1 }}>
                  {[
                    { time: "08:00", score: 94, note: "IMP 3 setup forming" },
                    { time: "04:00", score: 89, note: "RET 2 confirmed" },
                    { time: "00:00", score: 81, note: "IMP 2 break confirmed" },
                    { time: "20:00", score: 74, note: "BOS detected" },
                    { time: "16:00", score: 61, note: "CHoCH signal" },
                  ].map((h, i) => (
                    <div key={i} style={{ display: "flex", gap: 10, padding: "8px 6px", borderBottom: "1px solid #111318", alignItems: "flex-start" }}>
                      <Label color="#2A2D36">{h.time}</Label>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 10, color: "#6B6F7A" }}>{h.note}</div>
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 700, color: h.score >= 80 ? "#F5A623" : "#6B6F7A" }}>{h.score}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Footer Action */}
          <div style={{ padding: "12px 14px", borderTop: "1px solid #1C1E24" }}>
            <button style={{
              width: "100%", padding: "10px",
              background: "rgba(245,166,35,0.1)",
              border: "1px solid rgba(245,166,35,0.35)",
              color: "#F5A623", fontSize: 10, fontWeight: 700,
              letterSpacing: "0.12em", cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace", borderRadius: 2,
            }}>OPEN TRADE SETUP →</button>
          </div>
        </div>
      </div>

      {/* Status Bar */}
      <div style={{ borderTop: "1px solid #1C1E24", padding: "8px 24px", display: "flex", justifyContent: "space-between", background: "#0A0C10" }}>
        <Label color="#2A2D36">CHRONOS-AI · XAUUSD · H4 · SWING TREND ENGINE</Label>
        <Label color="#2A2D36">BOS / CHoCH / IMPULSE / RETRACEMENT · NOT FINANCIAL ADVICE</Label>
      </div>
    </div>
  );
}
