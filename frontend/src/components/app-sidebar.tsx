"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart2,
  Cable,
  Globe,
  Lock,
  PieChart,
  Radar,
  Shield,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { IkengaLogomark } from "@/components/ikenga-logomark";
import { RelativeTimeWithTooltip } from "@/components/ui/relative-time";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { formatLocaleInt } from "@/lib/format-display";
import type { HealthResponse, UniverseRankingStatus } from "@/lib/types";

interface ScanStatus {
  in_progress: boolean;
  stage: string | null;
  stage1_complete: number;
  stage2_complete: number;
  stage2_total: number;
}

function analysisJobsActive(
  health: HealthResponse | null,
  ranking: UniverseRankingStatus | null,
): boolean {
  if (!health && !ranking) return false;
  return Boolean(
    health?.scan_in_progress ||
      ranking?.in_progress ||
      ranking?.global_structure_in_progress ||
      ranking?.prime_impulse_in_progress ||
      ranking?.walker_in_progress,
  );
}

/** Priority: global structure → prime impulse → walker → active refresh scan → universe ranking. */
function analysisStatusMessage(
  health: HealthResponse | null,
  ranking: UniverseRankingStatus | null,
  scanStatus: ScanStatus | null,
): string | null {
  if (!health && !ranking) return null;
  if (ranking?.global_structure_in_progress) return "COMPUTING GLOBAL STRUCTURE...";
  if (ranking?.prime_impulse_in_progress) return "COMPUTING PRIME IMPULSE...";
  if (ranking?.walker_in_progress) return "COMPUTING DEPTH ANALYSIS...";
  if (health?.scan_in_progress) {
    const stageUniverse = scanStatus?.stage
      ? scanStatus.stage.includes("multi_asset")
        ? " · MULTI-ASSET"
        : scanStatus.stage.includes("synthetic")
        ? " · SYNTHETIC"
        : scanStatus.stage.includes("crypto")
        ? " · CRYPTO"
        : ""
      : "";
    return "SCANNING MARKETS" + stageUniverse + "...";
  }
  if (ranking?.in_progress) return "RANKING UNIVERSE...";
  return null;
}

const PRIMARY_NAV = [
  { label: "SCANNER", href: "/scanner", icon: Radar },
  { label: "SIGNAL BOARD", href: "/signals", icon: Activity },
  { label: "TRADES", href: "/trades", icon: TrendingUp },
  { label: "MARKET VIEW", href: "/market", icon: BarChart2 },
  { label: "UNIVERSE", href: "/universe", icon: Globe },
] satisfies { label: string; href: string; icon: LucideIcon }[];

const SECONDARY_NAV = [
  { label: "INTEGRATIONS", href: "/settings/integrations", icon: Cable },
  { label: "ANALYTICS", href: "/analytics", icon: PieChart },
  { label: "RISK", href: "/risk", icon: Shield },
] satisfies { label: string; href?: string; icon: LucideIcon }[];

