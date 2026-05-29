export function formatCompactNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K`
  return String(value)
}

export function formatSignedNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (value > 0) return `+${formatCompactNumber(value)}`
  return formatCompactNumber(value)
}

export function formatScore(value: number | undefined): string {
  if (value === undefined) return "-"
  return value <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(1)
}

export function formatDate(value: string | undefined): string {
  if (!value) return "-"
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return value
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(time)
}

export function labelize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
