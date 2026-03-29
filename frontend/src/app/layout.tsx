"use client";
import "./globals.css";
import { IBM_Plex_Mono } from "next/font/google";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { CommandPalette } from "@/components/command-palette";
import { AppSidebar } from "@/components/app-sidebar";

const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "700"] });

export default function RootLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const titleMap: Record<string, string> = {
    "/scanner": "Scanner",
    "/signals": "Signal Board",
    "/market": "Market View",
    "/universe": "Universe",
    "/analytics": "Analytics",
    "/risk": "Risk",
  };
  const activeTitle = Object.entries(titleMap).find(([path]) => pathname === path || pathname.startsWith(path + "/"))?.[1] ?? "Ikenga";

  return (
    <html lang="en">
      <body className={`${plexMono.className} flex h-screen w-screen overflow-hidden bg-[#131722] text-[#D1D4DC]`}>
        <div className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-[#363A45] bg-[#131722] px-6 text-[#D1D4DC]">
            <div className="flex items-center gap-4">
              <span className="text-[10px] uppercase tracking-[0.12em] text-[#787B86]">{activeTitle}</span>
            </div>
            <div />
          </header>

          <div className="flex flex-1 overflow-hidden">
            <AppSidebar />
            <main className="flex flex-1 flex-col overflow-hidden bg-background-base">
              {children}
            </main>
          </div>
        </div>
        <CommandPalette />
      </body>
    </html>
  );
}