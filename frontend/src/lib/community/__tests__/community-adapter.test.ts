import { describe, expect, it } from "vitest"
import { adaptCommunityBoardPayload } from "@/lib/community/community-adapter"
import { buildCommunityListResult, filterCommunityTopics } from "@/lib/community/community-filters"
import type { CommunityTopic } from "@/types/community"

describe("community board adapter", () => {
  it("maps board output cards to public Community Pulse topics and strips private fields", () => {
    const result = adaptCommunityBoardPayload({
      board_type: "community_pulse",
      generated_at: "2026-05-25T00:00:00Z",
      cards: [
        {
          card_id: "card-agent",
          title: "Agent memory debate",
          summary: "Developers discuss memory latency and reliability.",
          published_at: "2026-05-24T00:00:00Z",
          metadata: {
            raw_payload: { token: "hidden" },
            secret: "hidden"
          },
          metrics: [
            { label: "Heat", value: 0.8 },
            { label: "Sentiment Divergence", value: 0.4 }
          ],
          badges: [{ label: "hot topic" }],
          evidence_refs: [
            {
              external_id: "evidence-1",
              source_name: "Hacker News",
              source_type: "hackernews",
              source_url: "http://news.ycombinator.com/item?id=1",
              content_excerpt: "Public excerpt only.",
              raw_content: "private full thread"
            }
          ],
          related_refs: [
            { object_type: "paper", object_id: "paper-1", label: "Memory paper" },
            { object_type: "github_project", object_id: "project-1", label: "Memory repo" },
            { object_type: "ai_news", object_id: "news-1", label: "Memory launch" }
          ]
        }
      ],
      detail_pages: []
    })

    expect(result.topics).toHaveLength(1)
    expect(result.topics[0]).toMatchObject({
      slug: "agent-memory-debate-2026-05-24t00-00-00z",
      sourceType: "hackernews",
      sentiment: "unknown",
      heatScore: 80,
      controversyScore: 40,
      commentCount: undefined,
      sourceUrl: undefined
    })
    expect(result.topics[0].relatedPapers?.[0].title).toBe("Memory paper")
    expect(result.topics[0].relatedProjects?.[0].name).toBe("Memory repo")
    expect(result.topics[0].relatedNews?.[0].title).toBe("Memory launch")
    expect(JSON.stringify(result)).not.toContain("raw_payload")
    expect(JSON.stringify(result)).not.toContain("raw_content")
    expect(JSON.stringify(result)).not.toContain("token")
    expect(JSON.stringify(result)).not.toContain("secret")
  })

  it("reads nested backend artifacts, provenance refs, and board-specific score fields", () => {
    const result = adaptCommunityBoardPayload({
      content: {
        board_output: {
          board_type: "community_pulse",
          generated_at: "2026-05-26T00:00:00Z",
          cards: [
            {
              card_id: "card-backend",
              title: "Backend community topic",
              summary: "Public backend summary.",
              published_at: "2026-05-25T00:00:00Z",
              ranking_features: {
                board_specific_features: {
                  sentiment_divergence: "0.22",
                  adoption_score: 0.33
                }
              },
              score: {
                factors: [{ name: "discussion_heat", value: "0.91" }]
              },
              provenance: {
                source_refs: [
                  {
                    external_id: "reddit-1",
                    source_name: "Reddit",
                    source_type: "reddit",
                    source_url: "https://reddit.com/r/LocalLLaMA/comments/1",
                    content_excerpt: "Public provenance excerpt."
                  }
                ]
              }
            }
          ],
          detail_pages: [{ title: "Backend community topic", summary: "Backend detail summary." }]
        }
      }
    })

    expect(result.topics[0]).toMatchObject({
      sourceType: "reddit",
      sourceUrl: "https://reddit.com/r/LocalLLaMA/comments/1",
      heatScore: 91,
      controversyScore: 22,
      adoptionScore: 33,
      sentiment: "unknown",
      commentCount: undefined
    })
    expect(result.details[0]?.summary).toBe("Backend detail summary.")
  })

  it("filters and sorts topics by query, source, sentiment, topic, and score", () => {
    const topics: CommunityTopic[] = [
      topic({ id: "1", title: "Agent memory", sourceType: "hackernews", sentiment: "mixed", heatScore: 60, tags: ["agents"] }),
      topic({ id: "2", title: "RAG retrieval", sourceType: "reddit", sentiment: "negative", heatScore: 30, tags: ["rag"] }),
      topic({ id: "3", title: "Coding agent adoption", sourceType: "github_discussion", sentiment: "positive", heatScore: 90, tags: ["coding"] })
    ]

    expect(filterCommunityTopics(topics, { q: "memory" }).map((item) => item.id)).toEqual(["1"])
    expect(filterCommunityTopics(topics, { source: "reddit" }).map((item) => item.id)).toEqual(["2"])
    expect(filterCommunityTopics(topics, { sentiment: "positive" }).map((item) => item.id)).toEqual(["3"])
    expect(filterCommunityTopics(topics, { topic: "agents" }).map((item) => item.id)).toEqual(["3", "1"])
    expect(filterCommunityTopics(topics, { sort: "trending" }).map((item) => item.id)).toEqual(["3", "1", "2"])

    const list = buildCommunityListResult(topics, { page: 1 }, { source: "artifact" })
    expect(list.metrics).toMatchObject({ totalTopics: 3, activeSources: 3, positiveCount: 1, negativeCount: 1, mixedCount: 1 })
  })
})

function topic(partial: Partial<CommunityTopic> & Pick<CommunityTopic, "id" | "title" | "sourceType" | "sentiment">): CommunityTopic {
  return {
    slug: partial.id,
    summary: `${partial.title} summary`,
    tags: [],
    ...partial
  }
}
