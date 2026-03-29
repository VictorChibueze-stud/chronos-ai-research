interface StatCardProps {
  label: string;
  value: string | number;
  highlighted?: boolean;
  valueColor?: string;
}

export function StatCard({ label, value, highlighted = false, valueColor }: StatCardProps) {
  const displayValueColor = valueColor || (highlighted ? "#F5A623" : "#E8E8EC");

  return (
    <div
      style={{
        flex: 1,
        padding: "14px 18px",
        background: "#111318",
        border: "1px solid #1C1E24",
        borderTop: highlighted ? "2px solid #F5A623" : "1px solid #1C1E24",
        borderRadius: 2,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <label
        style={{
          fontSize: 10,
          color: "#4A4D58",
          letterSpacing: "0.12em",
          fontWeight: 700,
          fontFamily: '"IBM Plex Mono", monospace',
          textTransform: "uppercase",
        }}
      >
        {label}
      </label>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: displayValueColor,
          fontFamily: '"IBM Plex Mono", monospace',
        }}
      >
        {value}
      </div>
    </div>
  );
}
