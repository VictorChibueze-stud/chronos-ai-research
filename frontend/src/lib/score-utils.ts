/**
 * Shared score colour helpers — keeps score thresholds in one place.
 * Thresholds: ≥75 = amber (high conviction), ≥50 = secondary (moderate), else muted.
 */

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 75) return "var(--amber)";
  if (score >= 50) return "var(--text-secondary)";
  return "var(--text-muted)";
}

export function scoreBarColor(score: number | null | undefined): string {
  if (score == null) return "var(--border-strong)";
  if (score >= 75) return "var(--amber)";
  if (score >= 50) return "var(--bull)";
  return "var(--border-strong)";
}
