import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CommunityPulsePage } from "@/features/community/components/community-pulse-page"
import { CommunityTopicDetail } from "@/features/community/components/community-topic-detail"
import { buildCommunityListResult } from "@/lib/community/community-filters"
import type { CommunityTopic, CommunityTopicDetail as CommunityTopicDetailType } from "@/types/community"

describe("Community Pulse UI", () => {
  it("renders an empty state when no community topics are available", () => {
    const result = buildCommunityListResult([], {}, { source: "empty" })

    render(<CommunityPulsePage result={result} filters={{}} onChange={vi.fn()} />)

    expect(screen.getByText("暂无社区话题")).toBeInTheDocument()
  })

  it("renders community topic cards and forwards filter interactions", () => {
    const onChange = vi.fn()
    const result = buildCommunityListResult([sampleTopic()], {}, { source: "artifact" })

    render(<CommunityPulsePage result={result} filters={{}} onChange={onChange} />)

    expect(screen.getByText("Agent memory debate")).toBeInTheDocument()
    expect(screen.getByText("Memory paper")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "正面" }))
    expect(onChange).toHaveBeenCalledWith({ sentiment: "positive" })

    fireEvent.change(screen.getByRole("textbox", { name: "搜索社区话题" }), {
      target: { value: "latency" }
    })
    fireEvent.click(screen.getByRole("button", { name: "搜索" }))
    expect(onChange).toHaveBeenLastCalledWith({ q: "latency" })
  })

  it("renders Community Pulse detail sections from public data", () => {
    render(<CommunityTopicDetail topic={sampleDetail()} />)

    expect(screen.getByText("高热讨论")).toBeInTheDocument()
    expect(screen.getByText("代表性评论")).toBeInTheDocument()
    expect(screen.getByText("Memory paper")).toBeInTheDocument()
    expect(screen.getByText("打开讨论")).toBeInTheDocument()
  })
})

function sampleTopic(): CommunityTopic {
  return {
    id: "topic-1",
    slug: "agent-memory-debate",
    title: "Agent memory debate",
    summary: "Developers discuss memory latency, reliability, and cost.",
    sourceType: "hackernews",
    sourceName: "Hacker News",
    sourceUrl: "https://news.ycombinator.com/item?id=1",
    publishedAt: "2026-05-24T00:00:00Z",
    lastActivityAt: "2026-05-25T00:00:00Z",
    sentiment: "mixed",
    heatScore: 88,
    controversyScore: 42,
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
    ]
  }
}

function sampleDetail(): CommunityTopicDetailType {
  return {
    ...sampleTopic(),
    sourceDistribution: [{ sourceType: "hackernews", count: 1 }],
    topDiscussions: [
      {
        id: "discussion-1",
        title: "Agent memory debate",
        sourceType: "hackernews",
        sourceName: "Hacker News",
        url: "https://news.ycombinator.com/item?id=1",
        excerpt: "Public discussion excerpt.",
        publishedAt: "2026-05-24T00:00:00Z"
      }
    ],
    representativeComments: [
      {
        id: "comment-1",
        excerpt: "Latency is the main blocker.",
        sentiment: "mixed",
        sourceName: "Hacker News"
      }
    ],
    timeline: [
      {
        id: "timeline-1",
        label: "发布",
        timestamp: "2026-05-24T00:00:00Z"
      }
    ],
    notices: []
  }
}
