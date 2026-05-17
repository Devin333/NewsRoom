import type { Config } from "tailwindcss"

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#f7f8fa",
        ink: "#172033",
        muted: "#667085",
        line: "#d8dee8",
        accent: "#1769aa",
        good: "#1b7f5c",
        warn: "#b7791f",
        bad: "#b42318"
      }
    }
  },
  plugins: []
}

export default config
