import { NextRequest, NextResponse } from "next/server"
import { recordPdfProxyMetricEvent, type PdfProxyMetricEvent } from "@/lib/papers/pdf-proxy-metrics"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

const MAX_PDF_CONTENT_LENGTH_BYTES = 50 * 1024 * 1024
const PDF_FETCH_TIMEOUT_MS = 10_000
const MAX_PDF_REDIRECTS = 3

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

type PdfUrlValidation =
  | { ok: true }
  | { ok: false; code: "blocked_pdf_host" | "unsupported_pdf_source"; message: string }

type PdfFetchResult =
  | { ok: true; response: Response; url: URL }
  | {
      ok: false
      code: "blocked_pdf_host" | "unsupported_pdf_source" | "pdf_fetch_failed"
      message: string
      status: number
      responseStatus?: number
      url?: URL
    }

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

  const validation = validatePdfUrl(parsedUrl)
  if (!validation.ok) {
    return pdfError(validation.code, validation.message, 400, {
      ...auditBase,
      durationMs: elapsed(startedAt)
    })
  }

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), PDF_FETCH_TIMEOUT_MS)
  let response: Response
  try {
    const fetched = await fetchPdfResponse(parsedUrl, range, controller.signal)
    if (!fetched.ok) {
      const errorAuditBase = fetched.url
        ? { host: fetched.url.hostname, path: fetched.url.pathname, rangeRequested: Boolean(range) }
        : auditBase
      clearTimeout(timeout)
      return pdfError(fetched.code, fetched.message, fetched.status, {
        ...errorAuditBase,
        durationMs: elapsed(startedAt),
        status: fetched.responseStatus
      })
    }
    response = fetched.response
  } catch (error) {
    clearTimeout(timeout)
    const code = isAbortError(error) ? "pdf_timeout" : "pdf_fetch_failed"
    return pdfError(code, code === "pdf_timeout" ? "PDF fetch timed out." : "PDF fetch failed.", code === "pdf_timeout" ? 504 : 502, {
      ...auditBase,
      code,
      durationMs: elapsed(startedAt)
    })
  }

  try {
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

    const pdfContentType = pdfResponseContentType(response)
    if (!pdfContentType) {
      void response.body.cancel()
      return pdfError("invalid_pdf_content_type", "Invalid PDF content type.", 502, {
        ...auditBase,
        contentLength,
        durationMs: elapsed(startedAt),
        status: response.status
      })
    }

    const body = await readLimitedResponseBody(response, controller.signal)
    if (!body.ok) {
      return pdfError(body.code, body.message, body.status, {
        ...auditBase,
        contentLength: body.contentLength ?? contentLength,
        durationMs: elapsed(startedAt),
        status: response.status
      })
    }

    if (requiresPdfMagicCheck(response, pdfContentType) && !hasPdfMagic(body.bytes)) {
      return pdfError("invalid_pdf_content_type", "Invalid PDF content.", 502, {
        ...auditBase,
        contentLength: body.contentLength,
        durationMs: elapsed(startedAt),
        status: response.status
      })
    }

    await auditPdfProxy({
      ...auditBase,
      contentLength: contentLength ?? body.contentLength,
      durationMs: elapsed(startedAt),
      status: response.status
    })

    return new NextResponse(arrayBufferFromBytes(body.bytes), {
      headers: responseHeaders(response, body.bytes.byteLength),
      status: response.status
    })
  } finally {
    clearTimeout(timeout)
  }
}

async function fetchPdfResponse(initialUrl: URL, range: string | null, signal: AbortSignal): Promise<PdfFetchResult> {
  let currentUrl = initialUrl
  for (let redirectCount = 0; redirectCount <= MAX_PDF_REDIRECTS; redirectCount += 1) {
    const response = await fetch(currentUrl.toString(), {
      headers: {
        "User-Agent": "AgoraHubResearch/0.1 (+https://localhost)",
        ...(range ? { Range: range } : {})
      },
      cache: "no-store",
      signal,
      redirect: "manual"
    })

    if (!isRedirectResponse(response)) {
      return { ok: true, response, url: currentUrl }
    }

    void response.body?.cancel()
    if (redirectCount >= MAX_PDF_REDIRECTS) {
      return {
        ok: false,
        code: "unsupported_pdf_source",
        message: "PDF redirect limit exceeded.",
        status: 400,
        responseStatus: response.status,
        url: currentUrl
      }
    }

    const location = response.headers.get("location")
    if (!location) {
      return {
        ok: false,
        code: "unsupported_pdf_source",
        message: "PDF redirect did not include a destination.",
        status: 400,
        responseStatus: response.status,
        url: currentUrl
      }
    }

    let nextUrl: URL
    try {
      nextUrl = new URL(location, currentUrl)
    } catch {
      return {
        ok: false,
        code: "unsupported_pdf_source",
        message: "PDF redirect destination is invalid.",
        status: 400,
        responseStatus: response.status,
        url: currentUrl
      }
    }

    const validation = validatePdfUrl(nextUrl)
    if (!validation.ok) {
      return {
        ok: false,
        code: validation.code,
        message: "PDF redirect points to an unsupported source.",
        status: 400,
        responseStatus: response.status,
        url: nextUrl
      }
    }
    currentUrl = nextUrl
  }

  return {
    ok: false,
    code: "pdf_fetch_failed",
    message: "PDF fetch failed.",
    status: 502,
    url: currentUrl
  }
}

