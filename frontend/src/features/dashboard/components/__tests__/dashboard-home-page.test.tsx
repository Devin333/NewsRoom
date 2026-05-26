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

    expect(screen.getByText("今日情报")).toBeInTheDocument()
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

    expect(screen.getByText("首页情报加载失败")).toBeInTheDocument()
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

    expect(screen.getByText("暂无 cross-board 情报")).toBeInTheDocument()
  })

  it("shows partial notice while keeping available content", () => {
    mockedUseDashboardOverview.mockReturnValue({
      isLoading: false,
      isError: false,
      data: overview({ dataState: "partial", notices: ["已从本地 productized board 产物生成部分 cross-board 首页。"] }),
      error: null,
      refetch: vi.fn()
    } as never)

    render(<DashboardHomePage />)

    expect(screen.getAllByText("部分数据").length).toBeGreaterThan(0)
    expect(screen.getByText("趋势归因可能不完整")).toBeInTheDocument()
    expect(screen.getByText("跨板块重点线索")).toBeInTheDocument()
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
    metrics: [{ id: "signals", label: "今日信号", value: 1, description: "信号" }],
    brief: {
      title: "今日简报",
      summary: "摘要",
      keyFindings: ["发现"],
      coreJudgments: ["判断"],
      readingPath: [{ id: "story-news", label: "新闻线索", href: "/news/news-1", board: "news" }],
      agentNotes: [],
      updatedAt: "2026-05-26T00:00:00Z"
    },
    topStories: [
      {
        id: "story-news",
        title: "新闻线索",
        summary: "新闻摘要",
        board: "news",
        href: "/news/news-1"
      }
    ],
    trendingTopics: [],
    techRadar: [],
    rightInsights: [],
    quality: {
      status: "passed",
      summary: "质量通过"
    },
    notices: [],
    ...partial
  }
}
