interface StatRowProps {
  label: string;
  value: string | number;
  valueColor?: string;
}

export function StatRow({ label, value, valueColor }: StatRowProps) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "5px 0",
        fontFamily: '"IBM Plex Mono", monospace',
      }}
    >
      <span
        style={{
          fontSize: 9,
          color: "#3A3D48",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          fontWeight: 400,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 11,
          color: valueColor || "#C8C8D0",
          fontWeight: 600,
        }}
      >
        {value}
      </span>
    </div>
  );
}
