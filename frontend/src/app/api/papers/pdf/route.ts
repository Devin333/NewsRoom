import { NextRequest, NextResponse } from "next/server"
import { recordPdfProxyMetricEvent, type PdfProxyMetricEvent } from "@/lib/papers/pdf-proxy-metrics"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

const MAX_PDF_CONTENT_LENGTH_BYTES = 50 * 1024 * 1024
const PDF_FETCH_TIMEOUT_MS = 10_000

const ALLOWED_PDF_HOSTS = new Set([
  "arxiv.org",
  "www.arxiv.org",
  "openreview.net",
  "www.openreview.net",
  "aclanthology.org",
  "www.aclanthology.org",
  "proceedings.mlr.press",
  "papers.nips.cc",
  "proceedings.neurips.cc",
  "openaccess.thecvf.com"
])

type PdfProxyErrorCode =
  | "missing_pdf_url"
  | "invalid_pdf_url"
  | "unsupported_pdf_source"
  | "blocked_pdf_host"
  | "pdf_timeout"
  | "pdf_too_large"
  | "pdf_fetch_failed"
  | "invalid_pdf_content_type"

type PdfProxyAudit = PdfProxyMetricEvent & { durationMs: number }

export async function GET(request: NextRequest) {
  const startedAt = Date.now()
  const range = request.headers.get("range")
  const url = request.nextUrl.searchParams.get("url")
  if (!url) {
    return pdfError("missing_pdf_url", "Missing PDF URL.", 400, {
      durationMs: elapsed(startedAt),
      rangeRequested: Boolean(range)
    })
  }

  let parsedUrl: URL
  try {
    parsedUrl = new URL(url)
  } catch {
    return pdfError("invalid_pdf_url", "Invalid PDF URL.", 400, {
      durationMs: elapsed(startedAt),
      rangeRequested: Boolean(range)
    })
  }

  const auditBase = {
    host: parsedUrl.hostname,
    path: parsedUrl.pathname,
    rangeRequested: Boolean(range)
  }

  if (isBlockedNetworkHost(parsedUrl.hostname)) {
    return pdfError("blocked_pdf_host", "Blocked PDF host.", 400, {
      ...auditBase,
      durationMs: elapsed(startedAt)
    })
  }

  if (
    parsedUrl.protocol !== "https:" ||
    parsedUrl.username ||
    parsedUrl.password ||
    !ALLOWED_PDF_HOSTS.has(normalizedHostname(parsedUrl.hostname)) ||
    !isAllowedPaperPdfUrl(parsedUrl)
  ) {
    return pdfError("unsupported_pdf_source", "Unsupported PDF source.", 400, {
      ...auditBase,
      durationMs: elapsed(startedAt)
    })
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), PDF_FETCH_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(parsedUrl.toString(), {
      headers: {
        "User-Agent": "NewsRoomResearch/0.1 (+https://localhost)",
        ...(range ? { Range: range } : {})
      },
      cache: "no-store",
      signal: controller.signal
    })
  } catch (error) {
    const code = isAbortError(error) ? "pdf_timeout" : "pdf_fetch_failed"
    return pdfError(code, code === "pdf_timeout" ? "PDF fetch timed out." : "PDF fetch failed.", code === "pdf_timeout" ? 504 : 502, {
      ...auditBase,
      code,
      durationMs: elapsed(startedAt)
    })
  } finally {
    clearTimeout(timeout)
  }

  const contentLength = responseContentLength(response)
  if (contentLength !== undefined && contentLength > MAX_PDF_CONTENT_LENGTH_BYTES) {
    void response.body?.cancel()
    return pdfError("pdf_too_large", "PDF is too large.", 413, {
      ...auditBase,
      contentLength,
      durationMs: elapsed(startedAt),
      status: response.status
    })
  }

  if (!isSuccessfulPdfResponse(response) || !response.body) {
    void response.body?.cancel()
    return pdfError("pdf_fetch_failed", "PDF fetch failed.", 502, {
      ...auditBase,
      contentLength,
      durationMs: elapsed(startedAt),
      status: response.status
    })
  }

  if (!isPdfResponse(parsedUrl, response)) {
    void response.body.cancel()
    return pdfError("invalid_pdf_content_type", "Invalid PDF content type.", 502, {
      ...auditBase,
      contentLength,
      durationMs: elapsed(startedAt),
      status: response.status
    })
  }

  await auditPdfProxy({
    ...auditBase,
    contentLength,
    durationMs: elapsed(startedAt),
    status: response.status
  })

  return new NextResponse(response.body, {
    headers: responseHeaders(response),
    status: response.status
  })
}

