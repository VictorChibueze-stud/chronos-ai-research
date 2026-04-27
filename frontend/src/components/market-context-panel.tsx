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
  color: "var(--text-dim)",
  textTransform: "uppercase",
  letterSpacing: "0.1em",
  marginBottom: 8,
};

// Match panelRowLabel from market-cockpit.tsx
const ROW_LABEL: CSSProperties = {
  fontSize: 9,
  color: "var(--text-dim)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  fontFamily: '"IBM Plex Mono", monospace',
};

function impactColor(level: string): string {
  if (level === "high") return "#EF5350";
  if (level === "medium") return "#F5A623";
  return "var(--text-dim)";
}

function sentimentColor(s: string): string {
  if (s === "Strongly Bullish") return "#26A69A";
  if (s === "Mildly Bullish") return "#4CAF80";
  if (s === "Strongly Bearish") return "#EF5350";
  if (s === "Mildly Bearish") return "#FF7043";
  return "var(--text-dim)"; // Neutral / unknown
}

function sentimentGlyph(s: string): string {
  if (s.includes("Bullish")) return "▲";
  if (s.includes("Bearish")) return "▼";
  return "●";
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
      <div style={{ ...MONO, color: "var(--text-dim)", padding: "4px 0" }}>
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
            <div style={{ ...ROW_LABEL, paddingLeft: 17, fontSize: 9, color: "var(--text-dim)", lineHeight: 1.5 }}>
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
                  <span style={{ ...ROW_LABEL, color: "var(--text-primary)", fontSize: 9 }}>
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
                      <span style={{ ...ROW_LABEL, fontSize: 8, color: "var(--text-dim)" }}>
                        · R{event.rank}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ ...ROW_LABEL, color: "var(--text-dim)", fontSize: 9 }}>
                  {event.name}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* NEWS CONTEXT — LLM story clusters */}
      <div>
        <div style={SUBLABEL}>News Context</div>

        {/* VETO BANNER */}
        {newsData?.critical_veto_flag && (
          <div
            style={{
              padding: "8px 10px",
              background: "#EF535015",
              border: "1px solid #EF535040",
              borderRadius: 4,
              marginBottom: 8,
            }}
          >
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 9,
                color: "#EF5350",
                letterSpacing: "0.1em",
                marginBottom: 2,
              }}
            >
              ⚠ TRADE ENTRIES BLOCKED
            </div>
            <div
              style={{
                fontSize: 9,
                color: "var(--text-secondary)",
                lineHeight: 1.4,
              }}
            >
              {newsData.veto_reason || "Critical macro event detected"}
            </div>
          </div>
        )}

        {/* RISK SUMMARY */}
        {newsData?.risk_summary && (
          <div
            style={{
              padding: "6px 8px",
              background: "var(--border-subtle)",
              borderRadius: 4,
              marginBottom: 8,
              fontSize: 9,
              color: "var(--text-secondary)",
              lineHeight: 1.5,
            }}
          >
            {newsData.risk_summary}
          </div>
        )}

        {/* STORY CLUSTERS */}
        {(newsData?.stories?.length ?? 0) > 0 && (
          <div>
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 8,
                color: "var(--text-muted)",
                letterSpacing: "0.1em",
                marginBottom: 6,
                textTransform: "uppercase",
              }}
            >
              News Stories
              {newsData?.analyzed_at
                ? ` · analyzed ${timeAgo(newsData.analyzed_at)}`
                : ""}
            </div>
            {newsData!.stories.map((story) => (
              <div
                key={story.story_id}
                style={{
                  marginBottom: 10,
                  borderLeft: "2px solid var(--border-subtle)",
                  paddingLeft: 8,
                }}
              >
                {/* Story header */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    marginBottom: 3,
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      color: "var(--text-primary)",
                      flex: 1,
                    }}
                  >
                    {story.story_title}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      color: sentimentColor(story.overall_sentiment),
                      fontFamily: "'IBM Plex Mono', monospace",
                    }}
                  >
                    {sentimentGlyph(story.overall_sentiment)}{" "}
                    {story.overall_sentiment}
                  </span>
                </div>

                {/* Summary */}
                <div
                  style={{
                    fontSize: 9,
                    color: "var(--text-dim)",
                    lineHeight: 1.5,
                    marginBottom: 4,
                  }}
                >
                  {story.summary}
                </div>

                {/* Actors */}
                {(story.actors?.length ?? 0) > 0 && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 4,
                      marginBottom: 4,
                    }}
                  >
                    {story.actors.map((actor, ai) => (
                      <span
                        key={ai}
                        style={{
                          fontSize: 8,
                          padding: "1px 5px",
                          background: "var(--border-subtle)",
                          border: "1px solid var(--border-default)",
                          borderRadius: 10,
                          color: sentimentColor(actor.sentiment),
                          fontFamily: "'IBM Plex Mono', monospace",
                        }}
                      >
                        {actor.name}
                      </span>
                    ))}
                  </div>
                )}

                {/* Timeline of articles */}
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  {story.timeline?.slice(0, 4).map((article, ti) => (
                    <a
                      key={ti}
                      href={article.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 5,
                        textDecoration: "none",
                      }}
                    >
                      <span
                        style={{
                          fontSize: 8,
                          color: sentimentColor(article.sentiment),
                          flexShrink: 0,
                        }}
                      >
                        {sentimentGlyph(article.sentiment)}
                      </span>
                      <span
                        style={{
                          fontSize: 8,
                          color: "var(--text-secondary)",
                          flex: 1,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {article.headline}
                      </span>
                      <span
                        style={{
                          fontSize: 7,
                          color: "var(--text-muted)",
                          flexShrink: 0,
                          fontFamily: "'IBM Plex Mono', monospace",
                        }}
                      >
                        {article.source}
                        {article.popularity_count > 1
                          ? ` +${article.popularity_count - 1}`
                          : ""}
                      </span>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* LLM UPCOMING EVENTS (from news payload, complements the top-level list) */}
        {(newsData?.upcoming_events?.length ?? 0) > 0 && (
          <div style={{ marginTop: 8 }}>
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 8,
                color: "var(--text-muted)",
                letterSpacing: "0.1em",
                marginBottom: 4,
                textTransform: "uppercase",
              }}
            >
              Upcoming Events
            </div>
            {newsData!.upcoming_events.slice(0, 5).map((event, ei) => (
              <div
                key={ei}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "3px 0",
                  borderBottom: "1px solid var(--border-subtle)20",
                }}
              >
                <span
                  style={{
                    fontSize: 8,
                    color: impactColor(event.impact_level),
                    flexShrink: 0,
                  }}
                >
                  ●
                </span>
                <span
                  style={{
                    fontSize: 8,
                    color: "var(--text-secondary)",
                    flex: 1,
                  }}
                >
                  {event.event_name}
                </span>
                <span
                  style={{
                    fontSize: 7,
                    color: "var(--text-dim)",
                    fontFamily: "'IBM Plex Mono', monospace",
                    flexShrink: 0,
                  }}
                >
                  {new Date(event.scheduled_at).toLocaleDateString("en-GB", {
                    day: "2-digit",
                    month: "short",
                  })}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* NO DATA FALLBACK */}
        {!newsData?.stories?.length &&
          !newsData?.upcoming_events?.length &&
          !newsData?.articles?.length && (
            <div
              style={{
                fontSize: 9,
                color: "var(--text-muted)",
                fontFamily: "'IBM Plex Mono', monospace",
              }}
            >
              NO FUNDAMENTAL DATA
            </div>
          )}

        {/* RAW-ARTICLE FALLBACK (pre-LLM window) */}
        {newsData?.mode === "raw_articles" &&
          (newsData.articles?.length ?? 0) > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {newsData.articles!.map((article, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 5,
                    alignItems: "center",
                  }}
                >
                  <span
                    style={{
                      fontSize: 8,
                      color: "var(--text-dim)",
                      flexShrink: 0,
                    }}
                  >
                    ●
                  </span>
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      ...MONO,
                      color: "var(--text-secondary)",
                      fontSize: 9,
                      textDecoration: "none",
                      flex: 1,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={article.headline}
                  >
                    {article.headline}
                  </a>
                  <span style={{ ...ROW_LABEL, fontSize: 8, flexShrink: 0 }}>
                    {timeAgo(article.published_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
      </div>

    </div>
  );
}

