import { formatScore } from "@/lib/format-display";

interface ScoreBarProps {
  value: number;
}

function scoreColor(val: number): string {
  if (val >= 80) return "#F5A623";
  if (val >= 60) return "#C8851A";
  return "#6B6F7A";
}

export function ScoreBar({ value }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const color = scoreColor(clamped);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          width: 80,
          height: 3,
          background: "#1C1E24",
          borderRadius: 1,
        }}
      >
        <div
          style={{
            width: `${clamped}%`,
            height: "100%",
            background: color,
            borderRadius: 1,
            transition: "width 0.6s ease",
          }}
        />
      </div>
      <span
        style={{
          fontSize: 13,
          fontWeight: 700,
          minWidth: 28,
          color,
          fontFamily: '"IBM Plex Mono", monospace',
        }}
      >
        {formatScore(clamped)}
      </span>
    </div>
  );
}
