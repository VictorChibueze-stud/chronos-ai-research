import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Mono"', "monospace"],
        mono: ['"IBM Plex Mono"', "monospace"],
      },
      dropShadow: {
        "glow-amber": "0 0 8px rgba(245,166,35,0.4)",
      },
      colors: {
        background: {
          base: "#131722",
          panel: "#1E222D",
          surface: "#2A2E39",
        },
        surface: {
          DEFAULT: "#1E222D",
          elevated: "#2A2E39",
        },
        border: {
          faint: "#363A45",
          strong: "#363A45",
        },
        text1: "#D1D4DC",
        text2: "#787B86",
        text3: "#787B86",
        text4: "#787B86",
        brand: {
          amber: "#F5A623",
          amberDim: "#F5A623",
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