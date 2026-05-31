import { mkdtemp, readFile, rm } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "node:os"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { GET } from "@/app/api/papers/pdf/route"

const originalFetch = globalThis.fetch
let tempDir = ""
let auditPath = ""

function pdfRequest(url?: string, headers?: HeadersInit) {
  const requestUrl = new URL("http://localhost/api/papers/pdf")
  if (url !== undefined) {
    requestUrl.searchParams.set("url", url)
  }
  return new NextRequest(requestUrl, { headers })
}

async function json(response: Response) {
  return response.json() as Promise<{ error: { code: string; message: string } }>
}

function pdfResponse(init?: ResponseInit) {
  return new Response(new TextEncoder().encode("%PDF-1.7"), {
    status: 200,
    headers: {
      "content-length": "8",
      "content-type": "application/pdf",
      ...init?.headers
    },
    ...init
  })
}

describe("paper PDF proxy route", () => {
  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(tmpdir(), "newsroom-pdf-route-"))
    auditPath = path.join(tempDir, "events.jsonl")
    vi.stubEnv("NEWSROOM_PDF_PROXY_AUDIT_PATH", auditPath)
    vi.spyOn(console, "info").mockImplementation(() => undefined)
    vi.spyOn(console, "warn").mockImplementation(() => undefined)
  })

  afterEach(async () => {
    globalThis.fetch = originalFetch
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    vi.useRealTimers()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("rejects missing and invalid URLs without fetching upstream", async () => {
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock

    const missing = await GET(pdfRequest())
    const invalid = await GET(pdfRequest("not a url"))

    expect(missing.status).toBe(400)
    expect(await json(missing)).toMatchObject({ error: { code: "missing_pdf_url" } })
    expect(invalid.status).toBe(400)
    expect(await json(invalid)).toMatchObject({ error: { code: "invalid_pdf_url" } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("rejects non-HTTPS, unsupported hosts, and disallowed paths before fetching", async () => {
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock

    const nonHttps = await GET(pdfRequest("http://arxiv.org/pdf/2605.00001.pdf"))
    const unsupportedHost = await GET(pdfRequest("https://example.com/paper.pdf"))
    const disallowedPath = await GET(pdfRequest("https://arxiv.org/abs/2605.00001"))

    expect(nonHttps.status).toBe(400)
    expect(await json(nonHttps)).toMatchObject({ error: { code: "unsupported_pdf_source" } })
    expect(unsupportedHost.status).toBe(400)
    expect(await json(unsupportedHost)).toMatchObject({ error: { code: "unsupported_pdf_source" } })
    expect(disallowedPath.status).toBe(400)
    expect(await json(disallowedPath)).toMatchObject({ error: { code: "unsupported_pdf_source" } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("rejects localhost, private IP, metadata, and IPv6 local addresses before fetching", async () => {
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock

    const localhost = await GET(pdfRequest("https://localhost/pdf/2605.00001.pdf"))
    const privateIp = await GET(pdfRequest("https://127.0.0.1/pdf/2605.00001.pdf"))
    const metadataIp = await GET(pdfRequest("https://169.254.169.254/latest/meta-data"))
    const ipv6Loopback = await GET(pdfRequest("https://[::1]/pdf/2605.00001.pdf"))

    expect(localhost.status).toBe(400)
    expect(await json(localhost)).toMatchObject({ error: { code: "blocked_pdf_host" } })
    expect(privateIp.status).toBe(400)
    expect(await json(privateIp)).toMatchObject({ error: { code: "blocked_pdf_host" } })
    expect(metadataIp.status).toBe(400)
    expect(await json(metadataIp)).toMatchObject({ error: { code: "blocked_pdf_host" } })
    expect(ipv6Loopback.status).toBe(400)
    expect(await json(ipv6Loopback)).toMatchObject({ error: { code: "blocked_pdf_host" } })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("forwards Range and streams allowed PDF responses with safe headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      pdfResponse({
        status: 206,
        headers: {
          "accept-ranges": "bytes",
          "content-length": "8",
          "content-range": "bytes 0-7/8",
          "content-type": "application/pdf"
        }
      })
    )
    globalThis.fetch = fetchMock

    const response = await GET(pdfRequest("https://arxiv.org/pdf/2605.00001.pdf", { range: "bytes=0-7" }))

    expect(response.status).toBe(206)
    expect(response.headers.get("cache-control")).toBe("no-store")
    expect(response.headers.get("content-disposition")).toBe("inline")
    expect(response.headers.get("content-range")).toBe("bytes 0-7/8")
    expect(fetchMock).toHaveBeenCalledWith(
      "https://arxiv.org/pdf/2605.00001.pdf",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({ Range: "bytes=0-7" }),
        signal: expect.any(AbortSignal)
      })
    )
    expect(console.info).toHaveBeenCalledWith(expect.objectContaining({ event: "paper_pdf_proxy", rangeRequested: true }))
    const auditText = await readFile(auditPath, "utf8")
    expect(auditText).toContain("\"host\":\"arxiv.org\"")
    expect(auditText).toContain("\"rangeRequested\":true")
  })

  it("rejects oversized upstream PDFs before streaming", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      pdfResponse({
        headers: {
          "content-length": String(51 * 1024 * 1024),
          "content-type": "application/pdf"
        }
      })
    )

    const response = await GET(pdfRequest("https://arxiv.org/pdf/2605.00001.pdf"))

    expect(response.status).toBe(413)
    expect(await json(response)).toMatchObject({ error: { code: "pdf_too_large" } })
    expect(console.warn).toHaveBeenCalledWith(expect.objectContaining({ code: "pdf_too_large" }))
  })

  it("aborts slow upstream fetches with a timeout error", async () => {
    vi.useFakeTimers()
    globalThis.fetch = vi.fn((_url, init) => {
      const signal = (init as RequestInit).signal
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"))
        })
      })
    })

    const pending = GET(pdfRequest("https://arxiv.org/pdf/2605.00001.pdf"))
    await vi.advanceTimersByTimeAsync(10_000)
    const response = await pending

    expect(response.status).toBe(504)
    expect(await json(response)).toMatchObject({ error: { code: "pdf_timeout" } })
    expect(console.warn).toHaveBeenCalledWith(expect.objectContaining({ code: "pdf_timeout" }))
  })

  it("rejects non-PDF content from allowed hosts", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("not a pdf", {
        status: 200,
        headers: {
          "content-length": "9",
          "content-type": "text/html"
        }
      })
    )

    const response = await GET(pdfRequest("https://openreview.net/pdf?id=abc123"))

    expect(response.status).toBe(502)
    expect(await json(response)).toMatchObject({ error: { code: "invalid_pdf_content_type" } })
  })
})
