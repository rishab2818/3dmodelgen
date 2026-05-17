import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Minimal palette for M1. shadcn/ui colors land in M5.
        bg: "#0b0d10",
        panel: "#13161b",
        border: "#23262d",
        muted: "#7b818b",
        text: "#e6e8eb",
        accent: "#5b8def",
        success: "#3cc78a",
        warn: "#e7b455",
        error: "#e16464",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
