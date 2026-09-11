import type { Config } from "tailwindcss";

/**
 * Trading Universe visual identity - deliberately distinct from any previous
 * project. Deep space-blue ground, cool neutral glass, a single restrained
 * accent. Roughly 70% Apple-like polish, 30% dense analytical utility.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./universe/**/*.{ts,tsx}",
    "./charts/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        void: {
          DEFAULT: "#05070d",
          50: "#0a0e18",
          100: "#0e1421",
          200: "#141b2b",
          300: "#1c2436",
        },
        glass: {
          DEFAULT: "rgba(255,255,255,0.04)",
          edge: "rgba(255,255,255,0.10)",
          hi: "rgba(255,255,255,0.07)",
        },
        ink: {
          DEFAULT: "#e8ecf4",
          dim: "#9aa5bb",
          faint: "#5d687e",
        },
        // Accessible signal palette: never red/green alone (spec 49).
        accent: { DEFAULT: "#5ad1e6", deep: "#2a9fbd", glow: "#9df0ff" },
        up: "#4fd1a5",
        down: "#e8886b",
        warn: "#e8c26b",
        live: "#4fd1a5",
        degraded: "#e8c26b",
        stale: "#e8886b",
      },
      fontFamily: {
        sans: [
          "-apple-system", "BlinkMacSystemFont", "SF Pro Display", "Inter",
          "Segoe UI", "system-ui", "sans-serif",
        ],
        mono: [
          "SF Mono", "ui-monospace", "JetBrains Mono", "Menlo", "monospace",
        ],
      },
      backdropBlur: { xs: "2px", glass: "24px" },
      boxShadow: {
        glass: "0 8px 32px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06)",
        glow: "0 0 24px rgba(90,209,230,0.28)",
      },
      transitionTimingFunction: {
        // The calm, premium feel the spec asks for: ease out, never bouncy.
        calm: "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 220ms cubic-bezier(0.22,0.61,0.36,1)",
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