function responseHeaders(response: Response, bodyLength: number) {
  const headers: Record<string, string> = {
    "Accept-Ranges": response.headers.get("accept-ranges") ?? "bytes",
    "Cache-Control": "no-store",
    "Content-Disposition": "inline",
    "Content-Length": String(bodyLength),
    "Content-Type": "application/pdf",
    "X-Content-Type-Options": "nosniff"
  }

  const contentRange = response.headers.get("content-range")
  if (contentRange) {
    headers["Content-Range"] = contentRange
  }

  return headers
}

function arrayBufferFromBytes(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.byteLength)
  new Uint8Array(buffer).set(bytes)
  return buffer
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

function validatePdfUrl(url: URL): PdfUrlValidation {
  if (isBlockedNetworkHost(url.hostname)) {
    return { ok: false, code: "blocked_pdf_host", message: "Blocked PDF host." }
  }

  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    !ALLOWED_PDF_HOSTS.has(normalizedHostname(url.hostname)) ||
    !isAllowedPaperPdfUrl(url)
  ) {
    return { ok: false, code: "unsupported_pdf_source", message: "Unsupported PDF source." }
  }

  return { ok: true }
}

function isRedirectResponse(response: Response) {
  return response.status >= 300 && response.status < 400
}

function pdfResponseContentType(response: Response) {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? ""
  if (contentType.includes("application/pdf")) {
    return "pdf"
  }
  if (contentType.includes("application/octet-stream")) {
    return "octet-stream"
  }
  return null
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

async function readLimitedResponseBody(response: Response, signal: AbortSignal): Promise<
  | { ok: true; bytes: Uint8Array; contentLength: number }
  | { ok: false; code: "pdf_too_large" | "pdf_timeout" | "pdf_fetch_failed"; message: string; status: number; contentLength?: number }
> {
  const reader = response.body?.getReader()
  if (!reader) {
    return { ok: false, code: "pdf_fetch_failed", message: "PDF fetch failed.", status: 502 }
  }

  const chunks: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await readResponseChunk(reader, signal)
      if (done) {
        break
      }
      if (!value) {
        continue
      }
      total += value.byteLength
      if (total > MAX_PDF_CONTENT_LENGTH_BYTES) {
        await reader.cancel()
        return {
          ok: false,
          code: "pdf_too_large",
          message: "PDF is too large.",
          status: 413,
          contentLength: total
        }
      }
      chunks.push(value)
    }
  } catch (error) {
    if (signal.aborted || isAbortError(error)) {
      void reader.cancel().catch(() => undefined)
      return { ok: false, code: "pdf_timeout", message: "PDF fetch timed out.", status: 504, contentLength: total }
    }
    return { ok: false, code: "pdf_fetch_failed", message: "PDF fetch failed.", status: 502, contentLength: total }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // The stream may still be settling after an abort-triggered cancel.
    }
  }

  const bytes = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }
  return { ok: true, bytes, contentLength: total }
}

function readResponseChunk(reader: ReadableStreamDefaultReader<Uint8Array>, signal: AbortSignal) {
  if (signal.aborted) {
    return Promise.reject(new DOMException("PDF fetch timed out.", "AbortError"))
  }
  return new Promise<ReadableStreamReadResult<Uint8Array>>((resolve, reject) => {
    const onAbort = () => {
      void reader.cancel().catch(() => undefined)
      reject(new DOMException("PDF fetch timed out.", "AbortError"))
    }
    signal.addEventListener("abort", onAbort, { once: true })
    reader.read().then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort))
  })
}

function requiresPdfMagicCheck(response: Response, contentType: "pdf" | "octet-stream") {
  if (contentType === "octet-stream") {
    return true
  }
  if (response.status === 200) {
    return true
  }
  const rangeStart = responseContentRangeStart(response)
  return rangeStart === undefined || rangeStart === 0
}

function hasPdfMagic(bytes: Uint8Array) {
  return (
    bytes.length >= 5 &&
    bytes[0] === 0x25 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x44 &&
    bytes[3] === 0x46 &&
    bytes[4] === 0x2d
  )
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

function responseContentRangeStart(response: Response) {
  const value = response.headers.get("content-range")
  if (!value) {
    return undefined
  }
  const match = value.match(/^bytes\s+(\d+)-\d+\/(?:\d+|\*)$/i)
  if (!match) {
    return undefined
  }
  const parsed = Number.parseInt(match[1], 10)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined
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
