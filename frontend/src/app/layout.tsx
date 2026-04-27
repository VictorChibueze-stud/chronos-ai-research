"use client";
import "./globals.css";
import {
    IBM_Plex_Mono,
    IBM_Plex_Sans,
} from "next/font/google";
import { usePathname } from "next/navigation";
import { ChevronDown, ChevronUp, Moon, PanelLeftClose, PanelLeftOpen, Sun } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { CommandPalette } from "@/components/command-palette";
import { AppSidebar } from "@/components/app-sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

const plexMono = IBM_Plex_Mono({
    subsets: ["latin"],
    weight: ["400", "500", "700"],
    variable: "--font-mono",
});

const plexSans = IBM_Plex_Sans({
    subsets: ["latin"],
    weight: ["400", "500", "600", "700"],
    variable: "--font-sans",
});

export default function RootLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [topbarHidden, setTopbarHidden] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    try {
      const sidebar = window.localStorage.getItem("ikenga.sidebarCollapsed");
      const topbar = window.localStorage.getItem("ikenga.topbarHidden");
      const savedTheme = window.localStorage.getItem("ikenga.theme");
      if (sidebar !== null) {
        setSidebarCollapsed(sidebar === "true");
      }
      if (topbar !== null) {
        setTopbarHidden(topbar === "true");
      }
      if (savedTheme === "light" || savedTheme === "dark") {
        setTheme(savedTheme);
      }
    } catch {
      // no-op if storage is unavailable
    }
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem("ikenga.theme", next);
      } catch {
        // no-op
      }
      return next;
    });
  };

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
        <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-primary)" }}>{words[0] ?? text}</span>
      );
    }
    return (
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase" }}>
        <span className="text-[#F5A623]">{words[0]}</span>
        <span style={{ color: "var(--text-primary)" }}> {words.slice(1).join(" ")}</span>
      </span>
    );
  }

  return (
    <html lang="en">
      <body className={`${plexMono.variable} ${plexSans.variable} flex h-screen w-screen overflow-hidden bg-[var(--bg-base)] text-[var(--text-primary)]`}>
        <TooltipProvider>
          <div className="relative flex flex-1 flex-col overflow-hidden">
            {!topbarHidden ? (
              <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-[var(--border-strong)] bg-[var(--bg-elevated)] px-6 text-[var(--text-primary)] shadow-[inset_0_-1px_0_0_rgba(54,58,69,0.6)]">
                <div className="flex items-center gap-4">
                  <RouteTitleHeading text={activeTitle} />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <button
                    type="button"
                    onClick={toggleTheme}
                    title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
                    className="inline-flex items-center gap-1 border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[var(--text-dim)] hover:text-[var(--text-primary)]"
                  >
                    {theme === "dark" ? <Sun className="h-3 w-3" /> : <Moon className="h-3 w-3" />}
                    {theme === "dark" ? "Light" : "Dark"}
                  </button>
                  <button
                    type="button"
                    onClick={toggleTopbar}
                    aria-label="Hide top bar"
                    title="Hide top bar"
                    className="inline-flex items-center gap-1 border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-[var(--text-dim)] hover:text-[var(--text-primary)]"
                  >
                    <ChevronUp className="h-3.5 w-3.5" />
                    Hide
                  </button>
                </div>
              </header>
            ) : null}
            {topbarHidden ? (
              <button
                type="button"
                onClick={toggleTopbar}
                aria-label="Show top bar"
                title="Show top bar"
                className="absolute right-4 top-3 z-20 inline-flex items-center gap-1 border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2 py-1 text-[9px] uppercase tracking-[0.08em] text-text-dim hover:text-text-primary"
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