function formatCountdown(msUntil: number): string {
  if (msUntil <= 0) return "00:00";
  const totalSecs = Math.floor(msUntil / 1000);
  const hours = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;
  if (hours > 0) {
    return `${hours}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

interface AppSidebarProps {
  collapsed?: boolean;
  onToggle?: () => void;
  toggleIcon?: ReactNode;
}

export function AppSidebar({ collapsed = false, onToggle, toggleIcon }: AppSidebarProps) {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [killswitchActive, setKillswitchActive] = useState(false);
  const [countdown, setCountdown] = useState<string>("--:--");
  const [analysisSnapshot, setAnalysisSnapshot] = useState<{
    health: HealthResponse;
    ranking: UniverseRankingStatus;
  } | null>(null);

  // Health polling every 30 seconds
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const data = await api.getHealth();
        setHealth(data);
        setKillswitchActive(data.killswitch_active ?? false);
      } catch {
        // silent fail — keep last known state
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 30_000);
    return () => clearInterval(interval);
  }, []);

  // Scan status polling every 5 seconds
  useEffect(() => {
    const fetchScanStatus = async () => {
      try {
        const data = await api.getScanStatus();
        setScanStatus(data);
      } catch {
        // silent fail
      }
    };
    fetchScanStatus();
    const interval = setInterval(fetchScanStatus, 5_000);
    return () => clearInterval(interval);
  }, []);

  // Health + ranking / batch job flags for footer analysis row (10s)
  useEffect(() => {
    const fetchAnalysisProgress = async () => {
      try {
        const snap = await api.getAnalysisProgress();
        setAnalysisSnapshot(snap);
      } catch {
        // silent fail — keep last snapshot
      }
    };
    fetchAnalysisProgress();
    const interval = setInterval(fetchAnalysisProgress, 10_000);
    return () => clearInterval(interval);
  }, []);

  // Countdown ticker every second
  useEffect(() => {
    const tick = () => {
      if (!health?.next_scan) {
        setCountdown("--:--");
        return;
      }
      const msUntil = new Date(health.next_scan).getTime() - Date.now();
      setCountdown(formatCountdown(msUntil));
    };
    tick();
    const interval = setInterval(tick, 1_000);
    return () => clearInterval(interval);
  }, [health?.next_scan]);

  const handleKillswitchToggle = async () => {
    try {
      const result = await api.toggleKillswitch();
      setKillswitchActive(result.killswitch_active);
    } catch {
      setKillswitchActive((prev) => !prev);
    }
  };

  const activeSetups = health?.active_setups ?? 0;
  const maxCapacity = health?.max_capacity ?? 50;
  const overCapacity = maxCapacity > 0 && activeSetups > maxCapacity;
  const fillPercent = maxCapacity > 0 ? Math.min(100, (activeSetups / maxCapacity) * 100) : 0;
  const overFillPercent =
    maxCapacity > 0 && activeSetups > maxCapacity
      ? Math.min(105, (activeSetups / maxCapacity) * 100)
      : fillPercent;
  const fractionColor = overCapacity ? "#EF5350" : "#F5A623";
  const capacityTooltip = `Active markets being tracked. Maximum ${formatLocaleInt(maxCapacity)}. Markets are scored and replaced each scan cycle.`;

  const analysisHealth = analysisSnapshot?.health ?? null;
  const analysisRanking = analysisSnapshot?.ranking ?? null;
  const analysisFooterActive = analysisJobsActive(analysisHealth, analysisRanking);
  const analysisFooterMessage = analysisStatusMessage(analysisHealth, analysisRanking, scanStatus);
  const showAnalysisFooter = analysisFooterActive && analysisFooterMessage;

  return (
    <aside
      className="relative flex h-full min-h-0 flex-col border-r border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] transition-[width,min-width] duration-200"
      style={{
        width: collapsed ? 56 : 176,
        minWidth: collapsed ? 56 : 176,
      }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className="absolute -right-3 top-4 z-20 inline-flex h-6 w-6 items-center justify-center border border-[var(--border-strong)] bg-[var(--bg-elevated)] text-[var(--text-dim)] hover:text-[var(--text-primary)]"
      >
        {toggleIcon}
      </button>

      <div className={`pb-3 pt-4 ${collapsed ? "px-2" : "px-4"}`}>
        <div className="flex items-center">
          <IkengaLogomark size={20} style={{ marginRight: 8 }} />
          {!collapsed ? (
            <div>
              <span className="font-mono text-[17px] font-bold tracking-[0.04em] text-[#F5A623]">IKENGA</span>
            </div>
          ) : null}
        </div>
        {!collapsed && scanStatus?.in_progress && (
          <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 9, color: "#F5A623", letterSpacing: "0.1em", paddingTop: 6 }}>
            <span
              style={{
                width: 4,
                height: 4,
                borderRadius: "50%",
                background: "#F5A623",
                animation: "live-pulse 1s ease-in-out infinite",
              }}
            />
            <span>SCANNING...</span>
            <span style={{ animation: "value-flash 2s ease-in-out infinite" }}>
              {scanStatus.stage1_complete}/{scanStatus.stage2_total}
            </span>
          </div>
        )}
      </div>

      <div className={`${collapsed ? "mx-2" : "mx-5"} mb-3 h-px bg-[var(--border-subtle)]`} />

      <nav className={collapsed ? "px-1" : "px-2"}>
        {PRIMARY_NAV.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link key={item.href} href={item.href} className="mb-1 block no-underline" title={collapsed ? item.label : undefined}>
              <div
                className={[
                    "flex items-center gap-2.5 border-l px-3 py-1.5 transition-colors",
                    active
                      ? "border-[#F5A623] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "border-transparent text-[var(--text-dim)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
                  ].join(" ")}
                style={{ fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, letterSpacing: "0.05em" }}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
                {!collapsed ? <span>{item.label}</span> : null}
              </div>
            </Link>
          );
        })}
      </nav>

      <div className={`${collapsed ? "mx-2" : "mx-5"} my-3 h-px bg-[var(--border-subtle)]`} />

      <div className={collapsed ? "px-1" : "px-2"}>
        {SECONDARY_NAV.map((item) => {
          const Icon = item.icon;
          const active = item.href ? pathname === item.href || pathname.startsWith(item.href + "/") : false;
          if (item.href) {
            return (
              <Link key={item.label} href={item.href} className="mb-1 block no-underline" title={collapsed ? item.label : undefined}>
                <div
                  className={[
                    "flex items-center gap-2.5 border-l px-3 py-1.5 transition-colors",
                    active
                      ? "border-[#F5A623] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "border-transparent text-[var(--text-dim)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
                  ].join(" ")}
                  style={{ fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, letterSpacing: "0.05em" }}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
                  {!collapsed ? <span>{item.label}</span> : null}
                </div>
              </Link>
            );
          }
          return (
            <div
              key={item.label}
              className="mb-1 flex items-center gap-2.5 border-l border-transparent px-3 py-1.5 text-[var(--text-dim)] opacity-80"
              style={{ fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, letterSpacing: "0.05em" }}
              title={collapsed ? `${item.label} (locked)` : `${item.label} (coming soon)`}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
              {!collapsed ? (
                <>
                  <span>{item.label}</span>
                  <Lock className="ml-auto h-3 w-3 shrink-0 text-[#F5A623]" strokeWidth={2} aria-hidden />
                </>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className={`${collapsed ? "mx-2" : "mx-5"} my-3 h-px bg-[var(--border-subtle)]`} />

      <div className={`mt-auto space-y-4 border-t border-[var(--border-subtle)] bg-[var(--bg-base)] pb-4 pt-4 ${collapsed ? "px-2" : "px-4"}`}>
        <div>
          {!collapsed ? (
            <div className="mb-2 flex items-center justify-between">
              <Tooltip content={capacityTooltip} multiline>
                <span className="cursor-default uppercase tracking-[0.12em]" style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-dim)" }}>CAPACITY</span>
              </Tooltip>
              <span className="text-[9px] uppercase tracking-[0.12em]" style={{ color: fractionColor }}>
                {formatLocaleInt(activeSetups)} / {formatLocaleInt(maxCapacity)}
              </span>
            </div>
          ) : null}
          <div
            className="h-2 w-full border border-[var(--border-strong)] bg-[var(--bg-base)]"
            style={{ overflow: overCapacity ? "visible" : "hidden" }}
          >
            <div
              className="h-full"
              style={{
                width: `${overCapacity ? overFillPercent : fillPercent}%`,
                background: overCapacity ? "#EF5350" : "#F5A623",
                animation: overCapacity ? "pulse-red 1.5s ease-in-out infinite" : undefined,
              }}
            />
          </div>
          {!collapsed ? (
            <>
              <div className="mt-2 flex flex-wrap items-baseline gap-1.5">
                <span className="uppercase tracking-[0.1em]" style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-dim)" }}>NEXT</span>
                <span className="font-mono tracking-[0.06em]" style={{ fontSize: 10, color: "var(--text-secondary)" }}>{countdown}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-baseline gap-1.5">
                <span className="uppercase tracking-[0.1em]" style={{ fontFamily: "var(--font-sans)", fontSize: 9, color: "var(--text-dim)" }}>LAST</span>
                {health?.last_scan ? (
                  <span
                    style={{
                      animation: health?.scan_in_progress ? "value-flash 1.5s ease-in-out infinite" : undefined,
                    }}
                  >
                    <RelativeTimeWithTooltip
                      iso={health.last_scan}
                      fallback="PENDING"
                      className="font-mono tracking-[0.06em]"
                      style={{ fontSize: 10, color: "var(--text-secondary)" }}
                    />
                  </span>
                ) : (
                  <span className="text-[10px] uppercase tracking-[0.06em] text-[var(--text-dim)]">PENDING</span>
                )}
              </div>
            </>
          ) : null}
          {showAnalysisFooter ? (
            <div className="mt-2.5 border-t border-[var(--border-subtle)] pt-2.5">
              {!collapsed ? (
                <div className="mb-1 text-[9px] uppercase tracking-[0.12em] text-[var(--text-dim)]">ANALYSIS STATUS</div>
              ) : null}
              <div className={`flex items-center gap-1.5 ${collapsed ? "justify-center" : ""}`}>
                <Tooltip content="Background analysis is running. Market data will update when complete.">
                  <span
                    className="inline-flex shrink-0 cursor-default"
                    role="status"
                    aria-label="Background analysis running"
                  >
                    <span
                      className="inline-block rounded-full"
                      style={{
                        width: 5,
                        height: 5,
                        background: "#F5A623",
                        animation: "live-pulse 1s ease-in-out infinite",
                      }}
                    />
                  </span>
                </Tooltip>
                {!collapsed ? (
                  <span className="min-w-0 text-[9px] leading-tight tracking-[0.06em] text-[var(--text-dim)]">
                    {analysisFooterMessage}
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <div className="border-t border-[var(--border-subtle)] pt-4">
          {!collapsed ? <div className="mb-2 text-[9px] uppercase tracking-[0.12em] text-[var(--text-dim)]">Killswitch</div> : null}
          <div
            className="flex items-center justify-between border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2.5"
            style={{ cursor: "pointer" }}
            onClick={handleKillswitchToggle}
            title="Killswitch"
          >
            {!collapsed ? (
              <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--text-primary)]">
                {killswitchActive ? "Armed" : "Standby"}
              </span>
            ) : null}
            <div className="relative h-5 w-10 shrink-0 rounded-full border border-[var(--border-default)] bg-[var(--bg-base)]">
              <div
                className="absolute top-[1px] h-3.5 w-3.5 rounded-full"
                style={{
                  left: killswitchActive ? 20 : 2,
                  background: killswitchActive ? "#FF1744" : "var(--text-dim)",
                  transition: "left 0.15s ease",
                }}
              />
            </div>
          </div>
        </div>

      </div>
    </aside>
  );
}