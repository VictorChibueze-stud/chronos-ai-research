"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";

type ZoneType = "SUPPORT" | "RESISTANCE" | "CHOCH";
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function CommandConsolePage() {
  const router = useRouter();
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [zoneType, setZoneType] = useState<ZoneType>("CHOCH");
  const [priceHigh, setPriceHigh] = useState<string>("");
  const [priceLow, setPriceLow] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [overrides, setOverrides] = useState<any[]>([]);
  const [status, setStatus] = useState<{ message: string; kind: "success" | "error" } | null>(
    null,
  );
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/overrides`)
      .then((r) => r.json())
      .then((data) => setOverrides(Array.isArray(data) ? data : []))
      .catch(() => setOverrides([]));
  }, []);

  useEffect(() => {
    if (!validationError) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setValidationError(null);
    }, 3000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [validationError]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedSymbol = symbol.trim().toUpperCase();
    const parsedHigh = Number(priceHigh);
    const parsedLow = Number(priceLow);
    if (normalizedSymbol.length === 0) {
      setValidationError("[SYSTEM]: SYMBOL IS REQUIRED");
      return;
    }

    if (!Number.isFinite(parsedHigh) || !Number.isFinite(parsedLow)) {
      setValidationError("[SYSTEM]: INVALID PRICE INPUT");
      return;
    }

    if (parsedHigh <= parsedLow) {
      setValidationError("[SYSTEM]: PRICE HIGH MUST EXCEED PRICE LOW");
      return;
    }

    setIsSubmitting(true);
    setStatus(null);
    setValidationError(null);

    try {
      await api.postOverride({
        symbol: normalizedSymbol,
        zone_type: zoneType,
        price_high: parsedHigh,
        price_low: parsedLow,
      });
      setStatus({ message: "[SYSTEM]: OVERRIDE INJECTED SUCCESSFULLY", kind: "success" });
      fetch(`${API}/api/overrides`)
        .then((r) => r.json())
        .then((data) => setOverrides(Array.isArray(data) ? data : []))
        .catch(() => setOverrides([]));
      router.push("/signals");
    } catch (error) {
      setStatus({
        message: `[SYSTEM]: ${(error as Error).message || "OVERRIDE INJECTION FAILED"}`,
        kind: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="h-full overflow-hidden bg-background-base">
      <div className="grid h-full grid-cols-[350px_1fr] gap-4 p-4">
        <section className="flex min-h-0 flex-col border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
          <div className="border-b border-[var(--border-subtle)] pb-3">
            <h1 className="text-sm uppercase tracking-[0.18em] text-text-primary">OVERRIDE PARAMETERS</h1>
            <p className="mt-1 text-[11px] uppercase tracking-[0.14em] text-text-dim">
              Manual Alert Zone Injection
            </p>
          </div>

          <form onSubmit={onSubmit} className="mt-5 flex flex-1 flex-col gap-4">
            <label className="flex flex-col gap-2">
              <span className="text-[9px] uppercase tracking-[0.14em] text-text-dim">Symbol</span>
              <input
                value={symbol}
                onChange={(event) => setSymbol(event.target.value)}
                className="rounded-none border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-2 text-sm text-text-primary outline-none transition-colors focus:border-[#F5A623]"
                placeholder="BTCUSDT"
                required
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-[9px] uppercase tracking-[0.14em] text-text-dim">Zone Type</span>
              <select
                value={zoneType}
                onChange={(event) => setZoneType(event.target.value as ZoneType)}
                className="rounded-none border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-2 text-sm text-text-primary outline-none transition-colors focus:border-[#F5A623]"
              >
                <option value="SUPPORT">SUPPORT</option>
                <option value="RESISTANCE">RESISTANCE</option>
                <option value="CHOCH">CHOCH</option>
              </select>
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-[9px] uppercase tracking-[0.14em] text-text-dim">Price High</span>
              <input
                type="number"
                step="any"
                value={priceHigh}
                onChange={(event) => setPriceHigh(event.target.value)}
                className="rounded-none border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-2 text-sm text-text-primary outline-none transition-colors focus:border-[#F5A623]"
                placeholder="73100"
                required
              />
            </label>

            <label className="flex flex-col gap-2">
              <span className="text-[9px] uppercase tracking-[0.14em] text-text-dim">Price Low</span>
              <input
                type="number"
                step="any"
                value={priceLow}
                onChange={(event) => setPriceLow(event.target.value)}
                className="rounded-none border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-2 text-sm text-text-primary outline-none transition-colors focus:border-[#F5A623]"
                placeholder="72800"
                required
              />
            </label>

            <div className="min-h-10 border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2">
              {validationError ? (
                <p className="text-sm text-[#F23645]">{validationError}</p>
              ) : status ? (
                <p className={status.kind === "success" ? "text-sm text-[#F5A623]" : "text-sm text-[#F23645]"}>
                  {status.message}
                </p>
              ) : (
                <p className="text-sm text-text-dim">[SYSTEM]: READY</p>
              )}
            </div>

            <div className="mt-auto">
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full rounded-none border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-2 font-semibold uppercase text-text-primary transition-colors hover:border-[#F5A623] hover:bg-[#F5A623] hover:text-[var(--bg-surface)] disabled:opacity-60"
              >
                {isSubmitting ? "Injecting..." : "Inject Override"}
              </button>
            </div>
          </form>
        </section>

        <section className="flex min-h-0 flex-col border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
          <div className="border-b border-[var(--border-subtle)] px-4 py-3">
            <h2 className="text-sm uppercase tracking-[0.18em] text-text-primary">ACTIVE FSM OVERRIDES</h2>
            <p className="mt-1 text-[10px] uppercase tracking-[0.14em] text-text-dim">Current Overrides</p>
          </div>

          <div className="min-h-0 flex-1 overflow-auto bg-[var(--bg-surface)]">
            <table className="w-full border-collapse text-left">
              <thead className="bg-[var(--bg-surface)]">
                <tr>
                  <th className="border-b border-[var(--border-subtle)] px-4 py-3 text-[9px] uppercase tracking-[0.12em] text-text-dim">Symbol</th>
                  <th className="border-b border-[var(--border-subtle)] px-4 py-3 text-[9px] uppercase tracking-[0.12em] text-text-dim">Type</th>
                  <th className="border-b border-[var(--border-subtle)] px-4 py-3 text-[9px] uppercase tracking-[0.12em] text-text-dim">High</th>
                  <th className="border-b border-[var(--border-subtle)] px-4 py-3 text-[9px] uppercase tracking-[0.12em] text-text-dim">Low</th>
                </tr>
              </thead>
              <tbody>
                {overrides.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-4 text-[11px] text-text-dim">No overrides found.</td>
                  </tr>
                )}
                {overrides.map((row) => (
                  <tr key={row.id} className="border-b border-[var(--border-subtle)] transition-colors hover:bg-[var(--border-subtle)]/30">
                    <td className="px-4 py-3 text-[11px] text-text-primary">{row.symbol}</td>
                    <td className="px-4 py-3 text-[11px] text-text-dim">{row.zone_type}</td>
                    <td className="px-4 py-3 text-[11px] text-text-primary">{row.price_high}</td>
                    <td className="px-4 py-3 text-[11px] text-text-primary">{row.price_low}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}