import { describe, expect, it } from "vitest"
import {
  buildCommunitySignalDetailResult,
  buildCommunitySignalListResult,
  communitySignalFromTopic,
  communitySignalSource,
  communitySignalSentiment,
  filterCommunitySignals,
  paginateCommunitySignals
} from "@/lib/community/community-signals"
import type { CommunitySignal, CommunityTopic, CommunityTopicDetail } from "@/types/community"

const NOW = Date.parse("2026-05-26T00:00:00Z")

describe("community signals", () => {
  it("derives PRD community signals from public topic and detail fields", () => {
    const signal = communitySignalFromTopic(topic({ id: "agent", title: "Agent memory debate" }), detail("agent"))

    expect(signal).toMatchObject({
      id: "agent",
      source: "hackernews",
      sentiment: "mixed",
      title: "Agent memory debate",
      url: "https://news.ycombinator.com/item?id=1",
      summary: "Detailed public summary.",
      score: 75,
      comments: 18,
      heatScore: 88,
      controversyScore: 42,
      adoptionScore: 35,
      relatedPaperIds: ["paper-1"],
      relatedProjectIds: ["project-1"],
      relatedNewsIds: ["news-1"]
    })
    expect(JSON.stringify(signal)).not.toMatch(/token|secret|raw_content|raw_payload/i)
  })

  it("normalizes source and sentiment values to the PRD enum", () => {
    expect(communitySignalSource("github_discussion", "GitHub Discussion")).toBe("github")
    expect(communitySignalSource("other", "GitHub Trending", "https://github.com/trending")).toBe("github_trending")
    expect(communitySignalSource("other", "X", "https://x.com/example")).toBe("x")
    expect(communitySignalSource("devto", "Personal blog")).toBe("blog")
    expect(communitySignalSource("other", "Vendor site")).toBe("other")
    expect(communitySignalSentiment("unknown", 0)).toBe("neutral")
    expect(communitySignalSentiment("mixed", 75)).toBe("controversial")
  })

  it("filters by source, topic, sentiment, period, query and sorts by PRD modes", () => {
    const items = [
      signal({ id: "hot", source: "hackernews", sentiment: "mixed", heatScore: 90, controversyScore: 30, adoptionScore: 10, postedAt: "2026-05-25T12:00:00Z", topics: ["agents"] }),
      signal({ id: "new", source: "reddit", sentiment: "negative", heatScore: 40, controversyScore: 80, adoptionScore: 20, postedAt: "2026-05-25T23:00:00Z", topics: ["rag"] }),
      signal({ id: "adopted", source: "github", sentiment: "positive", heatScore: 60, controversyScore: 10, adoptionScore: 95, postedAt: "2026-04-20T00:00:00Z", topics: ["coding"] })
    ]

    expect(filterCommunitySignals(items, { source: "reddit" }, NOW).map((item) => item.id)).toEqual(["new"])
    expect(filterCommunitySignals(items, { sentiment: "positive" }, NOW).map((item) => item.id)).toEqual(["adopted"])
    expect(filterCommunitySignals(items, { topic: "agent" }, NOW).map((item) => item.id)).toEqual(["hot"])
    expect(filterCommunitySignals(items, { q: "RAG" }, NOW).map((item) => item.id)).toEqual(["new"])
    expect(filterCommunitySignals(items, { period: "weekly" }, NOW).map((item) => item.id)).toEqual(["hot", "new"])
    expect(filterCommunitySignals(items, { sort: "newest" }, NOW).map((item) => item.id)).toEqual(["new", "hot", "adopted"])
    expect(filterCommunitySignals(items, { sort: "controversial" }, NOW).map((item) => item.id)).toEqual(["new", "hot", "adopted"])
    expect(filterCommunitySignals(items, { sort: "adoption" }, NOW).map((item) => item.id)).toEqual(["adopted", "new", "hot"])
  })

  it("paginates with cursor and legacy page parameters", () => {
    const items = Array.from({ length: 5 }, (_, index) => signal({ id: `signal-${index}` }))

    const firstPage = paginateCommunitySignals(items, { limit: 2 })
    expect(firstPage.items.map((item) => item.id)).toEqual(["signal-0", "signal-1"])
    expect(firstPage.nextCursor).toBe("Mg")

    const secondPage = paginateCommunitySignals(items, { limit: 2, cursor: firstPage.nextCursor ?? undefined })
    expect(secondPage.items.map((item) => item.id)).toEqual(["signal-2", "signal-3"])

    const legacyPage = paginateCommunitySignals(items, { page: 2, pageSize: 2 })
    expect(legacyPage.items.map((item) => item.id)).toEqual(["signal-2", "signal-3"])
  })

  it("builds facets, metrics, debate clusters and detail results without inventing arguments", () => {
    const list = buildCommunitySignalListResult(
      [topic({ id: "agent", title: "Agent memory debate" })],
      [detail("agent")],
      {},
      { source: "artifact", now: NOW }
    )

    expect(list.items).toHaveLength(1)
    expect(list.facets.sources).toContainEqual({ source: "hackernews", label: "Hacker News", count: 1 })
    expect(list.facets.topics).toContainEqual({ topic: "agents", label: "agents", count: 1 })
    expect(list.metrics).toMatchObject({ totalSignals: 1, periodSignals: 1, hotSignals: 1, controversialSignals: 0 })
    expect(list.clusters[0]).toMatchObject({
      title: "Agent memory debate",
      positiveArguments: [],
      negativeArguments: [],
      neutralFacts: ["Latency is the main blocker.", "Public excerpt only."]
    })

    const detailResult = buildCommunitySignalDetailResult([topic({ id: "agent" })], [detail("agent")], "agent")
    expect(detailResult?.signal.id).toBe("agent")
    expect(detailResult?.relatedPapers[0]?.title).toBe("Memory paper")
    expect(detailResult?.evidenceLinks[0]?.url).toBe("https://news.ycombinator.com/item?id=1")
  })
})

