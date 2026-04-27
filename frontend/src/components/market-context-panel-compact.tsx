"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  FundamentalEventsResponse,
  FundamentalNewsResponse,
} from "@/lib/types";

interface CompactFundamentalsPanelProps {
  symbol: string;
}

function timeUntil(isoString: string): string {
  const now = Date.now();
  const target = new Date(isoString).getTime();
  const diff = target - now;
  if (diff <= 0) return "now";
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  if (h > 48) {
    const d = Math.floor(h / 24);
    return `${d}d`;
  }
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function impactColor(level: string): string {
  if (level === "high") return "var(--bear)";
  if (level === "medium") return "var(--amber)";
  return "var(--text-muted)";
}

export function MarketContextPanelCompact({ symbol }: CompactFundamentalsPanelProps) {
  const [eventsData, setEventsData] = useState<FundamentalEventsResponse | null>(null);
  const [newsData, setNewsData] = useState<FundamentalNewsResponse | null>(null);
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
      <div
        style={{
          padding: "8px 0",
          fontFamily: "var(--font-sans)",
          fontSize: 9,
          color: "var(--text-muted)",
        }}
      >
        Loading fundamentals…
      </div>
    );
  }

  const isBlackout = eventsData?.blackout_active ?? false;
  const blackoutReason = eventsData?.blackout_reason ?? null;
  const nextEvents = eventsData?.next_events ?? [];
  const nextEvent =
    nextEvents.find((e) => e.impact_level === "high") ?? nextEvents[0] ?? null;
  const vetoActive = newsData?.critical_veto_flag ?? false;
  const topStory = newsData?.stories?.[0] ?? null;

  const hasAnyData = isBlackout || nextEvent || vetoActive || topStory;

  if (!hasAnyData) {
    return (
      <div
        style={{
          padding: "8px 0",
          fontFamily: "var(--font-sans)",
          fontSize: 9,
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border-subtle)",
          marginTop: 8,
        }}
      >
        No fundamental data available
      </div>
    );
  }

  return (
    <div
      style={{
        borderTop: "1px solid var(--border-subtle)",
        marginTop: 10,
        paddingTop: 10,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {/* Section label */}
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 8,
          fontWeight: 600,
          color: "var(--text-muted)",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        Macro Context
      </div>

      {/* Blackout or clear status */}
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <span style={{ fontSize: 7, color: isBlackout ? "var(--bear)" : "var(--bull)" }}>
          ●
        </span>
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 9,
            color: isBlackout ? "var(--bear)" : "var(--bull)",
            fontWeight: 500,
          }}
        >
          {isBlackout ? "TRADING BLOCKED" : "TRADING CLEAR"}
        </span>
      </div>

      {/* Blackout reason if active */}
      {isBlackout && blackoutReason && (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 9,
            color: "var(--text-muted)",
            lineHeight: 1.4,
            paddingLeft: 12,
          }}
        >
          {blackoutReason}
        </div>
      )}

      {/* LLM veto badge */}
      {vetoActive && (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "2px 7px",
            border: "1px solid var(--bear)",
            borderRadius: 3,
            background: "transparent",
            width: "fit-content",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 8,
              fontWeight: 600,
              color: "var(--bear)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            ⚠ MACRO VETO ACTIVE
          </span>
        </div>
      )}

      {/* Next high-impact event */}
      {nextEvent && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span
            style={{
              fontSize: 7,
              color: impactColor(nextEvent.impact_level),
              flexShrink: 0,
            }}
          >
            ■
          </span>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 9,
              color: "var(--text-secondary)",
              flex: 1,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {nextEvent.name}
          </span>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 8,
              color: "var(--text-muted)",
              flexShrink: 0,
            }}
          >
            {timeUntil(nextEvent.scheduled_at)}
          </span>
        </div>
      )}

      {/* Top story cluster — title + actors */}
      {topStory && (
        <div
          style={{
            borderLeft: "2px solid var(--border-default)",
            paddingLeft: 8,
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 9,
              fontWeight: 600,
              color: "var(--text-secondary)",
              lineHeight: 1.3,
            }}
          >
            {topStory.story_title}
          </div>
          {topStory.actors?.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
              {topStory.actors.slice(0, 3).map((actor, i) => (
                <span
                  key={i}
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 7,
                    padding: "1px 4px",
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    borderRadius: 2,
                    color: "var(--text-dim)",
                  }}
                >
                  {actor.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
