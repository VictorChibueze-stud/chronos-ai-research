import { ScoreRing } from "@/components/score-ring";

interface RightSidebarProps {
  score: number;
  direction: "LONG" | "SHORT";
  mtfAlignment: string[];
  conviction: { level: string; aligned: number; total: number };
  activeTab: "ANALYSIS" | "STRUCTURE" | "HISTORY";
  onTabChange: (tab: "ANALYSIS" | "STRUCTURE" | "HISTORY") => void;
  children: React.ReactNode;
}

export function RightSidebar({
  score,
  direction,
  mtfAlignment,
  conviction,
  activeTab,
  onTabChange,
  children,
}: RightSidebarProps) {
  return (
    <aside className="w-80 flex flex-col overflow-hidden bg-[#1E222D]">
      {/* Score & Direction Section */}
      <div className="p-5 border-b border-[#2A2E39]" style={{ background: "#0A0C10" }}>
        <div style={{ display: "flex", gap: 16 }}>
          {/* Score Ring */}
          <div>
            <ScoreRing score={score} size={86} />
          </div>

          {/* Direction & Alignment Info */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
            {/* Direction */}
            <div>
              <label
                style={{
                  fontSize: 9,
                  color: "#3A3D48",
                  letterSpacing: "0.12em",
                  fontFamily: '"IBM Plex Mono", monospace',
                  textTransform: "uppercase",
                }}
              >
                DIRECTION
              </label>
              <div style={{ marginTop: 3 }}>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: direction === "LONG" ? "#F5A623" : "#E05A5A",
                    letterSpacing: "0.06em",
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  {direction} {direction === "LONG" ? "↑" : "↓"}
                </span>
              </div>
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: "#1C1E24", margin: "4px 0" }} />

            {/* MTF Alignment */}
            <div>
              <label
                style={{
                  fontSize: 9,
                  color: "#3A3D48",
                  letterSpacing: "0.12em",
                  fontFamily: '"IBM Plex Mono", monospace',
                  textTransform: "uppercase",
                }}
              >
                MTF ALIGNMENT
              </label>
              <div style={{ display: "flex", gap: 4, marginTop: 5 }}>
                {mtfAlignment.map((tf) => (
                  <span
                    key={tf}
                    style={{
                      fontSize: 9,
                      padding: "2px 6px",
                      background: "rgba(245,166,35,0.12)",
                      border: "1px solid rgba(245,166,35,0.3)",
                      borderRadius: 2,
                      color: "#F5A623",
                      fontFamily: '"IBM Plex Mono", monospace',
                    }}
                  >
                    {tf}
                  </span>
                ))}
              </div>
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: "#1C1E24", margin: "4px 0" }} />

            {/* Conviction */}
            <div>
              <label
                style={{
                  fontSize: 9,
                  color: "#3A3D48",
                  letterSpacing: "0.12em",
                  fontFamily: '"IBM Plex Mono", monospace',
                  textTransform: "uppercase",
                }}
              >
                CONVICTION
              </label>
              <div style={{ marginTop: 3 }}>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: "#F5A623",
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  {conviction.level}
                </span>
                <span
                  style={{
                    fontSize: 9,
                    color: "#3A3D48",
                    marginLeft: 6,
                    fontFamily: '"IBM Plex Mono", monospace',
                  }}
                >
                  {conviction.aligned} / {conviction.total} TF
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="grid grid-cols-3 border-b border-[#2A2E39]">
        {["ANALYSIS", "STRUCTURE", "HISTORY"].map((tab) => (
          <button
            key={tab}
            onClick={() => onTabChange(tab as "ANALYSIS" | "STRUCTURE" | "HISTORY")}
            className="h-9 text-[9px] uppercase tracking-[0.1em] border-b"
            style={{
              color: activeTab === tab ? "#F5A623" : "#787B86",
              borderBottomColor: activeTab === tab ? "#F5A623" : "transparent",
              fontFamily: '"IBM Plex Mono", monospace',
              fontWeight: activeTab === tab ? 600 : 400,
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-4">{children}</div>

      {/* Footer Action */}
      <div className="p-3 border-t border-[#1C1E24]" style={{ background: "#0A0C10" }}>
        <button
          style={{
            width: "100%",
            padding: "10px",
            background: "rgba(245,166,35,0.1)",
            border: "1px solid rgba(245,166,35,0.35)",
            color: "#F5A623",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            cursor: "pointer",
            fontFamily: '"IBM Plex Mono", monospace',
            borderRadius: 2,
          }}
        >
          OPEN TRADE SETUP →
        </button>
      </div>
    </aside>
  );
}