function responseHeaders(response: Response) {
  const headers: Record<string, string> = {
    "Accept-Ranges": response.headers.get("accept-ranges") ?? "bytes",
    "Cache-Control": "no-store",
    "Content-Disposition": "inline",
    "Content-Type": response.headers.get("content-type") ?? "application/pdf"
  }

  const contentLength = response.headers.get("content-length")
  const contentRange = response.headers.get("content-range")
  if (contentLength) {
    headers["Content-Length"] = contentLength
  }
  if (contentRange) {
    headers["Content-Range"] = contentRange
  }

  return headers
}

function isAllowedPaperPdfUrl(url: URL) {
  const host = normalizedHostname(url.hostname).replace(/^www\./, "")
  const path = url.pathname.toLowerCase()

  if (host === "arxiv.org") {
    return path.startsWith("/pdf/")
  }

  if (host === "openreview.net") {
    return url.pathname === "/pdf" && Boolean(url.searchParams.get("id"))
  }

  if (host === "aclanthology.org") {
    return path.endsWith(".pdf")
  }

  if (host === "proceedings.mlr.press") {
    return /^\/v\d+\/[^/]+\/[^/]+\.pdf$/i.test(url.pathname)
  }

  if (host === "openaccess.thecvf.com") {
    return path.includes("/papers/") && path.endsWith(".pdf")
  }

  if (host === "papers.nips.cc" || host === "proceedings.neurips.cc") {
    return path.endsWith(".pdf")
  }

  return false
}

function isPdfResponse(url: URL, response: Response) {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? ""
  return contentType.includes("application/pdf") || contentType.includes("octet-stream") || url.pathname.toLowerCase().endsWith(".pdf")
}

function isSuccessfulPdfResponse(response: Response) {
  return response.status === 200 || response.status === 206
}

async function pdfError(code: PdfProxyErrorCode, message: string, status: number, audit: PdfProxyAudit) {
  await auditPdfProxy({ ...audit, code, status })
  return NextResponse.json(
    {
      error: {
        code,
        message
      }
    },
    {
      status,
      headers: {
        "Cache-Control": "no-store"
      }
    }
  )
}

async function auditPdfProxy(audit: PdfProxyAudit) {
  const payload = {
    event: "paper_pdf_proxy",
    host: audit.host,
    path: audit.path,
    durationMs: audit.durationMs,
    status: audit.status,
    code: audit.code,
    contentLength: audit.contentLength,
    rangeRequested: audit.rangeRequested
  }
  if (audit.code) {
    console.warn(payload)
  } else {
    console.info(payload)
  }
  try {
    await recordPdfProxyMetricEvent(audit)
  } catch (error) {
    console.warn({
      event: "paper_pdf_proxy_metrics_write_failed",
      message: error instanceof Error ? error.message : "PDF proxy metrics write failed"
    })
  }
}

function elapsed(startedAt: number) {
  return Date.now() - startedAt
}

function responseContentLength(response: Response) {
  const contentLength = parseContentLength(response.headers.get("content-length"))
  const contentRangeLength = parseContentRangeLength(response.headers.get("content-range"))
  return contentRangeLength ?? contentLength
}

function parseContentLength(value: string | null) {
  if (!value) {
    return undefined
  }
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
}

function parseContentRangeLength(value: string | null) {
  if (!value) {
    return undefined
  }
  const match = value.match(/\/(\d+)$/)
  if (!match) {
    return undefined
  }
  return parseContentLength(match[1])
}

function isAbortError(error: unknown) {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError"
}

function isBlockedNetworkHost(hostname: string) {
  const host = normalizedHostname(hostname)
  if (host === "localhost" || host.endsWith(".localhost")) {
    return true
  }

  if (host === "metadata.google.internal") {
    return true
  }

  return isBlockedIpv4Host(host) || isBlockedIpv6Host(host)
}

function normalizedHostname(hostname: string) {
  return hostname.toLowerCase().replace(/\.$/, "")
}

function isBlockedIpv4Host(host: string) {
  const octets = host.split(".")
  if (octets.length !== 4 || octets.some((part) => !/^\d+$/.test(part))) {
    return false
  }

  const numbers = octets.map((part) => Number.parseInt(part, 10))
  if (numbers.some((part) => part < 0 || part > 255)) {
    return false
  }

  const [first, second] = numbers
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168) ||
    first >= 224 ||
    host === "100.100.100.200"
  )
}

function isBlockedIpv6Host(host: string) {
  const normalized = host.replace(/^\[/, "").replace(/\]$/, "")
  if (!normalized.includes(":")) {
    return false
  }

  return (
    normalized === "::" ||
    normalized === "::1" ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    normalized.startsWith("fe80:") ||
    normalized.startsWith("ff") ||
    normalized.toLowerCase().startsWith("::ffff:127.") ||
    normalized.toLowerCase().startsWith("::ffff:10.") ||
    normalized.toLowerCase().startsWith("::ffff:192.168.") ||
    normalized.toLowerCase().startsWith("::ffff:169.254.")
  )
}
