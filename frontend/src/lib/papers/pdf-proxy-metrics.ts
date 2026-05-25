import path from "node:path"
import { appendFile, mkdir, readFile } from "node:fs/promises"
import type { PaperPdfProxyStats } from "@/types/studio"

export type PdfProxyMetricEvent = {
  code?: string
  contentLength?: number
  durationMs?: number
  host?: string
  path?: string
  rangeRequested?: boolean
  status?: number
  timestamp?: string
}

const DEFAULT_WINDOW_HOURS = 24
const MAX_RECENT_ERRORS = 8
const MAX_TOP_HOSTS = 5
const MS_PER_HOUR = 60 * 60 * 1000

export async function recordPdfProxyMetricEvent(event: PdfProxyMetricEvent): Promise<void> {
  const auditPath = resolvePdfProxyAuditPath()
  await mkdir(path.dirname(auditPath), { recursive: true })
  await appendFile(auditPath, `${JSON.stringify(sanitizeEvent(event))}\n`, "utf8")
}

export async function getPdfProxyStats(options: {
  now?: Date
  windowHours?: number
} = {}): Promise<PaperPdfProxyStats> {
  const now = options.now ?? new Date()
  const windowHours = normalizeWindowHours(options.windowHours)
  const windowStartedAt = new Date(now.getTime() - windowHours * MS_PER_HOUR)
  const readResult = await readMetricEvents()
  const events = readResult.events.filter((event) => {
    const timestamp = Date.parse(event.timestamp ?? "")
    return Number.isFinite(timestamp) && timestamp >= windowStartedAt.getTime() && timestamp <= now.getTime()
  })

  const errors = events.filter((event) => Boolean(event.code))
  const errorsByCode = errors.reduce<Record<string, number>>((counts, event) => {
    const code = event.code ?? "unknown"
    counts[code] = (counts[code] ?? 0) + 1
    return counts
  }, {})
  const notices = [
    ...readResult.notices,
    ...(events.length ? [] : ["No PDF proxy events were recorded for this window."])
  ]

  return {
    dataState: readResult.skippedLineCount ? "partial" : events.length ? "ready" : "empty",
    windowHours,
    generatedAt: now.toISOString(),
    windowStartedAt: windowStartedAt.toISOString(),
    windowEndedAt: now.toISOString(),
    totalRequests: events.length,
    successCount: events.length - errors.length,
    errorCount: errors.length,
    timeoutCount: errorsByCode.pdf_timeout ?? 0,
    oversizedCount: errorsByCode.pdf_too_large ?? 0,
    blockedCount: errorsByCode.blocked_pdf_host ?? 0,
    invalidContentTypeCount: errorsByCode.invalid_pdf_content_type ?? 0,
    upstreamFailureCount: errorsByCode.pdf_fetch_failed ?? 0,
    errorsByCode,
    topHosts: topHosts(events),
    recentErrors: errors
      .slice()
      .sort((left, right) => Date.parse(right.timestamp ?? "") - Date.parse(left.timestamp ?? ""))
      .slice(0, MAX_RECENT_ERRORS)
      .map((event) => ({
        timestamp: event.timestamp ?? "",
        host: event.host,
        path: event.path,
        code: event.code ?? "unknown",
        status: event.status,
        durationMs: event.durationMs
      })),
    notices
  }
}

export function normalizePdfProxyStatsWindow(value: string | null): number {
  return normalizeWindowHours(value === null ? undefined : Number(value))
}

export function resolvePdfProxyAuditPath(): string {
  return process.env.NEWSROOM_PDF_PROXY_AUDIT_PATH
    ?? path.resolve(process.cwd(), "..", ".newsroom", "papers", "pdf-proxy-events.jsonl")
}

async function readMetricEvents(): Promise<{
  events: PdfProxyMetricEvent[]
  notices: string[]
  skippedLineCount: number
}> {
  let text = ""
  try {
    text = await readFile(resolvePdfProxyAuditPath(), "utf8")
  } catch (error) {
    if (isFileMissingError(error)) {
      return { events: [], notices: [], skippedLineCount: 0 }
    }
    return {
      events: [],
      notices: ["PDF proxy metrics could not be read; showing empty fallback stats."],
      skippedLineCount: 1
    }
  }

  const events: PdfProxyMetricEvent[] = []
  let skippedLineCount = 0
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) {
      continue
    }
    try {
      const payload = JSON.parse(line) as PdfProxyMetricEvent
      events.push(sanitizeEvent(payload))
    } catch {
      skippedLineCount += 1
    }
  }

  return {
    events,
    notices: skippedLineCount ? [`Skipped ${skippedLineCount} malformed PDF proxy metric line(s).`] : [],
    skippedLineCount
  }
}

function sanitizeEvent(event: PdfProxyMetricEvent): PdfProxyMetricEvent {
  return {
    timestamp: safeText(event.timestamp) ?? new Date().toISOString(),
    host: safeText(event.host),
    path: safePath(event.path),
    status: safeNumber(event.status),
    code: safeText(event.code),
    durationMs: safeNumber(event.durationMs),
    contentLength: safeNumber(event.contentLength),
    rangeRequested: Boolean(event.rangeRequested)
  }
}

function topHosts(events: PdfProxyMetricEvent[]) {
  const buckets = new Map<string, { requestCount: number; errorCount: number; durations: number[] }>()
  for (const event of events) {
    const host = event.host ?? "unknown"
    const bucket = buckets.get(host) ?? { requestCount: 0, errorCount: 0, durations: [] }
    bucket.requestCount += 1
    if (event.code) {
      bucket.errorCount += 1
    }
    if (event.durationMs !== undefined) {
      bucket.durations.push(event.durationMs)
    }
    buckets.set(host, bucket)
  }

  return [...buckets.entries()]
    .sort(([, left], [, right]) => right.errorCount - left.errorCount || right.requestCount - left.requestCount)
    .slice(0, MAX_TOP_HOSTS)
    .map(([host, bucket]) => ({
      host,
      requestCount: bucket.requestCount,
      errorCount: bucket.errorCount,
      avgDurationMs: bucket.durations.length ? Math.round(bucket.durations.reduce((total, value) => total + value, 0) / bucket.durations.length) : undefined
    }))
}

function normalizeWindowHours(value?: number): number {
  return value !== undefined && Number.isFinite(value) && value > 0 && value <= 24 * 30 ? Math.round(value) : DEFAULT_WINDOW_HOURS
}

function safeNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined
}

function safeText(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined
  }
  const trimmed = value.trim()
  return trimmed ? trimmed.slice(0, 240) : undefined
}

function safePath(value: unknown): string | undefined {
  const text = safeText(value)
  if (!text) {
    return undefined
  }
  return text.split("?")[0].split("#")[0]
}

function isFileMissingError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT"
}
