import { useState, useEffect, useRef } from "react";

const ASSET_CLASSES = ["Forex", "Commodities", "Indices", "Crypto", "Synthetic"];
const MARKETS = {
  Forex: ["EURUSD","GBPJPY","USDJPY","GBPUSD","AUDUSD"],
  Commodities: ["XAUUSD","XAGUSD","USOIL","NGAS"],
  Indices: ["NAS100","SPX500","GER40","UK100"],
  Crypto: ["BTCUSD","ETHUSD","SOLUSD"],
  Synthetic: ["V75","V100","BOOM1000","CRASH500"],
};
const ENTRY_TYPES = ["BOS", "CHoCH", "RETRACEMENT", "TRUE BREAK"];
const PHASES = ["IMPULSE", "RETRACEMENT"];

function generateTrades(n = 60) {
  const trades = [];
  let equity = 10000;
  for (let i = 0; i < n; i++) {
    const cls = ASSET_CLASSES[Math.floor(Math.random() * ASSET_CLASSES.length)];
    const mkt = MARKETS[cls][Math.floor(Math.random() * MARKETS[cls].length)];
    const score = 45 + Math.floor(Math.random() * 52);
    const rr = +(1.2 + Math.random() * 2.8).toFixed(2);
    const win = Math.random() < (score > 70 ? 0.62 : 0.44);
    const r = win ? rr : -1;
    const pnl = +(r * 100).toFixed(0);
    equity += pnl;
    const daysAgo = n - i;
    const date = new Date(); date.setDate(date.getDate() - daysAgo);
    trades.push({
      id: i + 1, market: mkt, category: cls,
      direction: Math.random() > 0.5 ? "LONG" : "SHORT",
      entryType: ENTRY_TYPES[Math.floor(Math.random() * ENTRY_TYPES.length)],
      phase: PHASES[Math.floor(Math.random() * PHASES.length)],
      score, rr, win, r: +r.toFixed(2), pnl,
      equity: +equity.toFixed(0),
      date: date.toISOString().slice(0, 10),
      tf: ["W1","D1","H4"][Math.floor(Math.random() * 3)],
    });
  }
  return trades;
}

const TRADES = generateTrades(60);

function pct(n, d) { return d === 0 ? 0 : Math.round((n / d) * 100); }
function avg(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0; }
function fmt(n, decimals = 2) { return (n >= 0 ? "+" : "") + n.toFixed(decimals); }

function Label({ children, color = "#3A3D48" }) {
  return <span style={{ fontSize: 9, color, letterSpacing: "0.12em", fontFamily: "'IBM Plex Mono', monospace" }}>{children}</span>;
}
function Divider() { return <div style={{ height: 1, background: "#1C1E24", margin: "10px 0" }} />; }

function EquityCurve({ trades }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const PAD = { top: 16, right: 16, bottom: 24, left: 56 };
    ctx.clearRect(0, 0, W, H);
    const points = [{ y: 10000 }, ...trades.map(t => ({ y: t.equity }))];
    const minY = Math.min(...points.map(p => p.y)) - 200;
    const maxY = Math.max(...points.map(p => p.y)) + 200;
    const chartW = W - PAD.left - PAD.right;
    const chartH = H - PAD.top - PAD.bottom;
    const toX = (i) => PAD.left + (i / (points.length - 1)) * chartW;
    const toY = (v) => PAD.top + chartH - ((v - minY) / (maxY - minY)) * chartH;
    for (let i = 0; i <= 4; i++) {
      const v = minY + ((maxY - minY) / 4) * i;
      const y = toY(v);
      ctx.strokeStyle = "#1C1E24"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
      ctx.fillStyle = "#3A3D48"; ctx.font = "9px IBM Plex Mono";
      ctx.fillText("$" + Math.round(v / 1000) + "k", 2, y + 3);
    }
    const baseY = toY(10000);
    ctx.strokeStyle = "#2A2D36"; ctx.lineWidth = 1; ctx.setLineDash([3, 5]);
    ctx.beginPath(); ctx.moveTo(PAD.left, baseY); ctx.lineTo(W - PAD.right, baseY); ctx.stroke();
    ctx.setLineDash([]);
    const grad = ctx.createLinearGradient(0, PAD.top, 0, H - PAD.bottom);
    grad.addColorStop(0, "rgba(245,166,35,0.18)");
    grad.addColorStop(1, "rgba(245,166,35,0)");
    ctx.beginPath();
    points.forEach((p, i) => i === 0 ? ctx.moveTo(toX(i), toY(p.y)) : ctx.lineTo(toX(i), toY(p.y)));
    ctx.lineTo(toX(points.length - 1), H - PAD.bottom);
    ctx.lineTo(toX(0), H - PAD.bottom);
    ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    points.forEach((p, i) => i === 0 ? ctx.moveTo(toX(i), toY(p.y)) : ctx.lineTo(toX(i), toY(p.y)));
    ctx.strokeStyle = "#F5A623"; ctx.lineWidth = 1.5; ctx.stroke();
    let peak = points[0].y;
    for (let i = 1; i < points.length; i++) {
      if (points[i].y >= peak) { peak = points[i].y; continue; }
      ctx.fillStyle = "rgba(224,90,90,0.07)";
      ctx.fillRect(toX(i - 1), toY(peak), toX(i) - toX(i - 1), toY(points[i].y) - toY(peak));
    }
  }, [trades]);
  return <canvas ref={canvasRef} width={780} height={160} style={{ width: "100%", height: "100%", display: "block" }} />;
}

