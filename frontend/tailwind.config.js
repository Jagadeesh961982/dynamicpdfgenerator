/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        bg: {
          page:     "#07070e",
          surface:  "#0e0e18",
          card:     "#14141f",
          elevated: "#1a1a28",
          hover:    "#1f1f30",
        },
        border: {
          DEFAULT: "rgba(255,255,255,0.07)",
          strong:  "rgba(255,255,255,0.13)",
        },
        brand: {
          DEFAULT: "#7c3aed",
          light:   "#8b5cf6",
          soft:    "rgba(124,58,237,0.18)",
          glow:    "rgba(124,58,237,0.35)",
        },
        txt: {
          primary: "#f0f0ff",
          muted:   "#8b8baa",
          subtle:  "#55556a",
        },
        ok:   { DEFAULT: "#34d399", soft: "rgba(52,211,153,0.15)"  },
        warn: { DEFAULT: "#fbbf24", soft: "rgba(251,191,36,0.15)"  },
        err:  { DEFAULT: "#f87171", soft: "rgba(248,113,113,0.15)" },
        info: { DEFAULT: "#38bdf8", soft: "rgba(56,189,248,0.15)"  },
      },
      animation: {
        "fade-in":    "fadeIn 0.25s ease",
        "slide-up":   "slideUp 0.3s ease",
        "pulse-slow": "pulse 3s cubic-bezier(0.4,0,0.6,1) infinite",
        "spin-slow":  "spin 2s linear infinite",
      },
      keyframes: {
        fadeIn:  { from: { opacity: "0" },                    to: { opacity: "1" } },
        slideUp: { from: { opacity: "0", transform: "translateY(12px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
      backdropBlur: { xs: "2px" },
    },
  },
  plugins: [],
};
