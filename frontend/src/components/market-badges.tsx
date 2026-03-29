interface DirectionTagProps {
  direction: "LONG" | "SHORT";
}

interface PhaseBadgeProps {
  phase: "IMPULSE" | "RETRACEMENT";
}

export function DirectionTag({ direction }: DirectionTagProps) {
  const isLong = direction === "LONG";
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        padding: "3px 7px",
        borderRadius: 2,
        background: isLong ? "rgba(245,166,35,0.1)" : "rgba(224,90,90,0.1)",
        border: isLong ? "1px solid rgba(245,166,35,0.25)" : "1px solid rgba(224,90,90,0.25)",
        color: isLong ? "#F5A623" : "#E05A5A",
        fontFamily: '"IBM Plex Mono", monospace',
        display: "inline-block",
        letterSpacing: "0.04em",
      }}
    >
      {direction} {isLong ? "↑" : "↓"}
    </span>
  );
}

export function PhaseBadge({ phase }: PhaseBadgeProps) {
  const isImpulse = phase === "IMPULSE";
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 400,
        padding: "3px 7px",
        borderRadius: 2,
        border: "1px solid #2A2E36",
        background: isImpulse ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
        color: isImpulse ? "#C8C8D0" : "#6B6F7A",
        fontFamily: '"IBM Plex Mono", monospace',
        display: "inline-block",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
      }}
    >
      {phase}
    </span>
  );
}