function RingMetric({ value, label, color = "#F5A623", size = 72 }) {
  const r = size / 2 - 6, stroke = 5;
  const circ = 2 * Math.PI * r;
  const filled = (Math.min(value, 100) / 100) * circ;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1C1E24" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeDashoffset={circ / 4} strokeLinecap="round" />
        <text x={size/2} y={size/2 + 5} textAnchor="middle" fill={color}
          style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: size * 0.22, fontWeight: 700 }}>
          {value}%
        </text>
      </svg>
      <Label color={color}>{label}</Label>
    </div>
  );
}

function CategoryBars({ trades }) {
  const byClass = {};
  ASSET_CLASSES.forEach(c => { byClass[c] = { wins: 0, total: 0, r: 0 }; });
  trades.forEach(t => {
    byClass[t.category].total++;
    if (t.win) byClass[t.category].wins++;
    byClass[t.category].r += t.r;
  });
  const maxR = Math.max(...Object.values(byClass).map(v => Math.abs(v.r)), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {ASSET_CLASSES.map(cls => {
        const d = byClass[cls];
        if (!d.total) return null;
        const wr = pct(d.wins, d.total);
        const totalR = +d.r.toFixed(2);
        const barW = (Math.abs(totalR) / maxR) * 100;
        const positive = totalR >= 0;
        return (
          <div key={cls}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#C8C8D0", minWidth: 100 }}>{cls.toUpperCase()}</span>
                <Label>{d.total} TRADES · {wr}% WR</Label>
              </div>
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: positive ? "#F5A623" : "#E05A5A", fontWeight: 700 }}>{fmt(totalR, 1)}R</span>
            </div>
            <div style={{ height: 4, background: "#1C1E24", borderRadius: 2 }}>
              <div style={{ width: `${barW}%`, height: "100%", background: positive ? "#F5A623" : "#E05A5A", borderRadius: 2, transition: "width 0.8s" }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ScoreBuckets({ trades }) {
  const buckets = [
    { label: "45–59", min: 45, max: 59, color: "#3A3D48" },
    { label: "60–74", min: 60, max: 74, color: "#C8851A" },
    { label: "75–89", min: 75, max: 89, color: "#F5A623" },
    { label: "90+",   min: 90, max: 100, color: "#FFD166" },
  ];
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {buckets.map(b => {
        const bt = trades.filter(t => t.score >= b.min && t.score <= b.max);
        const wr = pct(bt.filter(t => t.win).length, bt.length);
        const totalR = +bt.reduce((s, t) => s + t.r, 0).toFixed(1);
        return (
          <div key={b.label} style={{ flex: 1, padding: "12px 10px", background: "#111318", border: `1px solid ${b.color}22`, borderTop: `2px solid ${b.color}` }}>
            <Label color={b.color}>SCORE {b.label}</Label>
            <div style={{ marginTop: 8, fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, color: b.color, lineHeight: 1 }}>{wr}%</div>
            <div style={{ marginTop: 2 }}><Label>WIN RATE</Label></div>
            <div style={{ marginTop: 8, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: totalR >= 0 ? "#4CAF7D" : "#E05A5A" }}>{fmt(totalR, 1)}R</div>
            <Label color="#2A2D36">{bt.length} TRADES</Label>
          </div>
        );
      })}
    </div>
  );
}

function TradeLog({ trades }) {
  const cols = "60px 90px 80px 70px 100px 55px 55px 60px 70px";
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: cols, padding: "7px 0", borderBottom: "1px solid #1C1E24" }}>
        {["DATE","MARKET","CLASS","DIR","ENTRY","TF","SCORE","RR","RESULT"].map(h => <Label key={h} color="#2A2D36">{h}</Label>)}
      </div>
      <div style={{ maxHeight: 240, overflowY: "auto" }}>
        {[...trades].reverse().map(t => (
          <div key={t.id} style={{ display: "grid", gridTemplateColumns: cols, padding: "8px 0", borderBottom: "1px solid #111318", alignItems: "center" }}>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#3A3D48" }}>{t.date.slice(5)}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#C8C8D0", fontWeight: 600 }}>{t.market}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#4A4D58" }}>{t.category.toUpperCase()}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: t.direction === "LONG" ? "#F5A623" : "#E05A5A", fontWeight: 700 }}>{t.direction}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#4A4D58" }}>{t.entryType}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#3A3D48" }}>{t.tf}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: t.score >= 80 ? "#F5A623" : t.score >= 65 ? "#C8851A" : "#4A4D58" }}>{t.score}</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#6B6F7A" }}>{t.rr}R</span>
            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 700, color: t.win ? "#4CAF7D" : "#E05A5A" }}>{t.win ? "+" : ""}{t.r}R</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ChronosAnalytics() {
  const [filter, setFilter] = useState("ALL");
  const [tab, setTab] = useState("OVERVIEW");

  const filtered = filter === "ALL" ? TRADES : TRADES.filter(t => t.category === filter);
  const wins = filtered.filter(t => t.win);
  const losses = filtered.filter(t => !t.win);
  const winRate = pct(wins.length, filtered.length);
  const totalR = +filtered.reduce((s, t) => s + t.r, 0).toFixed(2);
  const avgRR = +avg(filtered.map(t => t.rr)).toFixed(2);
  const expectancy = +(winRate / 100 * avgRR - (1 - winRate / 100) * 1).toFixed(2);
  const equities = [10000, ...filtered.map(t => t.equity)];
  const peak = Math.max(...equities);
  const currentEq = equities[equities.length - 1];
  const maxDD = +((peak - Math.min(...equities)) / peak * 100).toFixed(1);
  const currentDD = +((peak - currentEq) / peak * 100).toFixed(1);
  const winR = wins.reduce((s, t) => s + t.r, 0);
  const lossR = Math.abs(losses.reduce((s, t) => s + t.r, 0));
  const profitFactor = lossR === 0 ? 99 : +(winR / lossR).toFixed(2);

  const FILTERS = ["ALL", ...ASSET_CLASSES];
  const TABS = ["OVERVIEW", "BY SCORE", "BY CLASS", "TRADE LOG"];

  const kpis = [
    { label: "TOTAL TRADES", value: filtered.length, color: "#E8E8EC" },
    { label: "WIN RATE", value: winRate + "%", color: "#F5A623", highlight: true },
    { label: "TOTAL R", value: fmt(totalR, 1) + "R", color: totalR >= 0 ? "#4CAF7D" : "#E05A5A" },
    { label: "AVG R:R", value: "1:" + avgRR, color: "#E8E8EC" },
    { label: "EXPECTANCY", value: fmt(expectancy, 2) + "R", color: expectancy >= 0 ? "#F5A623" : "#E05A5A" },
    { label: "PROFIT FACTOR", value: profitFactor + "x", color: profitFactor >= 1.5 ? "#4CAF7D" : "#E05A5A" },
    { label: "MAX DRAWDOWN", value: maxDD + "%", color: maxDD > 20 ? "#E05A5A" : "#C8851A" },
    { label: "CURRENT DD", value: currentDD + "%", color: currentDD > 10 ? "#E05A5A" : "#4CAF7D" },
  ];

  return (
    <div style={{ background: "#0D0F14", minHeight: "100vh", fontFamily: "'IBM Plex Mono', monospace", color: "#E8E8EC", display: "flex", flexDirection: "column" }}>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Syne:wght@700;800&display=swap" rel="stylesheet" />

      {/* Header */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 28px", borderBottom: "1px solid #1C1E24", background: "#0A0C10" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 6, height: 24, background: "#F5A623" }} />
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, color: "#F5A623", letterSpacing: "0.04em" }}>CHRONOS</span>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 20, color: "#3A3D48", letterSpacing: "0.04em" }}>AI</span>
          </div>
          <div style={{ width: 1, height: 20, background: "#1C1E24" }} />
          <span style={{ fontSize: 10, color: "#3A3D48", letterSpacing: "0.1em" }}>TRADE ANALYTICS</span>
        </div>
        <div style={{ display: "flex", gap: 2 }}>
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              padding: "5px 10px", fontSize: 9, letterSpacing: "0.08em",
              background: filter === f ? "#F5A623" : "transparent",
              color: filter === f ? "#0D0F14" : "#4A4D58",
              border: `1px solid ${filter === f ? "#F5A623" : "#1C1E24"}`,
              borderRadius: 2, cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace", fontWeight: filter === f ? 700 : 400,
            }}>{f}</button>
          ))}
        </div>
      </header>

      {/* KPI Strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(8,1fr)", gap: 1, background: "#080A0E", padding: "1px 28px 0" }}>
        {kpis.map((k, i) => (
          <div key={k.label} style={{ padding: "14px 16px", background: "#111318", borderTop: k.highlight ? "2px solid #F5A623" : "1px solid #111318" }}>
            <Label>{k.label}</Label>
            <div style={{ marginTop: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 700, color: k.color, lineHeight: 1 }}>{k.value}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #1C1E24", padding: "0 28px", background: "#0A0C10" }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: "10px 18px", fontSize: 9, letterSpacing: "0.1em",
            background: "transparent",
            color: tab === t ? "#F5A623" : "#3A3D48",
            border: "none", borderBottom: `2px solid ${tab === t ? "#F5A623" : "transparent"}`,
            cursor: "pointer", fontFamily: "'IBM Plex Mono', monospace",
          }}>{t}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, padding: "20px 28px", overflowY: "auto" }}>

        {tab === "OVERVIEW" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Equity Curve */}
            <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <Label color="#4A4D58">EQUITY CURVE · {filtered.length} TRADES · STARTING $10,000</Label>
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <div style={{ width: 20, height: 2, background: "#F5A623" }} />
                    <Label color="#F5A623">EQUITY</Label>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <div style={{ width: 12, height: 12, background: "rgba(224,90,90,0.15)", border: "1px solid rgba(224,90,90,0.3)" }} />
                    <Label color="#E05A5A88">DRAWDOWN PERIODS</Label>
                  </div>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, color: currentEq >= 10000 ? "#4CAF7D" : "#E05A5A", fontWeight: 700 }}>${currentEq.toLocaleString()}</span>
                </div>
              </div>
              <div style={{ height: 160 }}><EquityCurve trades={filtered} /></div>
            </div>

            {/* Win/Loss stats + Entry types */}
            <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 12 }}>
              <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "16px", display: "flex", flexDirection: "column", gap: 14 }}>
                <Label color="#4A4D58">PERFORMANCE SUMMARY</Label>
                <div style={{ display: "flex", justifyContent: "space-around", paddingTop: 4 }}>
                  <RingMetric value={winRate} label="WIN RATE" color="#F5A623" />
                  <RingMetric value={Math.min(100, Math.round(profitFactor * 35))} label="PROF FACTOR" color="#4CAF7D" size={72} />
                </div>
                <Divider />
                {[
                  { label: "WINS / LOSSES", value: `${wins.length} / ${losses.length}`, color: "#C8C8D0" },
                  { label: "AVG WIN", value: "+" + avg(wins.map(t => t.r)).toFixed(2) + "R", color: "#4CAF7D" },
                  { label: "AVG LOSS", value: avg(losses.map(t => t.r)).toFixed(2) + "R", color: "#E05A5A" },
                  { label: "LARGEST WIN", value: "+" + Math.max(...wins.map(t => t.r)).toFixed(2) + "R", color: "#F5A623" },
                  { label: "LARGEST LOSS", value: Math.min(...losses.map(t => t.r)).toFixed(2) + "R", color: "#E05A5A" },
                  { label: "EXPECTANCY", value: fmt(expectancy, 3) + "R / TRADE", color: expectancy >= 0 ? "#F5A623" : "#E05A5A" },
                ].map(s => (
                  <div key={s.label} style={{ display: "flex", justifyContent: "space-between" }}>
                    <Label>{s.label}</Label>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: s.color, fontWeight: 600 }}>{s.value}</span>
                  </div>
                ))}
              </div>

              <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "16px", display: "flex", flexDirection: "column", gap: 14 }}>
                <Label color="#4A4D58">ENTRY TYPE PERFORMANCE</Label>
                {ENTRY_TYPES.map(et => {
                  const et2 = filtered.filter(t => t.entryType === et);
                  if (!et2.length) return null;
                  const eWR = pct(et2.filter(t => t.win).length, et2.length);
                  const eR = +et2.reduce((s, t) => s + t.r, 0).toFixed(1);
                  return (
                    <div key={et}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                        <div style={{ display: "flex", gap: 12 }}>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#C8C8D0", minWidth: 110 }}>{et}</span>
                          <Label>{et2.length} TRADES</Label>
                        </div>
                        <div style={{ display: "flex", gap: 14 }}>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: eWR >= 55 ? "#F5A623" : "#6B6F7A" }}>{eWR}% WR</span>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 700, color: eR >= 0 ? "#4CAF7D" : "#E05A5A" }}>{fmt(eR, 1)}R</span>
                        </div>
                      </div>
                      <div style={{ height: 3, background: "#1C1E24", borderRadius: 2 }}>
                        <div style={{ width: `${eWR}%`, height: "100%", background: eWR >= 55 ? "#F5A623" : "#3A3D48", borderRadius: 2, transition: "width 0.8s" }} />
                      </div>
                    </div>
                  );
                })}
                <Divider />
                <Label color="#4A4D58">ENTRY PHASE</Label>
                <div style={{ display: "flex", gap: 8 }}>
                  {PHASES.map(ph => {
                    const pt = filtered.filter(t => t.phase === ph);
                    const pWR = pct(pt.filter(t => t.win).length, pt.length);
                    const pR = +pt.reduce((s, t) => s + t.r, 0).toFixed(1);
                    const c = ph === "IMPULSE" ? "#F5A623" : "#6B8FFF";
                    return (
                      <div key={ph} style={{ flex: 1, padding: "10px", background: "#0D0F14", border: "1px solid #1C1E24" }}>
                        <Label color={c}>{ph}</Label>
                        <div style={{ marginTop: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700, color: c, lineHeight: 1 }}>{pWR}%</div>
                        <div style={{ marginTop: 2 }}><Label>WIN RATE</Label></div>
                        <div style={{ marginTop: 6, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: pR >= 0 ? "#4CAF7D" : "#E05A5A" }}>{fmt(pR, 1)}R</div>
                        <Label color="#2A2D36">{pt.length} TRADES</Label>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === "BY SCORE" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "18px" }}>
              <Label color="#4A4D58">WIN RATE BY TREND SCORE BUCKET — IS THE SCORE PREDICTIVE?</Label>
              <div style={{ marginTop: 16 }}><ScoreBuckets trades={filtered} /></div>
            </div>
            <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "18px" }}>
              <div style={{ marginBottom: 12 }}><Label color="#4A4D58">SCORE vs RESULT — EACH SQUARE IS ONE TRADE · OPACITY = SCORE STRENGTH</Label></div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {filtered.map(t => (
                  <div key={t.id} title={`${t.market} · Score ${t.score} · ${t.r}R`} style={{
                    width: 11, height: 11, borderRadius: 2,
                    background: t.win ? "#F5A623" : "#E05A5A",
                    opacity: 0.3 + (t.score / 100) * 0.7,
                    cursor: "default",
                  }} />
                ))}
              </div>
              <div style={{ marginTop: 10, display: "flex", gap: 16 }}>
                <div style={{ display: "flex", gap: 5, alignItems: "center" }}><div style={{ width: 11, height: 11, background: "#F5A623", borderRadius: 2 }} /><Label color="#F5A623">WIN</Label></div>
                <div style={{ display: "flex", gap: 5, alignItems: "center" }}><div style={{ width: 11, height: 11, background: "#E05A5A", borderRadius: 2 }} /><Label color="#E05A5A">LOSS</Label></div>
              </div>
            </div>
          </div>
        )}

        {tab === "BY CLASS" && (
          <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "20px" }}>
            <div style={{ marginBottom: 16 }}><Label color="#4A4D58">TOTAL R AND WIN RATE BY ASSET CLASS</Label></div>
            <CategoryBars trades={filtered} />
          </div>
        )}

        {tab === "TRADE LOG" && (
          <div style={{ background: "#111318", border: "1px solid #1C1E24", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <Label color="#4A4D58">FULL TRADE LOG · {filtered.length} RECORDS</Label>
              <Label color="#2A2D36">MOST RECENT FIRST</Label>
            </div>
            <TradeLog trades={filtered} />
          </div>
        )}
      </div>

      <div style={{ borderTop: "1px solid #1C1E24", padding: "8px 28px", display: "flex", justifyContent: "space-between", background: "#0A0C10" }}>
        <Label color="#2A2D36">CHRONOS-AI · TRADE ANALYTICS · SWING STRATEGY ENGINE</Label>
        <Label color="#2A2D36">SIMULATED DATA · CONNECTS TO LIVE TRADE RECORDS ON BACKEND</Label>
      </div>
    </div>
  );
}
