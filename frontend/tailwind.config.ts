import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
        data: ["var(--font-mono)", "monospace"],
      },
      dropShadow: {
        "glow-amber": "0 0 8px rgba(245,166,35,0.4)",
      },
      colors: {
        background: {
          base:     "var(--bg-base)",
          surface:  "var(--bg-surface)",
          elevated: "var(--bg-elevated)",
          hover:    "var(--bg-hover)",
          input:    "var(--bg-input)",
          panel:    "var(--bg-surface)",
        },
        border: {
          subtle:  "var(--border-subtle)",
          default: "var(--border-default)",
          strong:  "var(--border-strong)",
          faint:   "var(--border-subtle)",
        },
        text: {
          primary:   "var(--text-primary)",
          secondary: "var(--text-secondary)",
          dim:       "var(--text-dim)",
          muted:     "var(--text-muted)",
        },
        bull:   "var(--bull)",
        bear:   "var(--bear)",
        amber:  "var(--amber)",
        surface: {
          DEFAULT:  "var(--bg-elevated)",
          elevated: "var(--bg-input)",
        },
        text1: "var(--text-primary)",
        text2: "var(--text-secondary)",
        text3: "var(--text-dim)",
        text4: "var(--text-muted)",
        brand: {
          amber:    "var(--amber)",
          amberDim: "var(--amber)",
        },
        signal: {
          bull: "#00C853",
          bear: "#FF1744",
          blue: "#3A6BFF",
        },
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
};

export default config;