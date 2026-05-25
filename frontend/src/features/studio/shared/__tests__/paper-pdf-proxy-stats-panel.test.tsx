import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperPdfProxyStatsPanel } from "@/features/studio/shared/components/paper-pdf-proxy-stats-panel"
import { fetchPaperPdfProxyStats } from "@/features/studio/shared/api/pdf-proxy-stats-api"
import type { PaperPdfProxyStats } from "@/types/studio"

vi.mock("@/features/studio/shared/api/pdf-proxy-stats-api", () => ({
  fetchPaperPdfProxyStats: vi.fn()
}))

const readyStats: PaperPdfProxyStats = {
  dataState: "ready",
  windowHours: 24,
  generatedAt: "2026-05-25T01:00:00.000Z",
  windowStartedAt: "2026-05-24T01:00:00.000Z",
  windowEndedAt: "2026-05-25T01:00:00.000Z",
  totalRequests: 12,
  successCount: 9,
  errorCount: 3,
  timeoutCount: 1,
  oversizedCount: 1,
  blockedCount: 1,
  invalidContentTypeCount: 0,
  upstreamFailureCount: 0,
  errorsByCode: {
    pdf_timeout: 1,
    pdf_too_large: 1,
    blocked_pdf_host: 1
  },
  topHosts: [{ host: "arxiv.org", requestCount: 8, errorCount: 1, avgDurationMs: 120 }],
  recentErrors: [
    {
      timestamp: "2026-05-25T00:58:00.000Z",
      host: "arxiv.org",
      path: "/pdf/2605.00001.pdf",
      code: "pdf_timeout",
      status: 504,
      durationMs: 10_000
    }
  ],
  notices: []
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      }
    }
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PaperPdfProxyStatsPanel />
    </QueryClientProvider>
  )
}

describe("PaperPdfProxyStatsPanel", () => {
  beforeEach(() => {
    vi.mocked(fetchPaperPdfProxyStats).mockReset()
  })

  it("renders loading state", () => {
    vi.mocked(fetchPaperPdfProxyStats).mockReturnValue(new Promise(() => undefined))

    renderPanel()

    expect(screen.getByText("Loading PDF proxy request statistics.")).toBeInTheDocument()
  })

  it("renders error state", async () => {
    vi.mocked(fetchPaperPdfProxyStats).mockRejectedValue(new Error("stats down"))

    renderPanel()

    expect(await screen.findByText("PDF proxy stats unavailable")).toBeInTheDocument()
    expect(screen.getByText("stats down")).toBeInTheDocument()
  })

  it("renders empty state", async () => {
    vi.mocked(fetchPaperPdfProxyStats).mockResolvedValue({
      ...readyStats,
      dataState: "empty",
      totalRequests: 0,
      successCount: 0,
      errorCount: 0,
      topHosts: [],
      recentErrors: [],
      notices: ["No PDF proxy events were recorded for this window."]
    })

    renderPanel()

    expect(await screen.findByText("No PDF proxy events")).toBeInTheDocument()
  })

  it("renders ready stats", async () => {
    vi.mocked(fetchPaperPdfProxyStats).mockResolvedValue(readyStats)

    renderPanel()

    expect(await screen.findByText("Requests")).toBeInTheDocument()
    expect(screen.getByText("12")).toBeInTheDocument()
    expect(screen.getByText("pdf_timeout (1)")).toBeInTheDocument()
    expect(screen.getAllByText("arxiv.org").length).toBeGreaterThan(0)
    expect(screen.getByText("pdf_timeout")).toBeInTheDocument()
  })
})
