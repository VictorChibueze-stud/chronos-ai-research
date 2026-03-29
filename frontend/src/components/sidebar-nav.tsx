"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  label: string;
}

const DEFAULT_NAV_ITEMS: NavItem[] = [
  { href: "/scanner", label: "SCANNER" },
  { href: "/signals", label: "SIGNAL BOARD" },
  { href: "/market", label: "MARKET VIEW" },
  { href: "/universe", label: "UNIVERSE" },
  { href: "/analytics", label: "ANALYTICS" },
  { href: "/risk", label: "RISK" },
];

interface SidebarNavProps {
  items?: NavItem[];
}

export function SidebarNav({ items = DEFAULT_NAV_ITEMS }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav className="px-2 py-3">
      <ul className="space-y-1">
        {items.map((item) => {
          const isActive = pathname === item.href;

          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={[
                  "block border-l-2 px-3 py-2 text-xs uppercase tracking-[0.14em] transition-colors",
                  isActive
                    ? "border-l-[#F5A623] text-[#F5A623]"
                    : "border-l-transparent text-[#4A4D58]",
                ].join(" ")}
                aria-current={isActive ? "page" : undefined}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}