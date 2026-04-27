import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  message?: string;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ icon, title, message, action }: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        border: "1px dashed var(--border-default)",
        borderRadius: 4,
        gap: 8,
        width: "100%",
      }}
    >
      {icon && (
        <div style={{ color: "var(--text-muted)", marginBottom: 4, opacity: 0.5 }}>
          {icon}
        </div>
      )}
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text-dim)",
          letterSpacing: "0.02em",
        }}
      >
        {title}
      </div>
      {message && (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 11,
            color: "var(--text-muted)",
            textAlign: "center",
            maxWidth: 280,
            lineHeight: 1.6,
          }}
        >
          {message}
        </div>
      )}
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          style={{
            marginTop: 8,
            padding: "5px 14px",
            fontFamily: "var(--font-sans)",
            fontSize: 11,
            fontWeight: 500,
            color: "var(--amber)",
            border: "1px solid var(--amber)",
            background: "transparent",
            borderRadius: 3,
            cursor: "pointer",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
