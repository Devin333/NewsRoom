import { describe, expect, it } from "vitest"
import {
  buildPaperPortalMetrics,
  deriveTopPaperDomains,
  deriveTrendingPaperDomains
} from "@/lib/papers/metrics"
import type { Paper, TaskRef } from "@/lib/papers/types"

const agents: TaskRef = { id: "task-agents", slug: "agents", name: "Agents" }
const reasoning: TaskRef = { id: "task-reasoning", slug: "reasoning", name: "Reasoning" }
const vision: TaskRef = { id: "task-vision", slug: "vision", name: "Vision" }

describe("paper portal metrics", () => {
  it("counts papers, unique tasks, and unique code repositories from real paper records", () => {
    const result = buildPaperPortalMetrics(
      [
        paper("one", [agents], {
          repoUrl: "https://github.com/Owner/Repo",
          implementations: [{ id: "impl-one", name: "Owner/Repo", repoUrl: "https://github.com/owner/repo.git" }]
        }),
        paper("two", [agents, reasoning], {
          implementations: [{ id: "impl-two", name: "Owner/Other", repoUrl: "https://github.com/owner/other" }]
        }),
        paper("draft", [vision], { repoUrl: "https://github.com/owner/draft", isPublished: false })
      ],
      12
    )

    expect(result).toEqual({
      paperCount: 12,
      taskCount: 2,
      repositoryCount: 2
    })
  })

  it("derives hot and trending domains from paper counts and trend signals", () => {
    const papers = [
      paper("old-agents", [agents], { publishedAt: "2026-04-01T00:00:00Z", githubStars: 20 }),
      paper("new-agents", [agents], { publishedAt: "2026-05-20T00:00:00Z", githubStars: 5 }),
      paper("new-reasoning", [reasoning], { publishedAt: "2026-05-25T00:00:00Z", githubStars: 400 }),
      paper("vision", [vision], { publishedAt: "2026-05-22T00:00:00Z", citationCount: 1 })
    ]

    expect(deriveTopPaperDomains(papers, 2).map((task) => task.slug)).toEqual(["agents", "reasoning"])
    expect(deriveTrendingPaperDomains(papers, 2, new Date("2026-05-27T00:00:00Z")).map((task) => task.slug)).toEqual([
      "reasoning",
      "agents"
    ])
  })
})

function paper(id: string, taskRefs: TaskRef[], overrides: Partial<Paper> = {}): Paper {
  return {
    id,
    slug: id,
    title: id,
    abstractSnippet: id,
    authors: ["NewsRoom"],
    publishedAt: "2026-05-01T00:00:00Z",
    citationCount: 0,
    tags: [],
    taskRefs,
    methodRefs: [],
    isPublished: true,
    ...overrides
  }
}
