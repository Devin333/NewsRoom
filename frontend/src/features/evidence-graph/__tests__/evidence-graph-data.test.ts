import { describe, expect, it } from "vitest"
import { buildEvidenceGraphResponse, type EvidenceGraphLoadedSources } from "@/features/evidence-graph/evidence-graph-data"
import type { Paper } from "@/lib/papers/types"
import type { CommunityTopic } from "@/types/community"
import type { NewsItem } from "@/types/news"
import type { ProjectItem } from "@/types/projects"

const paper: Paper = {
  id: "paper-agent-memory",
  slug: "paper-agent-memory",
  title: "Agent Memory Architectures",
  abstractSnippet: "A paper about durable agent memory and retrieval.",
  authors: ["NewsRoom Test"],
  publishedAt: "2026-05-24T00:00:00Z",
  venue: "arXiv",
  tags: ["Agent Memory", "retrieval"],
  taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
  methodRefs: [{ id: "method-memory", slug: "memory", name: "Memory" }],
  paperUrl: "https://arxiv.org/abs/2605.00001",
  repoUrl: "https://github.com/example/agent-memory",
  evidenceRefs: [{ sourceName: "arXiv", sourceType: "arxiv", url: "https://arxiv.org/abs/2605.00001" }],
  isPublished: true,
}

const project: ProjectItem = {
  id: "project-agent-memory",
  slug: "example-agent-memory",
  name: "agent-memory",
  fullName: "example/agent-memory",
  description: "Open-source implementation for durable agent memory.",
  repoUrl: "https://github.com/example/agent-memory",
  stars: 1200,
  starGrowth7d: 80,
  scores: { trendScore: 88, evidenceScore: 3, activityScore: 80 },
  categoryRefs: [{ category: "memory", label: "Memory" }],
  categories: ["memory"],
  tags: ["Agent Memory"],
  topics: ["Agent Memory", "agents"],
  updatedAt: "2026-05-25T00:00:00Z",
  sourceRefs: [{ url: "https://github.com/example/agent-memory", sourceName: "GitHub", sourceType: "github" }],
  relatedPapers: [{ title: "Agent Memory Architectures", url: "https://arxiv.org/abs/2605.00001" }],
  relatedNews: [],
  relatedCommunityTopics: [],
  relationCounts: { papers: 1, news: 0, community: 0 },
}

const news: NewsItem = {
  id: "news-agent-memory",
  title: "Agent Memory adoption signal",
  summary: "Teams are testing durable memory for agents.",
  sourceName: "Official Engineering Blog",
  sourceType: "official_blog",
  sourceUrl: "https://openai.com/news/agent-memory",
  publishedAt: "2026-05-25T12:00:00Z",
  category: "product-update",
  tags: ["Agent Memory"],
  heatScore: 82,
  qualityScore: 84,
  credibility: "high",
  topicName: "Agent Memory",
  relatedProjects: [{ id: "project-agent-memory", title: "agent-memory", url: "https://github.com/example/agent-memory" }],
  evidenceRefs: [{ id: "evidence-news", url: "https://openai.com/news/agent-memory", sourceName: "Official Engineering Blog" }],
}

const community: CommunityTopic = {
  id: "community-agent-memory",
  slug: "agent-memory-discussion",
  title: "Agent Memory discussion",
  summary: "Developers compare memory implementations for long-running agents.",
  sourceType: "hackernews",
  sourceName: "Hacker News",
  sourceUrl: "https://news.ycombinator.com/item?id=1",
  publishedAt: "2026-05-25T18:00:00Z",
  sentiment: "mixed",
  heatScore: 76,
  tags: ["Agent Memory"],
  relatedProjects: [{ id: "project-agent-memory", name: "agent-memory", url: "https://github.com/example/agent-memory" }],
}

const sources: EvidenceGraphLoadedSources = {
  papers: [paper],
  projects: [project],
  news: [news],
  community: [community],
  reports: [
    {
      report_id: "report-agent-memory",
      title: "Agent Memory weekly brief",
      status: "published",
      created_at: "2026-05-25T20:00:00Z",
      workflow_id: "weekly",
    },
  ],
  sourceStates: [
    { board: "papers", state: "ready", source: "test", count: 1, notices: [] },
    { board: "projects", state: "ready", source: "test", count: 1, notices: [] },
    { board: "news", state: "ready", source: "test", count: 1, notices: [] },
    { board: "community", state: "ready", source: "test", count: 1, notices: [] },
    { board: "reports", state: "ready", source: "test", count: 1, notices: [] },
  ],
}

describe("evidence graph data builder", () => {
  it("builds a topic graph with cross-board counts, scores, timeline, and relation edges", () => {
    const graph = buildEvidenceGraphResponse(sources, { topic: "Agent Memory", depth: 3, limit: 20 })

    expect(graph.summary.topicName).toBe("Agent Memory")
    expect(graph.summary.paperCount).toBe(1)
    expect(graph.summary.projectCount).toBe(1)
    expect(graph.summary.newsCount).toBe(1)
    expect(graph.summary.communitySignalCount).toBe(1)
    expect(graph.summary.evidenceScore).toBeGreaterThan(0)
    expect(graph.summary.trendScore).toBeGreaterThan(0)
    expect(graph.summary.confidenceScore).toBeGreaterThan(0)
    expect(graph.edges.some((edge) => edge.type === "implements")).toBe(true)
    expect(graph.edges.some((edge) => edge.type === "mentions")).toBe(true)
    expect(graph.timeline.length).toBeGreaterThanOrEqual(4)
  })

  it("applies node type and limit filters without dropping the topic node", () => {
    const graph = buildEvidenceGraphResponse(sources, { topic: "Agent Memory", nodeTypes: ["paper"], limit: 1 })

    expect(graph.nodes.some((node) => node.type === "topic")).toBe(true)
    expect(graph.nodes.filter((node) => node.type !== "topic")).toHaveLength(1)
    expect(graph.nodes.find((node) => node.type === "paper")).toBeTruthy()
    expect(graph.summary.paperCount).toBe(1)
    expect(graph.summary.projectCount).toBe(0)
  })

  it("returns an empty graph state without fake evidence", () => {
    const graph = buildEvidenceGraphResponse(
      {
        papers: [],
        projects: [],
        news: [],
        community: [],
        reports: [],
        sourceStates: sources.sourceStates.map((state) => ({ ...state, count: 0, state: "empty" })),
      },
      { topic: "Missing Topic" }
    )

    expect(graph.nodes).toHaveLength(1)
    expect(graph.edges).toHaveLength(0)
    expect(graph.summary.paperCount).toBe(0)
    expect(graph.summary.summary).toContain("Missing Topic")
  })
})
