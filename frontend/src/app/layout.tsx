"use client";
import "./globals.css";
import { IBM_Plex_Mono } from "next/font/google";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronUp, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { CommandPalette } from "@/components/command-palette";
import { AppSidebar } from "@/components/app-sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "700"] });

export default function RootLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [topbarHidden, setTopbarHidden] = useState(false);

  useEffect(() => {
    try {
      const sidebar = window.localStorage.getItem("ikenga.sidebarCollapsed");
      const topbar = window.localStorage.getItem("ikenga.topbarHidden");
      if (sidebar !== null) {
        setSidebarCollapsed(sidebar === "true");
      }
      if (topbar !== null) {
        setTopbarHidden(topbar === "true");
      }
    } catch {
      // no-op if storage is unavailable
    }
  }, []);

  const toggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem("ikenga.sidebarCollapsed", String(next));
      } catch {
        // no-op
      }
      return next;
    });
  };

  const toggleTopbar = () => {
    setTopbarHidden((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem("ikenga.topbarHidden", String(next));
      } catch {
        // no-op
      }
      return next;
    });
  };

  const titleMap: Record<string, string> = {
    "/scanner": "Scanner",
    "/signals": "Signal Board",
    "/trades": "Trade History",
    "/market": "Market View",
    "/universe": "Universe",
    "/settings/integrations": "Integrations & execution",
    "/analytics": "Analytics",
    "/risk": "Risk",
  };
  const activeTitle = Object.entries(titleMap).find(([path]) => pathname === path || pathname.startsWith(path + "/"))?.[1] ?? "Ikenga";

  function RouteTitleHeading({ text }: { text: string }) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (words.length <= 1) {
      return (
        <span className="text-sm font-bold uppercase tracking-[0.14em] text-[#D1D4DC]">{words[0] ?? text}</span>
      );
    }
    return (
      <span className="text-sm font-bold uppercase tracking-[0.14em]">
        <span className="text-[#F5A623]">{words[0]}</span>
        <span className="text-[#D1D4DC]"> {words.slice(1).join(" ")}</span>
      </span>
    );
  }

  return (
    <html lang="en">
      <body className={`${plexMono.className} flex h-screen w-screen overflow-hidden bg-[#131722] text-[#D1D4DC]`}>
        <TooltipProvider>
          <div className="relative flex flex-1 flex-col overflow-hidden">
            {!topbarHidden ? (
              <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-[#363A45] bg-[#1E222D] px-6 text-[#D1D4DC] shadow-[inset_0_-1px_0_0_rgba(54,58,69,0.6)]">
                <div className="flex items-center gap-4">
                  <RouteTitleHeading text={activeTitle} />
                </div>
                <button
                  type="button"
                  onClick={toggleTopbar}
                  aria-label="Hide top bar"
                  title="Hide top bar"
                  className="inline-flex items-center gap-1 border border-[#363A45] bg-[#1E222D] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[#787B86] hover:text-[#D1D4DC]"
                >
                  <ChevronUp className="h-3.5 w-3.5" />
                  Hide
                </button>
              </header>
            ) : null}
            {topbarHidden ? (
              <button
                type="button"
                onClick={toggleTopbar}
                aria-label="Show top bar"
                title="Show top bar"
                className="absolute right-4 top-3 z-20 inline-flex items-center gap-1 border border-[#363A45] bg-[#1E222D] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[#787B86] hover:text-[#D1D4DC]"
              >
                <ChevronDown className="h-3.5 w-3.5" />
                Top Bar
              </button>
            ) : null}

            <div className="flex flex-1 overflow-hidden">
              <AppSidebar
                collapsed={sidebarCollapsed}
                onToggle={toggleSidebar}
                toggleIcon={sidebarCollapsed ? <PanelLeftOpen className="h-3.5 w-3.5" /> : <PanelLeftClose className="h-3.5 w-3.5" />}
              />
              <main className="flex flex-1 flex-col overflow-hidden bg-background-base">
                {children}
              </main>
            </div>
          </div>
          <CommandPalette />
        </TooltipProvider>
      </body>
    </html>
  );
}