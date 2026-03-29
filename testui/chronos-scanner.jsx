import { useState, useEffect } from "react";

const MARKETS = [
  { id: 1, symbol: "XAUUSD", name: "Gold / USD", category: "Commodities", phase: "IMPULSE", direction: "LONG", score: 94, tf: ["W1", "D1", "H4"], bos: true, choch: false, step: 4, totalSteps: 5, change: "+1.24%", price: "2341.50", strength: 0.94 },
  { id: 2, symbol: "EURUSD", name: "Euro / USD", category: "Forex", phase: "RETRACEMENT", direction: "LONG", score: 81, tf: ["D1", "H4", "H1"], bos: true, choch: false, step: 3, totalSteps: 5, change: "+0.38%", price: "1.08742", strength: 0.81 },
  { id: 3, symbol: "GBPJPY", name: "GBP / JPY", category: "Forex", phase: "IMPULSE", direction: "SHORT", score: 77, tf: ["W1", "D1"], bos: false, choch: true, step: 2, totalSteps: 5, change: "-0.62%", price: "191.344", strength: 0.77 },
  { id: 4, symbol: "BTCUSD", name: "Bitcoin / USD", category: "Crypto", phase: "IMPULSE", direction: "LONG", score: 72, tf: ["D1", "H4"], bos: true, choch: false, step: 3, totalSteps: 5, change: "+2.11%", price: "68,420.00", strength: 0.72 },
  { id: 5, symbol: "USOIL", name: "US Crude Oil", category: "Commodities", phase: "RETRACEMENT", direction: "SHORT", score: 68, tf: ["W1", "D1", "H4"], bos: false, choch: true, step: 4, totalSteps: 5, change: "-0.87%", price: "82.14", strength: 0.68 },
  { id: 6, symbol: "NAS100", name: "Nasdaq 100", category: "Indices", phase: "IMPULSE", direction: "LONG", score: 61, tf: ["D1"], bos: true, choch: false, step: 2, totalSteps: 5, change: "+0.54%", price: "18,231.0", strength: 0.61 },
  { id: 7, symbol: "USDJPY", name: "USD / JPY", category: "Forex", phase: "RETRACEMENT", direction: "SHORT", score: 54, tf: ["H4", "H1"], bos: false, choch: false, step: 1, totalSteps: 5, change: "-0.19%", price: "151.882", strength: 0.54 },
  { id: 8, symbol: "ETHUSD", name: "Ethereum / USD", category: "Crypto", phase: "IMPULSE", direction: "LONG", score: 49, tf: ["D1"], bos: true, choch: false, step: 2, totalSteps: 5, change: "+1.03%", price: "3,481.20", strength: 0.49 },
];

const CATEGORIES = ["All", "Forex", "Commodities", "Crypto", "Indices"];

