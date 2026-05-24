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

  const response = await fetch(parsedUrl.toString(), {
    headers: {
      "User-Agent": "NewsRoomResearch/0.1 (+https://localhost)"
    },
    cache: "no-store"
  })

  if (!response.ok || !response.body || !isPdfResponse(parsedUrl, response)) {
    return NextResponse.json({ error: "pdf fetch failed" }, { status: 502 })
  }

  return new NextResponse(response.body, {
    headers: {
      "Cache-Control": "public, max-age=3600",
      "Content-Disposition": "inline",
      "Content-Type": response.headers.get("content-type") ?? "application/pdf"
    },
    status: 200
  })
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
