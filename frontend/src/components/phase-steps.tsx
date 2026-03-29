interface PhaseStepsProps {
  step: number;
  total?: number;
  direction: "LONG" | "SHORT";
}

export function PhaseSteps({ step, total = 5, direction }: PhaseStepsProps) {
  const clamped = Math.max(0, Math.min(total, step));
  const filledColor = direction === "LONG" ? "#F5A623" : "#E05A5A";
  const emptyColor = "#1C1E24";
  const borderEmptyColor = "#2A2D36";

  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: total }).map((_, index) => {
        const isFilled = index < clamped;
        return (
          <div
            key={index}
            style={{
              width: 8,
              height: 8,
              borderRadius: 1,
              background: isFilled ? filledColor : emptyColor,
              border: isFilled ? "none" : `1px solid ${borderEmptyColor}`,
              transition: "background 0.4s, border-color 0.3s",
            }}
          />
        );
      })}
    </div>
  );
}
