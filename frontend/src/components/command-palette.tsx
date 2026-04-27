"use client";

import { api } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

const COMMON_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "EURUSD", "GBPUSD", "USOIL", "NAS100"];

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

export function CommandPalette() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dynamicSymbols, setDynamicSymbols] = useState<string[]>([]);

  useEffect(() => {
    let isCancelled = false;

    const loadSymbols = async () => {
      try {
        const setups = await api.getSetupsSummary();
        if (isCancelled) {
          return;
        }

        const nextSymbols = setups
          .map((setup) => normalizeSymbol(String(setup.symbol ?? "")))
          .filter(Boolean);

        setDynamicSymbols(Array.from(new Set(nextSymbols)));
      } catch {
        if (!isCancelled) {
          setDynamicSymbols([]);
        }
      }
    };

    void loadSymbols();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.dataset.commandPaletteInput === "true") {
        if (event.key === "Escape") {
          event.preventDefault();
          setIsOpen(false);
          setQuery("");
        }
        return;
      }

      if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setIsOpen((current) => !current);
        if (isOpen) {
          setQuery("");
        }
        return;
      }

      if (event.key === "Escape") {
        setIsOpen(false);
        setQuery("");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const allSymbols = useMemo(() => {
    return Array.from(new Set([...COMMON_SYMBOLS, ...dynamicSymbols].map(normalizeSymbol)));
  }, [dynamicSymbols]);

  const filteredSymbols = useMemo(() => {
    const normalizedQuery = normalizeSymbol(query);
    if (!normalizedQuery) {
      return allSymbols;
    }

    return allSymbols
      .filter((symbol) => symbol.includes(normalizedQuery))
      .sort((left, right) => {
        const leftStartsWith = left.startsWith(normalizedQuery);
        const rightStartsWith = right.startsWith(normalizedQuery);

        if (leftStartsWith !== rightStartsWith) {
          return leftStartsWith ? -1 : 1;
        }

        return left.localeCompare(right);
      });
  }, [allSymbols, query]);

  const topResult = filteredSymbols[0];

  const closePalette = () => {
    setIsOpen(false);
    setQuery("");
  };

  const navigateToSymbol = (symbol: string) => {
    const selectedSymbol = normalizeSymbol(symbol);
    router.push(`/market?symbol=${encodeURIComponent(selectedSymbol)}&timeframe=1h`);
    closePalette();
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-start justify-center bg-black/70 px-4 pt-[12vh] backdrop-blur-sm">
      <button
        type="button"
        aria-label="Close command palette"
        className="absolute inset-0 cursor-default"
        onClick={closePalette}
      />

      <div className="relative z-[201] w-full max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-[#0E1118]/90 shadow-[0_30px_120px_rgba(0,0,0,0.65)] backdrop-blur-xl">
        <div className="border-b border-white/10 px-5 py-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] tracking-[0.18em] text-brand-amber">COMMAND PALETTE</span>
            <span className="text-[10px] tracking-[0.12em] text-[var(--text-muted)]">PRESS ESC TO CLOSE</span>
          </div>

          <input
            ref={inputRef}
            data-command-palette-input="true"
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && topResult) {
                event.preventDefault();
                navigateToSymbol(topResult);
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closePalette();
              }
            }}
            placeholder="Jump to symbol..."
            className="w-full border-none bg-transparent px-0 py-1 font-mono text-[24px] font-semibold tracking-[0.04em] text-[var(--text-primary)] outline-none placeholder:text-[#343844]"
          />
        </div>

        <div className="max-h-[420px] overflow-y-auto p-2">
          {filteredSymbols.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center">
              <div className="text-[10px] tracking-[0.14em] text-[var(--text-muted)]">NO MATCHING SYMBOLS</div>
            </div>
          ) : (
            filteredSymbols.map((symbol, index) => {
              const isTopResult = index === 0;
              return (
                <button
                  key={symbol}
                  type="button"
                  onClick={() => navigateToSymbol(symbol)}
                  className={[
                    "flex w-full items-center justify-between rounded-xl px-4 py-3 text-left transition-colors",
                    isTopResult
                      ? "bg-brand-amber/12 text-brand-amber"
                      : "text-[#D1D5DE] hover:bg-white/5 hover:text-[#F4F6FA]",
                  ].join(" ")}
                >
                  <div className="flex items-center gap-3">
                    <div className={[
                      "h-2 w-2 rounded-full",
                      isTopResult ? "bg-brand-amber shadow-[0_0_12px_rgba(245,166,35,0.7)]" : "bg-[#2F3440]",
                    ].join(" ")} />
                    <span className="font-mono text-[15px] font-semibold tracking-[0.05em]">{symbol}</span>
                  </div>
                  <span className="font-mono text-[10px] tracking-[0.12em] text-[#5A6070]">MARKET VIEW</span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}