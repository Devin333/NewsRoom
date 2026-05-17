export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "n/a"
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date)
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined) {
    return "n/a"
  }
  return new Intl.NumberFormat("en").format(value)
}

export function formatScore(value?: number | null): string {
  if (value === null || value === undefined) {
    return "n/a"
  }
  if (value <= 1) {
    return `${Math.round(value * 100)}%`
  }
  return String(value)
}

export function stringifyJson(value: unknown): string {
  if (value === null || value === undefined) {
    return "{}"
  }
  return JSON.stringify(value, null, 2)
}
