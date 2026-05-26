import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet } from "@/lib/api/client"
import { fetchNewsDetail, fetchNewsList } from "@/lib/news/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
}))

describe("news API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
  })

  it("uses the /api/news BFF with supported filters", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        page: { items: [], total: 0, page: 2, pageSize: 8, hasNext: false },
        allItems: [],
        allFiltered: [],
        options: { categories: [], sourceTypes: [], credibility: ["high", "medium", "low"], qualityStatuses: ["passed", "review", "failed"] },
        dataState: "ready",
        source: "backend",
        notices: [],
      },
    })

    await fetchNewsList({
      keyword: "agent",
      dateRange: "today",
      sort: "heatScore",
      category: ["model-release"],
      sourceType: ["official_blog"],
      topic: "agents",
      page: 2,
      pageSize: 8,
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/news?q=agent&dateRange=today&category=model-release&sourceType=official_blog&topic=agents&sort=heatScore&page=2&pageSize=8",
      undefined
    )
  })

  it("builds detail payloads from the same list source", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        page: { items: [], total: 1, page: 1, pageSize: 1000, hasNext: false },
        allItems: [
          {
            id: "news-1",
            title: "Real AI News",
            summary: "A real board item.",
            url: "https://example.com/news",
            sourceName: "Example",
            sourceType: "official_blog",
            sourceUrl: "https://example.com/news",
            category: "model-release",
            tags: ["agents"],
            credibility: "high",
            evidenceRefs: [{ id: "ev-1", url: "https://example.com/news", sourceName: "Example", sourceType: "official_blog" }],
          },
        ],
        allFiltered: [],
        options: { categories: ["model-release"], sourceTypes: ["official_blog"], credibility: ["high", "medium", "low"], qualityStatuses: ["passed", "review", "failed"] },
        dataState: "ready",
        source: "backend",
        notices: [],
      },
    })

    const detail = await fetchNewsDetail("news-1")

    expect(apiGet).toHaveBeenCalledWith("/api/news?pageSize=1000", undefined)
    expect(detail.news?.title).toBe("Real AI News")
    expect(detail.evidence).toHaveLength(1)
  })
})
