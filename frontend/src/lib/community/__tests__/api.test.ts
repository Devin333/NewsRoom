import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet } from "@/lib/api/client"
import {
  CommunityApiError,
  fetchCommunitySignal,
  fetchCommunitySignals,
  fetchCommunityTopic,
  fetchCommunityTopics
} from "@/lib/community/api"

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

  it("uses Community Pulse signals list route with PRD query params", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        allItems: [],
        allFiltered: [],
        clusters: [],
        facets: { sources: [], topics: [], sentiments: [] },
        nextCursor: null,
        page: { items: [], total: 0, page: 1, pageSize: 12, hasNext: false, nextCursor: null },
        metrics: { totalSignals: 0, periodSignals: 0, activeSources: 0, hotSignals: 0, controversialSignals: 0 },
        dataState: "empty",
        source: "empty",
        notices: []
      }
    })

    await fetchCommunitySignals({
      q: "agent memory",
      source: "hackernews",
      sentiment: "mixed",
      topic: "agents",
      period: "weekly",
      sort: "controversial",
      limit: 12,
      cursor: "cursor-2"
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/community/signals?q=agent+memory&source=hackernews&sentiment=mixed&topic=agents&period=weekly&sort=controversial&limit=12&cursor=cursor-2",
      undefined
    )
  })

  it("uses Community Pulse signal detail route", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        signal: {
          id: "signal-1",
          slug: "signal-1",
          source: "hackernews",
          title: "Agent memory",
          url: "https://news.ycombinator.com/item?id=1",
          summary: "Public discussion",
          postedAt: "2026-05-25T00:00:00Z",
          collectedAt: "2026-05-25T00:00:00Z",
          sentiment: "mixed",
          topics: ["agents"],
          entities: [],
          heatScore: 80,
          controversyScore: 40,
          adoptionScore: 30,
          relatedPaperIds: [],
          relatedProjectIds: [],
          relatedNewsIds: []
        },
        relatedPapers: [],
        relatedProjects: [],
        relatedNews: [],
        evidenceLinks: []
      }
    })

    await fetchCommunitySignal("agent/memory")

    expect(apiGet).toHaveBeenCalledWith("/api/community/signals/agent%2Fmemory", undefined)
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
