import { NextRequest, NextResponse } from "next/server"

export const dynamic = "force-dynamic"

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

export async function GET(request: NextRequest) {
  const url = request.nextUrl.searchParams.get("url")
  if (!url) {
    return NextResponse.json({ error: "missing pdf url" }, { status: 400 })
  }

  let parsedUrl: URL
  try {
    parsedUrl = new URL(url)
  } catch {
    return NextResponse.json({ error: "invalid pdf url" }, { status: 400 })
  }

  if (parsedUrl.protocol !== "https:" || !ALLOWED_PDF_HOSTS.has(parsedUrl.hostname) || !isAllowedPaperPdfUrl(parsedUrl)) {
    return NextResponse.json({ error: "unsupported pdf source" }, { status: 400 })
  }

  const range = request.headers.get("range")
  const response = await fetch(parsedUrl.toString(), {
    headers: {
      "User-Agent": "NewsRoomResearch/0.1 (+https://localhost)",
      ...(range ? { Range: range } : {})
    },
    cache: "no-store"
  })

  if (!isSuccessfulPdfResponse(response) || !response.body || !isPdfResponse(parsedUrl, response)) {
    return NextResponse.json({ error: "pdf fetch failed" }, { status: 502 })
  }

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
  const host = url.hostname.toLowerCase().replace(/^www\./, "")
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
