import { afterEach, describe, expect, it, vi } from "vitest"
import { DashboardApiError, fetchDashboardOverview } from "@/lib/dashboard/api"
import type { DashboardOverview } from "@/types/dashboard"

describe("dashboard client api", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("fetches same-origin dashboard overview and unwraps the BFF envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        success: true,
        data: overview(),
        error: null
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    await expect(fetchDashboardOverview()).resolves.toMatchObject({ dataState: "ready" })
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/dashboard/overview",
      expect.objectContaining({
        method: "GET",
        cache: "no-store"
      })
    )
  })

  it("throws when the BFF envelope reports an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          success: false,
          data: null,
          error: { code: "dashboard_failed", message: "Dashboard failed" }
        })
      )
    )

    await expect(fetchDashboardOverview()).rejects.toBeInstanceOf(DashboardApiError)
  })
})

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json"
    }
  })
}

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
