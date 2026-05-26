import { beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { GET as getCommunityListRoute } from "@/app/api/community/route"
import { GET as getCommunityTopicRoute } from "@/app/api/community/topics/[slug]/route"
import { getCommunityList, getCommunityTopic } from "@/lib/community/server-data"

vi.mock("@/lib/community/server-data", () => ({
  getCommunityList: vi.fn(),
  getCommunityTopic: vi.fn()
}))

describe("community BFF routes", () => {
  beforeEach(() => {
    vi.mocked(getCommunityList).mockReset()
    vi.mocked(getCommunityTopic).mockReset()
  })

  it("returns Community Pulse list data with parsed filters", async () => {
    vi.mocked(getCommunityList).mockResolvedValueOnce({
      topics: [],
      allTopics: [],
      page: { items: [], total: 0, page: 2, pageSize: 12, hasNext: false },
      metrics: { totalTopics: 0, activeSources: 0, positiveCount: 0, negativeCount: 0, mixedCount: 0 },
      options: { sources: [], sentiments: [], topics: [], tags: [] },
      dataState: "empty",
      source: "empty",
      notices: []
    })

    const response = await getCommunityListRoute(
      new NextRequest(
        "http://localhost/api/community?q=agent&source=hackernews&sentiment=mixed&sort=controversial&topic=agents&page=2&pageSize=12"
      )
    )
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.success).toBe(true)
    expect(getCommunityList).toHaveBeenCalledWith({
      q: "agent",
      source: "hackernews",
      sentiment: "mixed",
      sort: "controversial",
      topic: "agents",
      page: 2,
      pageSize: 12
    })
  })

  it("returns community topic details", async () => {
    vi.mocked(getCommunityTopic).mockResolvedValueOnce({
      id: "topic-1",
      slug: "agent-memory",
      title: "Agent memory",
      summary: "Public topic summary.",
      sourceType: "hackernews",
      sentiment: "mixed",
      tags: [],
      sourceDistribution: [],
      topDiscussions: [],
      representativeComments: [],
      timeline: [],
      notices: []
    })

    const response = await getCommunityTopicRoute(new NextRequest("http://localhost/api/community/topics/agent-memory"), {
      params: { slug: "agent-memory" }
    })
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.success).toBe(true)
    expect(payload.data.topic.title).toBe("Agent memory")
  })

  it("returns not found for missing community topic details", async () => {
    vi.mocked(getCommunityTopic).mockResolvedValueOnce(undefined)

    const response = await getCommunityTopicRoute(new NextRequest("http://localhost/api/community/topics/missing"), {
      params: { slug: "missing" }
    })
    const payload = await response.json()

    expect(response.status).toBe(404)
    expect(payload.success).toBe(false)
    expect(payload.error.code).toBe("community_topic_not_found")
  })
})
