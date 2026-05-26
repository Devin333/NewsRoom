import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { useDashboardOverview } from "@/features/dashboard/hooks/use-dashboard-overview"
import { fetchDashboardOverview } from "@/lib/dashboard/api"
import type { DashboardOverview } from "@/types/dashboard"

vi.mock("@/lib/dashboard/api", () => ({
  fetchDashboardOverview: vi.fn()
}))

const mockedFetchDashboardOverview = vi.mocked(fetchDashboardOverview)

describe("useDashboardOverview", () => {
  beforeEach(() => {
    mockedFetchDashboardOverview.mockReset()
  })

  it("uses fetchDashboardOverview as the query function", async () => {
    mockedFetchDashboardOverview.mockResolvedValueOnce(overview())
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false
        }
      }
    })

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useDashboardOverview(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockedFetchDashboardOverview).toHaveBeenCalledTimes(1)
  })
})

function overview(): DashboardOverview {
  return {
    generatedAt: "2026-05-26T00:00:00Z",
    dataState: "ready",
    metrics: [],
    brief: {
      title: "Brief",
      summary: "Summary",
      keyFindings: [],
      coreJudgments: [],
      readingPath: [],
      agentNotes: [],
      updatedAt: "2026-05-26T00:00:00Z"
    },
    topStories: [],
    trendingTopics: [],
    techRadar: [],
    rightInsights: [],
    quality: {
      status: "passed",
      summary: "Quality passed"
    }
  }
}
