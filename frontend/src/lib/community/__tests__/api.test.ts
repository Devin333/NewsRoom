import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet } from "@/lib/api/client"
import { CommunityApiError, fetchCommunityTopic, fetchCommunityTopics } from "@/lib/community/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn()
}))

describe("community API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
  })

  it("uses Community Pulse BFF list route with encoded query params", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        topics: [],
        allTopics: [],
        page: { items: [], total: 0, page: 2, pageSize: 8, hasNext: false },
        metrics: { totalTopics: 0, activeSources: 0, positiveCount: 0, negativeCount: 0, mixedCount: 0 },
        options: { sources: [], sentiments: [], topics: [], tags: [] },
        dataState: "empty",
        source: "empty",
        notices: []
      }
    })

    await fetchCommunityTopics({ q: "agent memory", source: "hackernews", sort: "newest", page: 2 })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/community?q=agent+memory&source=hackernews&sort=newest&page=2",
      undefined
    )
  })

  it("uses Community Pulse BFF topic detail route", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        topic: {
          id: "topic-1",
          slug: "agent-memory",
          title: "Agent memory",
          summary: "Public discussion",
          sourceType: "hackernews",
          sentiment: "unknown",
          tags: [],
          sourceDistribution: [],
          topDiscussions: [],
          representativeComments: [],
          timeline: [],
          notices: []
        }
      }
    })

    await fetchCommunityTopic("agent/memory")

    expect(apiGet).toHaveBeenCalledWith("/api/community/topics/agent%2Fmemory", undefined)
  })

  it("throws normalized community API errors from unsuccessful envelopes", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: false,
      error: {
        code: "community_topic_not_found",
        message: "Missing topic"
      }
    })

    const request = fetchCommunityTopic("missing")
    await expect(request).rejects.toMatchObject({
      name: "CommunityApiError",
      code: "community_topic_not_found",
      message: "Missing topic"
    })
    await expect(request).rejects.toBeInstanceOf(CommunityApiError)
  })
})