function ScoreBar({ value }) {
  const color = value >= 80 ? "#F5A623" : value >= 60 ? "#C8851A" : "#5C4A1E";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 80, height: 3, background: "#1C1E24", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${value}%`, height: "100%", background: color, transition: "width 0.6s ease" }} />
      </div>
      <span style={{
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 13,
        fontWeight: 700,
        color: value >= 80 ? "#F5A623" : value >= 60 ? "#C8851A" : "#6B6F7A",
        minWidth: 28,
      }}>{value}</span>
    </div>
  );
}

function PhaseSteps({ step, total, direction }) {
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} style={{
          width: 8, height: 8,
          borderRadius: 1,
          background: i < step
            ? direction === "LONG" ? "#F5A623" : "#E05A5A"
            : "#1C1E24",
          border: `1px solid ${i < step ? "transparent" : "#2A2D36"}`,
        }} />
      ))}
    </div>
  );
}

function TFBadge({ label }) {
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10,
      padding: "2px 5px",
      border: "1px solid #2A2D36",
      borderRadius: 2,
      color: "#6B6F7A",
      letterSpacing: "0.05em",
    }}>{label}</span>
  );
}

function DirectionTag({ direction }) {
  const isLong = direction === "LONG";
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10,
      fontWeight: 700,
      padding: "3px 7px",
      borderRadius: 2,
      background: isLong ? "rgba(245,166,35,0.1)" : "rgba(224,90,90,0.1)",
      color: isLong ? "#F5A623" : "#E05A5A",
      border: `1px solid ${isLong ? "rgba(245,166,35,0.25)" : "rgba(224,90,90,0.25)"}`,
      letterSpacing: "0.08em",
    }}>{direction}</span>
  );
}

function PhaseBadge({ phase }) {
  const isImpulse = phase === "IMPULSE";
  return (
    <span style={{
      fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10,
      padding: "3px 7px",
      borderRadius: 2,
      background: isImpulse ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
      color: isImpulse ? "#C8C8D0" : "#6B6F7A",
      border: "1px solid #2A2D36",
      letterSpacing: "0.06em",
    }}>{phase}</span>
  );
}

function StatCard({ label, value, sub, highlight }) {
  return (
    <div style={{
      flex: 1,
      padding: "14px 18px",
      background: "#111318",
      border: "1px solid #1C1E24",
      borderTop: highlight ? "2px solid #F5A623" : "1px solid #1C1E24",
    }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#4A4D58", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, color: highlight ? "#F5A623" : "#E8E8EC", lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#4A4D58", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default function ChronosScanner() {
  const [selected, setSelected] = useState(null);
  const [category, setCategory] = useState("All");
  const [sortBy, setSortBy] = useState("score");
  const [pulse, setPulse] = useState(null);
  const [scanTime, setScanTime] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => {
      setScanTime(new Date());
      const randomId = MARKETS[Math.floor(Math.random() * MARKETS.length)].id;
      setPulse(randomId);
      setTimeout(() => setPulse(null), 600);
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  const filtered = MARKETS
    .filter(m => category === "All" || m.category === category)
    .sort((a, b) => sortBy === "score" ? b.score - a.score : a.symbol.localeCompare(b.symbol));

  const highScore = MARKETS.filter(m => m.score >= 75).length;
  const impulseCount = MARKETS.filter(m => m.phase === "IMPULSE").length;

  return (
    <div style={{
      background: "#0D0F14",
      minHeight: "100vh",
      fontFamily: "'IBM Plex Mono', monospace",
      color: "#E8E8EC",
      display: "flex",
      flexDirection: "column",
    }}>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Syne:wght@700;800&display=swap" rel="stylesheet" />

      {/* Header */}
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 28px",
        borderBottom: "1px solid #1C1E24",
        background: "#0A0C10",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 6, height: 24, background: "#F5A623" }} />
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, color: "#F5A623", letterSpacing: "0.04em" }}>CHRONOS</span>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 20, color: "#3A3D48", letterSpacing: "0.04em" }}>AI</span>
          </div>
          <div style={{ width: 1, height: 20, background: "#1C1E24" }} />
          <span style={{ fontSize: 10, color: "#3A3D48", letterSpacing: "0.1em" }}>MARKET SCANNER</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#4CAF7D", boxShadow: "0 0 6px #4CAF7D" }} />
            <span style={{ fontSize: 10, color: "#4A4D58", letterSpacing: "0.08em" }}>LIVE</span>
          </div>
          <span style={{ fontSize: 10, color: "#2A2D36" }}>
            {scanTime.toUTCString().slice(17, 25)} UTC
          </span>
          <div style={{
            padding: "6px 14px",
            border: "1px solid #2A2D36",
            borderRadius: 2,
            fontSize: 10,
            color: "#6B6F7A",
            cursor: "pointer",
            letterSpacing: "0.06em",
          }}>SCAN ALL</div>
          <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#1C1E24", border: "1px solid #2A2D36", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 11, color: "#6B6F7A" }}>V</span>
          </div>
        </div>
      </header>

      {/* Stat Row */}
      <div style={{ display: "flex", gap: 1, padding: "1px 28px 0", background: "#080A0E" }}>
        <StatCard label="Active Trends" value={MARKETS.length} sub="across all markets" highlight />
        <StatCard label="High Conviction" value={highScore} sub="score ≥ 75" />
        <StatCard label="In Impulse" value={impulseCount} sub="trending now" />
        <StatCard label="In Retracement" value={MARKETS.length - impulseCount} sub="entry zones" />
        <StatCard label="Last Scan" value={scanTime.toUTCString().slice(17, 22)} sub="UTC refresh" />
      </div>

      {/* Controls */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 28px",
        borderBottom: "1px solid #1C1E24",
        gap: 12,
      }}>
        <div style={{ display: "flex", gap: 2 }}>
          {CATEGORIES.map(cat => (
            <button key={cat} onClick={() => setCategory(cat)} style={{
              padding: "5px 12px",
              fontSize: 10,
              letterSpacing: "0.08em",
              background: category === cat ? "#F5A623" : "transparent",
              color: category === cat ? "#0D0F14" : "#4A4D58",
              border: `1px solid ${category === cat ? "#F5A623" : "#1C1E24"}`,
              borderRadius: 2,
              cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
              fontWeight: category === cat ? 700 : 400,
            }}>{cat}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
          <span style={{ fontSize: 10, color: "#3A3D48", marginRight: 4 }}>SORT</span>
          {["score", "symbol"].map(s => (
            <button key={s} onClick={() => setSortBy(s)} style={{
              padding: "5px 10px",
              fontSize: 10,
              background: sortBy === s ? "#1C1E24" : "transparent",
              color: sortBy === s ? "#C8C8D0" : "#3A3D48",
              border: "1px solid #1C1E24",
              borderRadius: 2,
              cursor: "pointer",
              fontFamily: "'IBM Plex Mono', monospace",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}>{s}</button>
          ))}
        </div>
      </div>

      {/* Table Header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "200px 100px 120px 140px 130px 120px 1fr",
        padding: "8px 28px",
        borderBottom: "1px solid #1C1E24",
        gap: 0,
      }}>
        {["MARKET", "DIRECTION", "PHASE", "TREND SCORE", "PROGRESS", "TIMEFRAMES", "PRICE / CHG"].map((h, i) => (
          <span key={h} style={{ fontSize: 9, color: "#2A2D36", letterSpacing: "0.14em" }}>{h}</span>
        ))}
      </div>

      {/* Rows */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filtered.map((m) => {
          const isSelected = selected === m.id;
          const isPulsing = pulse === m.id;
          return (
            <div
              key={m.id}
              onClick={() => setSelected(isSelected ? null : m.id)}
              style={{
                display: "grid",
                gridTemplateColumns: "200px 100px 120px 140px 130px 120px 1fr",
                padding: "14px 28px",
                borderBottom: "1px solid #111318",
                cursor: "pointer",
                background: isSelected
                  ? "rgba(245,166,35,0.04)"
                  : isPulsing
                  ? "rgba(245,166,35,0.06)"
                  : "transparent",
                borderLeft: isSelected ? "2px solid #F5A623" : "2px solid transparent",
                transition: "background 0.3s ease, border-color 0.2s",
                alignItems: "center",
                gap: 0,
              }}
            >
              {/* Market */}
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#E8E8EC", letterSpacing: "0.04em" }}>{m.symbol}</div>
                <div style={{ fontSize: 10, color: "#3A3D48", marginTop: 2 }}>{m.name}</div>
              </div>

              {/* Direction */}
              <div><DirectionTag direction={m.direction} /></div>

              {/* Phase */}
              <div><PhaseBadge phase={m.phase} /></div>

              {/* Score */}
              <div><ScoreBar value={m.score} /></div>

              {/* Steps */}
              <div>
                <PhaseSteps step={m.step} total={m.totalSteps} direction={m.direction} />
                <div style={{ fontSize: 9, color: "#3A3D48", marginTop: 4 }}>STEP {m.step} OF {m.totalSteps}</div>
              </div>

              {/* TF */}
              <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                {m.tf.map(t => <TFBadge key={t} label={t} />)}
              </div>

              {/* Price */}
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: "#E8E8EC" }}>{m.price}</div>
                <div style={{
                  fontSize: 10,
                  color: m.change.startsWith("+") ? "#4CAF7D" : "#E05A5A",
                  marginTop: 2,
                }}>{m.change}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{
        borderTop: "1px solid #1C1E24",
        padding: "10px 28px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        background: "#0A0C10",
      }}>
        <span style={{ fontSize: 9, color: "#2A2D36", letterSpacing: "0.1em" }}>
          CHRONOS-AI v0.4.2 · SWING TREND ENGINE · NOT FINANCIAL ADVICE
        </span>
        <span style={{ fontSize: 9, color: "#2A2D36", letterSpacing: "0.08em" }}>
          {filtered.length} MARKETS · BOS/CHoCH · MULTI-TF ALIGNMENT
        </span>
      </div>
    </div>
  );
}