function topic(partial: Partial<CommunityTopic> = {}): CommunityTopic {
  return {
    id: "topic-1",
    slug: "agent-memory-debate",
    title: "Agent memory debate",
    summary: "Developers discuss memory latency and reliability.",
    sourceType: "hackernews",
    sourceName: "Hacker News",
    sourceUrl: "https://news.ycombinator.com/item?id=1",
    publishedAt: "2026-05-25T12:00:00Z",
    lastActivityAt: "2026-05-25T13:00:00Z",
    sentiment: "mixed",
    heatScore: 88,
    controversyScore: 42,
    adoptionScore: 35,
    commentCount: 18,
    upvoteCount: 75,
    tags: ["agents"],
    relatedPapers: [{ id: "paper-1", title: "Memory paper" }],
    relatedProjects: [{ id: "project-1", name: "Memory repo" }],
    relatedNews: [{ id: "news-1", title: "Memory launch" }],
    evidenceRefs: [
      {
        id: "evidence-1",
        sourceName: "Hacker News",
        sourceType: "hackernews",
        url: "https://news.ycombinator.com/item?id=1",
        excerpt: "Public excerpt only."
      }
    ],
    ...partial
  }
}

function detail(id: string): CommunityTopicDetail {
  return {
    ...topic({ id }),
    sourceDistribution: [{ sourceType: "hackernews", count: 1 }],
    topDiscussions: [],
    representativeComments: [
      {
        id: "comment-1",
        excerpt: "Latency is the main blocker.",
        sentiment: "mixed",
        sourceName: "Hacker News"
      }
    ],
    timeline: [],
    summary: "Detailed public summary.",
    notices: []
  }
}

function signal(partial: Partial<CommunitySignal> & Pick<CommunitySignal, "id">): CommunitySignal {
  const { id, slug = id, ...rest } = partial
  return {
    id,
    slug,
    source: "hackernews",
    title: id,
    url: "https://example.com",
    summary: `${id} summary`,
    postedAt: "2026-05-25T00:00:00Z",
    collectedAt: "2026-05-25T00:00:00Z",
    sentiment: "neutral",
    topics: [],
    entities: [],
    heatScore: 0,
    controversyScore: 0,
    adoptionScore: 0,
    relatedPaperIds: [],
    relatedProjectIds: [],
    relatedNewsIds: [],
    ...rest
  }
}
