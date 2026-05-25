import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "node:os"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  getPdfProxyStats,
  normalizePdfProxyStatsWindow,
  recordPdfProxyMetricEvent
} from "@/lib/papers/pdf-proxy-metrics"

let tempDir = ""
let auditPath = ""

describe("PDF proxy metrics store", () => {
  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), "newsroom-pdf-proxy-"))
    auditPath = path.join(tempDir, "pdf-proxy-events.jsonl")
    vi.stubEnv("NEWSROOM_PDF_PROXY_AUDIT_PATH", auditPath)
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("records sanitized events without query strings", async () => {
    await recordPdfProxyMetricEvent({
      timestamp: "2026-05-25T00:00:00.000Z",
      host: "arxiv.org",
      path: "/pdf/2605.00001.pdf?token=secret",
      status: 200,
      durationMs: 42,
      contentLength: 1024,
      rangeRequested: true
    })

    const text = await readFile(auditPath, "utf8")
    const event = JSON.parse(text.trim())
    expect(event).toMatchObject({
      host: "arxiv.org",
      path: "/pdf/2605.00001.pdf",
      status: 200,
      durationMs: 42,
      rangeRequested: true
    })
    expect(text).not.toContain("secret")
  })

  it("aggregates window counts, errors by code, top hosts, and recent errors", async () => {
    await recordPdfProxyMetricEvent({
      timestamp: "2026-05-25T00:00:00.000Z",
      host: "arxiv.org",
      path: "/pdf/1.pdf",
      status: 200,
      durationMs: 20
    })
    await recordPdfProxyMetricEvent({
      timestamp: "2026-05-25T00:10:00.000Z",
      host: "openreview.net",
      path: "/pdf",
      code: "pdf_timeout",
      status: 504,
      durationMs: 10_000
    })
    await recordPdfProxyMetricEvent({
      timestamp: "2026-05-24T00:00:00.000Z",
      host: "arxiv.org",
      path: "/pdf/old.pdf",
      code: "pdf_fetch_failed",
      status: 502
    })

    const stats = await getPdfProxyStats({
      now: new Date("2026-05-25T01:00:00.000Z"),
      windowHours: 2
    })

    expect(stats.dataState).toBe("ready")
    expect(stats.totalRequests).toBe(2)
    expect(stats.successCount).toBe(1)
    expect(stats.errorCount).toBe(1)
    expect(stats.timeoutCount).toBe(1)
    expect(stats.errorsByCode).toEqual({ pdf_timeout: 1 })
    expect(stats.topHosts[0]).toMatchObject({ host: "openreview.net", requestCount: 1, errorCount: 1 })
    expect(stats.recentErrors[0]).toMatchObject({ code: "pdf_timeout", host: "openreview.net" })
  })

  it("returns empty stats when the audit file is missing", async () => {
    const stats = await getPdfProxyStats({ now: new Date("2026-05-25T01:00:00.000Z") })

    expect(stats.dataState).toBe("empty")
    expect(stats.totalRequests).toBe(0)
    expect(stats.notices).toContain("No PDF proxy events were recorded for this window.")
  })

  it("skips malformed lines and marks stats partial", async () => {
    await writeFile(
      auditPath,
      [
        "{\"timestamp\":\"2026-05-25T00:00:00.000Z\",\"host\":\"arxiv.org\",\"status\":200}",
        "not-json"
      ].join("\n"),
      "utf8"
    )

    const stats = await getPdfProxyStats({
      now: new Date("2026-05-25T01:00:00.000Z"),
      windowHours: 2
    })

    expect(stats.dataState).toBe("partial")
    expect(stats.totalRequests).toBe(1)
    expect(stats.notices[0]).toContain("Skipped 1 malformed")
  })

  it("normalizes invalid windows to 24 hours", () => {
    expect(normalizePdfProxyStatsWindow("nope")).toBe(24)
    expect(normalizePdfProxyStatsWindow("-1")).toBe(24)
    expect(normalizePdfProxyStatsWindow("2")).toBe(2)
  })
})
