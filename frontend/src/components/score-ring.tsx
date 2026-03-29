interface ScoreRingProps {
  score: number;
  size?: number;
}

function clampScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, score));
}

function ringColor(score: number): string {
  if (score >= 80) return "#F5A623";
  if (score >= 60) return "#C8851A";
  return "#5C4A1E";
}

export function ScoreRing({ score, size = 86 }: ScoreRingProps) {
  const normalized = clampScore(score);
  const r = 36;
  const stroke = 5;
  const circumference = 2 * Math.PI * r;
  const fill = (normalized / 100) * circumference;
  const color = ringColor(normalized);

  return (
    <svg width={size} height={size} viewBox="0 0 86 86" aria-label={`Score ${Math.round(normalized)}`}>
      <circle cx={43} cy={43} r={r} fill="none" stroke="#1C1E24" strokeWidth={stroke} />
      <circle
        cx={43}
        cy={43}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeDasharray={`${fill} ${Math.max(0, circumference - fill)}`}
        strokeDashoffset={circumference / 4}
        strokeLinecap="round"
      />
      <text
        x={43}
        y={47}
        textAnchor="middle"
        fill={color}
        style={{
          fontFamily: '"IBM Plex Mono", monospace',
          fontSize: 20,
          fontWeight: 700,
        }}
      >
        {Math.round(normalized)}
      </text>
    </svg>
  );
}
