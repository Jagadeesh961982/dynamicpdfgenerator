/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Google Sans Flex"', "system-ui", "sans-serif"],
        mono: ['"Roboto Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        surface: {
          DEFAULT: "#f8f9fa",
          card: "#ffffff",
          sidebar: "#eef0f4",
        },
        ink: {
          DEFAULT: "#1f1f1f",
          muted: "#5f6368",
        },
        accent: {
          DEFAULT: "#1a73e8",
          hover: "#1557b0",
        },
      },
    },
  },
  plugins: [],
};
