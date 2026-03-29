"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart2,
  Globe,
  PieChart,
  Radar,
  Shield,
  type LucideIcon,
} from "lucide-react";

import { api } from "@/lib/api";
import type { HealthResponse } from "@/lib/types";

interface ScanStatus {
  in_progress: boolean;
  stage: string | null;
  stage1_complete: number;
  stage2_complete: number;
  stage2_total: number;
}

const PRIMARY_NAV = [
  { label: "SCANNER", href: "/scanner", icon: Radar },
  { label: "SIGNAL BOARD", href: "/signals", icon: Activity },
  { label: "MARKET VIEW", href: "/market", icon: BarChart2 },
  { label: "UNIVERSE", href: "/universe", icon: Globe },
] satisfies { label: string; href: string; icon: LucideIcon }[];

const SECONDARY_NAV = [
  { label: "ANALYTICS", icon: PieChart },
  { label: "RISK", icon: Shield },
] satisfies { label: string; icon: LucideIcon }[];

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

function formatLastScan(iso: string | null): string {
  if (!iso) return "PENDING";
  try {
    const d = new Date(iso);
    return d.toUTCString().slice(17, 22) + " UTC";
  } catch {
    return "PENDING";
  }
}

export function AppSidebar() {
  const pathname = usePathname();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [killswitchActive, setKillswitchActive] = useState(false);
  const [countdown, setCountdown] = useState<string>("--:--");

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
  const capacityRatio = maxCapacity > 0 ? activeSetups / maxCapacity : 0;
  const capacityColor = capacityRatio > 0.8 ? "#E05A5A" : "#F5A623";

  return (
    <aside className="flex w-[176px] min-w-[176px] flex-col border-r border-[#363A45] bg-[#1E222D] text-[#D1D4DC]">
      <div className="px-4 pb-3 pt-4">
        <div className="flex items-center">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ marginRight: 8 }}>
            <circle cx="10" cy="10" r="8" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.4"/>
            <circle cx="10" cy="10" r="5" fill="none" stroke="#F5A623" strokeWidth="0.8" opacity="0.7"/>
            <path d="M10 3 L10 6 M8.5 5 L10 6.5 L11.5 5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M10 17 L10 14 M8.5 15 L10 13.5 L11.5 15" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M3 10 L6 10 M5 8.5 L6.5 10 L5 11.5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <path d="M17 10 L14 10 M15 8.5 L13.5 10 L15 11.5" fill="none" stroke="#F5A623" strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
            <circle cx="10" cy="10" r="1.5" fill="#F5A623"/>
          </svg>
          <div>
            <span className="font-mono text-[17px] font-bold tracking-[0.04em] text-[#F5A623]">IKENGA</span>
          </div>
        </div>
        {scanStatus?.in_progress && (
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

      <div className="mx-5 mb-3 h-px bg-[#363A45]" />

      <nav className="px-2">
        {PRIMARY_NAV.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link key={item.href} href={item.href} className="mb-1 block no-underline">
              <div
                className={[
                  "flex items-center gap-2.5 border-l-2 px-3 py-1.5 text-[10px] tracking-[0.1em] transition-colors",
                  active
                    ? "border-[#F5A623] bg-[#2A2E39] text-[#D1D4DC]"
                    : "border-transparent text-[#787B86] hover:bg-[#2A2E39]/60 hover:text-[#D1D4DC]",
                ].join(" ")}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
                <span>{item.label}</span>
              </div>
            </Link>
          );
        })}
      </nav>

      <div className="mx-5 my-3 h-px bg-[#363A45]" />

      <div className="px-2">
        {SECONDARY_NAV.map((item) => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="mb-1 flex items-center gap-2.5 border-l-2 border-transparent px-3 py-1.5 text-[10px] tracking-[0.1em] text-[#787B86] opacity-70">
              <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
              <span>{item.label}</span>
              <span className="ml-auto border border-[#363A45] bg-[#2A2E39] px-1.5 py-0.5 text-[9px] tracking-[0.08em] text-[#D1D4DC]">
                SOON
              </span>
            </div>
          );
        })}
      </div>

      <div className="mx-5 my-3 h-px bg-[#363A45]" />

      <div className="space-y-4 px-4 pb-4">
        <div>
          <div className="mb-2 text-[9px] uppercase tracking-[0.12em] text-[#787B86]">Killswitch</div>
          <div
            className="flex items-center justify-between border border-[#363A45] bg-[#2A2E39] px-3 py-2"
            style={{ cursor: "pointer" }}
            onClick={handleKillswitchToggle}
          >
            <span className="text-[10px] uppercase tracking-[0.08em] text-[#D1D4DC]">
              {killswitchActive ? "Armed" : "Standby"}
            </span>
            <div className="relative h-5 w-10 rounded-full border border-[#363A45] bg-[#131722]">
              <div
                className="absolute top-[1px] h-3.5 w-3.5 rounded-full"
                style={{
                  left: killswitchActive ? 20 : 2,
                  background: killswitchActive ? "#FF1744" : "#787B86",
                  transition: "left 0.15s ease",
                }}
              />
            </div>
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between text-[9px] uppercase tracking-[0.12em] text-[#787B86]">
            <span>Capacity</span>
            <span style={{ color: capacityColor }}>{activeSetups} / {maxCapacity}</span>
          </div>
          <div className="h-2 w-full border border-[#363A45] bg-[#131722]">
            <div
              className="h-full"
              style={{ width: `${capacityRatio * 100}%`, background: capacityColor }}
            />
          </div>
          <div className="mt-2 text-[9px] tracking-[0.1em]" style={{ color: "#3A3D48" }}>
            NEXT SCAN {countdown}
          </div>
          <div
            className="mt-1 text-[9px] tracking-[0.1em]"
            style={{
              color: "#3A3D48",
              animation: health?.scan_in_progress ? "value-flash 1.5s ease-in-out infinite" : undefined,
            }}
          >
            LAST SCAN {formatLastScan(health?.last_scan ?? null)}
          </div>
        </div>
      </div>
    </aside>
  );
}