"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { UniverseDashboard } from "@/components/universe-dashboard";
import { FullBleedPageSkeleton } from "@/components/ui/page-skeleton";
import { api } from "@/lib/api";
import type { ScanJobLog, Setup, UniverseStats } from "@/lib/types";

const CENTERED_STATUS_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: "100%",
  background: "#0D0F14",
  color: "#F5A623",
  fontFamily: '"IBM Plex Mono", monospace',
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const EMPTY_STATS: UniverseStats = {
  total_monitored: 0,
  by_category: {},
  by_phase: { impulse: 0, retracement: 0, range: 0 },
  by_depth: { depth_1: 0, depth_2: 0, depth_3: 0 },
};

function getLatestUniverseRankingCompletedAt(logs: ScanJobLog[] | null | undefined): string | null {
  if (!logs?.length) return null;
  const finished = logs.filter(
    (j) => j.job_type === "universe_ranking" && j.completed_at != null && j.status !== "running",
  );
  finished.sort((a, b) => {
    const ta = new Date(a.completed_at as string).getTime();
    const tb = new Date(b.completed_at as string).getTime();
    return tb - ta;
  });
  const job = finished[0];
  if (!job?.completed_at) return null;
  const d = new Date(job.completed_at);
  return Number.isFinite(d.getTime()) ? job.completed_at : null;
}

export default function UniversePage() {
  const [setups, setSetups] = useState<Setup[]>([]);
  const [stats, setStats] = useState<UniverseStats>(EMPTY_STATS);
  const [lastRankedIso, setLastRankedIso] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadUniverse() {
      setLoading(true);
      setError(null);

      try {
        const [setupsData, statsData, jobLogs] = await Promise.all([
          api.getSetupsUniverse(),
          api.getUniverseStats(),
          api.getScanJobLog().catch(() => [] as ScanJobLog[]),
        ]);

        if (cancelled) {
          return;
        }

        setSetups(Array.isArray(setupsData) ? setupsData : []);
        setStats(statsData || EMPTY_STATS);
        setLastRankedIso(getLatestUniverseRankingCompletedAt(Array.isArray(jobLogs) ? jobLogs : null));
      } catch (err) {
        if (!cancelled) {
          console.error("Error loading universe stats:", err);
          setSetups([]);
          setStats(EMPTY_STATS);
          setLastRankedIso(null);
          setError("DATA UNAVAILABLE");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadUniverse();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSetupMerged = useCallback((next: Setup) => {
    const sym = String(next.symbol || "").toUpperCase();
    setSetups((prev) =>
      prev.map((s) => (String(s.symbol || "").toUpperCase() === sym ? next : s)),
    );
  }, []);

  if (loading) {
    return (
      <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
        <FullBleedPageSkeleton label="Loading universe" />
      </div>
    );
  }

  if (error) {
    return <div style={{ ...CENTERED_STATUS_STYLE, color: "#E05A5A" }}>DATA UNAVAILABLE</div>;
  }

  return (
    <UniverseDashboard
      setups={setups}
      stats={stats}
      onSetupMerged={handleSetupMerged}
      lastRankedIso={lastRankedIso}
    />
  );
}