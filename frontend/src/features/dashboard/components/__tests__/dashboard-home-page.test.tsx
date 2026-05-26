import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DashboardHomePage } from "@/features/dashboard/components/dashboard-home-page"
import { useDashboardOverview } from "@/features/dashboard/hooks/use-dashboard-overview"
import type { DashboardOverview } from "@/types/dashboard"

vi.mock("@/features/dashboard/hooks/use-dashboard-overview", () => ({
  useDashboardOverview: vi.fn()
}))

const mockedUseDashboardOverview = vi.mocked(useDashboardOverview)

describe("DashboardHomePage", () => {
  beforeEach(() => {
    mockedUseDashboardOverview.mockReset()
  })

  it("shows loading state", () => {
    mockedUseDashboardOverview.mockReturnValue({
      isLoading: true,
      isError: false,
      data: undefined,
      error: null,
      refetch: vi.fn()
    } as never)

    render(<DashboardHomePage />)

    expect(screen.getByText("Cross-board Intelligence")).toBeInTheDocument()
  })

  it("shows error state", () => {
    mockedUseDashboardOverview.mockReturnValue({
      isLoading: false,
      isError: true,
      data: undefined,
      error: new Error("BFF failed"),
      refetch: vi.fn()
    } as never)

    render(<DashboardHomePage />)

    expect(screen.getByText("Dashboard overview failed")).toBeInTheDocument()
    expect(screen.getByText("BFF failed")).toBeInTheDocument()
  })

  it("shows empty state", () => {
    mockedUseDashboardOverview.mockReturnValue({
      isLoading: false,
      isError: false,
      data: overview({ dataState: "empty", topStories: [] }),
      error: null,
      refetch: vi.fn()
    } as never)

    render(<DashboardHomePage />)

    expect(screen.getByText("No cross-board intelligence yet")).toBeInTheDocument()
  })

  it("shows fallback notice", () => {
    mockedUseDashboardOverview.mockReturnValue({
      isLoading: false,
      isError: false,
      data: overview({ dataState: "fallback", notices: ["Showing local fallback"] }),
      error: null,
      refetch: vi.fn()
    } as never)

    render(<DashboardHomePage />)

    expect(screen.getAllByText("Showing local fallback").length).toBeGreaterThan(0)
  })
})

function overview(partial: Partial<DashboardOverview> = {}): DashboardOverview {
  return {
    generatedAt: "2026-05-26T00:00:00Z",
    dataState: "ready",
    metrics: [{ id: "signals", label: "Today signals", value: 1, description: "Signals" }],
    brief: {
      title: "Brief",
      summary: "Summary",
      keyFindings: ["Finding"],
      coreJudgments: ["Judgment"],
      readingPath: [{ id: "story-news", label: "News story", href: "/news/news-1", board: "news" }],
      agentNotes: [],
      updatedAt: "2026-05-26T00:00:00Z"
    },
    topStories: [
      {
        id: "story-news",
        title: "News story",
        summary: "News summary",
        board: "news",
        href: "/news/news-1"
      }
    ],
    trendingTopics: [],
    techRadar: [],
    rightInsights: [],
    quality: {
      status: "passed",
      summary: "Quality passed"
    },
    notices: [],
    ...partial
  }
}
