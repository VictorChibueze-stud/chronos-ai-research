const scoreFormatter = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const intFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
});

const floatFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
});

/** Trend / ranking scores: always one decimal (e.g. 72.3). */
export function formatScore(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return scoreFormatter.format(value);
}

export function formatLocaleInt(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return intFormatter.format(Math.round(value));
}

export function formatLocaleFloat(value: number, maxDecimals = 2): string {
  if (!Number.isFinite(value)) return "—";
  if (maxDecimals === 2) return floatFormatter.format(value);
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: maxDecimals }).format(value);
}

/** Exact UTC string for tooltips (ISO-style, human readable). */
export function formatExactUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return "—";
    return d.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
  } catch {
    return "—";
  }
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return "—";

  const diffMs = Date.now() - ts;
  if (diffMs < 0) return "just now";

  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;

  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;

  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;

  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}
