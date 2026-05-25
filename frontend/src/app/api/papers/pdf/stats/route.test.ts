import { mkdtemp, rm } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "node:os"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { recordPdfProxyMetricEvent } from "@/lib/papers/pdf-proxy-metrics"
import { GET } from "@/app/api/papers/pdf/stats/route"

let tempDir = ""

function statsRequest(windowHours?: string) {
  const url = new URL("http://localhost/api/papers/pdf/stats")
  if (windowHours !== undefined) {
    url.searchParams.set("windowHours", windowHours)
  }
  return new NextRequest(url)
}

describe("paper PDF proxy stats route", () => {
  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), "newsroom-pdf-proxy-stats-"))
    vi.stubEnv("NEWSROOM_PDF_PROXY_AUDIT_PATH", path.join(tempDir, "events.jsonl"))
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("returns an empty success envelope when no events exist", async () => {
    const response = await GET(statsRequest())
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.success).toBe(true)
    expect(payload.data.stats).toMatchObject({
      dataState: "empty",
      totalRequests: 0,
      windowHours: 24
    })
  })

  it("aggregates recorded events and normalizes invalid windowHours", async () => {
    await recordPdfProxyMetricEvent({
      timestamp: new Date().toISOString(),
      host: "arxiv.org",
      path: "/pdf/2605.00001.pdf",
      code: "pdf_too_large",
      status: 413,
      durationMs: 18
    })

    const response = await GET(statsRequest("not-a-number"))
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.data.stats).toMatchObject({
      dataState: "ready",
      totalRequests: 1,
      errorCount: 1,
      oversizedCount: 1,
      windowHours: 24
    })
  })
})
