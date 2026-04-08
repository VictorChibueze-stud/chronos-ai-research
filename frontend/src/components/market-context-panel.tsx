"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "@/lib/api";
import type {
  FundamentalEventsResponse,
  FundamentalNewsResponse,
} from "@/lib/types";

interface MarketContextPanelProps {
  symbol: string;
}

function timeAgo(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatEventDate(isoString: string): string {
  const d = new Date(isoString);
  const day = d.getUTCDate().toString().padStart(2, "0");
  const month = d
    .toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    .toUpperCase();
  const time = `${d.getUTCHours().toString().padStart(2, "0")}:${d
    .getUTCMinutes()
    .toString()
    .padStart(2, "0")}`;
  return `${day} ${month}  ${time} UTC`;
}

const MONO: CSSProperties = {
  fontFamily: '"IBM Plex Mono", monospace',
  fontSize: 10,
  letterSpacing: "0.06em",
};

const SUBLABEL: CSSProperties = {
  ...MONO,
  fontSize: 9,
  color: "#434651",
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  marginBottom: 8,
};

// Match panelRowLabel from market-cockpit.tsx
const ROW_LABEL: CSSProperties = {
  fontSize: 9,
  color: "#787B86",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  fontFamily: '"IBM Plex Mono", monospace',
};

function impactColor(level: string): string {
  if (level === "high") return "#EF5350";
  if (level === "medium") return "#F5A623";
  return "#787B86";
}

function sentimentArrow(label: string): { glyph: string; color: string } {
  if (label === "positive") return { glyph: "↑", color: "#26A69A" };
  if (label === "negative") return { glyph: "↓", color: "#EF5350" };
  return { glyph: "→", color: "#F5A623" };
}

export function MarketContextPanel({ symbol }: MarketContextPanelProps) {
  const [eventsData, setEventsData] =
    useState<FundamentalEventsResponse | null>(null);
  const [newsData, setNewsData] = useState<FundamentalNewsResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    Promise.all([
      api.getFundamentalEvents(symbol).catch(() => null),
      api.getFundamentalNews(symbol).catch(() => null),
    ]).then(([events, news]) => {
      setEventsData(events);
      setNewsData(news);
      setLoading(false);
    });
  }, [symbol]);

  if (loading) {
    return (
      <div style={{ ...MONO, color: "#434651", padding: "4px 0" }}>
        LOADING...
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* EVENT SHIELD */}
      <div>
        <div style={SUBLABEL}>Event Shield</div>
        {eventsData?.blackout_active ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "#EF5350", fontSize: 11 }}>⚠</span>
              <span style={{ ...MONO, color: "#EF5350", fontWeight: 600, fontSize: 9, letterSpacing: "0.1em" }}>
                BLACKOUT ACTIVE
              </span>
            </div>
            <div style={{ ...ROW_LABEL, paddingLeft: 17, fontSize: 9, color: "#787B86", lineHeight: 1.5 }}>
              {eventsData.blackout_reason}
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "#26A69A", fontSize: 9 }}>●</span>
            <span style={{ ...MONO, color: "#26A69A", fontSize: 9, letterSpacing: "0.1em" }}>
              TRADING CLEAR
            </span>
          </div>
        )}
      </div>

      {/* UPCOMING EVENTS */}
      <div>
        <div style={SUBLABEL}>Upcoming Events</div>
        {!eventsData?.next_events?.length ? (
          <div style={ROW_LABEL}>NO EVENTS SCHEDULED</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {eventsData.next_events.map((event, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  paddingBottom: 6,
                  borderBottom: i < eventsData.next_events.length - 1
                    ? "1px solid #1C1F26"
                    : "none",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ ...ROW_LABEL, color: "#D1D4DC", fontSize: 9 }}>
                    {formatEventDate(event.scheduled_at)}
                  </span>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <span
                      style={{
                        ...ROW_LABEL,
                        fontSize: 8,
                        color: impactColor(event.impact_level),
                      }}
                    >
                      {event.impact_level.toUpperCase().slice(0, 3)}
                    </span>
                    {event.rank !== null && (
                      <span style={{ ...ROW_LABEL, fontSize: 8, color: "#434651" }}>
                        · R{event.rank}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ ...ROW_LABEL, color: "#787B86", fontSize: 9 }}>
                  {event.name}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* NEWS CONTEXT */}
      <div>
        <div style={SUBLABEL}>News Context</div>
        {!newsData?.articles?.length ? (
          <div style={ROW_LABEL}>NO RECENT NEWS</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {newsData.articles.map((article, i) => {
              const { glyph, color } = sentimentArrow(article.sentiment_label);
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 6,
                    alignItems: "flex-start",
                    paddingBottom: 6,
                    borderBottom: i < newsData.articles.length - 1
                      ? "1px solid #1C1F26"
                      : "none",
                  }}
                >
                  <span
                    style={{ color, fontSize: 10, flexShrink: 0, marginTop: 1 }}
                  >
                    {glyph}
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        ...MONO,
                        color: "#D1D4DC",
                        fontSize: 9,
                        textDecoration: "none",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        display: "block",
                      }}
                      title={article.headline}
                    >
                      {article.headline}
                    </a>
                    <div style={{ display: "flex", gap: 6 }}>
                      <span style={{ ...ROW_LABEL, fontSize: 8 }}>
                        {article.source_name}
                      </span>
                      <span style={{ ...ROW_LABEL, fontSize: 8 }}>
                        {timeAgo(article.published_at)}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

    </div>
  );
}
