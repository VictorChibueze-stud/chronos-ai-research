"use client";

import { useEffect, useState, type CSSProperties } from "react";

import { UniverseDashboard } from "@/components/universe-dashboard";
import { api } from "@/lib/api";
import type { Setup, UniverseStats } from "@/lib/types";

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

export default function UniversePage() {
  const [setups, setSetups] = useState<Setup[]>([]);
  const [stats, setStats] = useState<UniverseStats>(EMPTY_STATS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadUniverse() {
      setLoading(true);
      setError(null);

      try {
        const [setupsData, statsData] = await Promise.all([
          api.getSetupsAll(),
          api.getUniverseStats(),
        ]);

        if (cancelled) {
          return;
        }

        setSetups(Array.isArray(setupsData) ? setupsData : []);
        setStats(statsData || EMPTY_STATS);
      } catch (err) {
        if (!cancelled) {
          console.error("Error loading universe stats:", err);
          setSetups([]);
          setStats(EMPTY_STATS);
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

  if (loading) {
    return <div style={CENTERED_STATUS_STYLE}>LOADING UNIVERSE DATA...</div>;
  }

  if (error) {
    return <div style={{ ...CENTERED_STATUS_STYLE, color: "#E05A5A" }}>DATA UNAVAILABLE</div>;
  }

  return <UniverseDashboard setups={setups} stats={stats} />;
}