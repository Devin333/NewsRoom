import type { Config } from "tailwindcss"

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#f9fafb",
        ink: "#111827",
        muted: "#6b7280",
        subtle: "#9ca3af",
        line: "#e5e7eb",
        accent: "#2563eb",
        "accent-hover": "#1d4ed8",
        good: "#16a34a",
        warn: "#d97706",
        bad: "#dc2626"
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"]
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(0 0 0 / 0.06), 0 1px 2px -1px rgb(0 0 0 / 0.04)"
      }
    }
  },
  plugins: []
}

export default config
