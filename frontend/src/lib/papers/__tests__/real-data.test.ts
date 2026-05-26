import { beforeEach, describe, expect, it, vi } from "vitest"
import { getPaperListResult, getPaperTasksResult, loadApiPapers } from "@/lib/papers/real-data"
import { safeApiGet } from "@/lib/api/server"
import type { Paper } from "@/lib/papers/types"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn()
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)

describe("Papers API data loading", () => {
  beforeEach(() => {
    mockedSafeApiGet.mockReset()
  })

  it("loads real papers from the backend API without inventing missing metrics", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: true,
      data: {
        papers: [
          {
            id: "arxiv-2605.00001",
            slug: "agent-paper",
            title: "Agent Paper",
            abstractSnippet: "A real collected paper abstract.",
            authors: ["Alice Example"],
            publishedAt: "2026-05-24T00:00:00Z",
            venue: "arXiv",
            citationDoi: "10.48550/arxiv.2605.00001",
            tags: ["cs.AI"],
            paperUrl: "https://arxiv.org/abs/2605.00001",
            arxivUrl: "https://arxiv.org/abs/2605.00001",
            pdfUrl: "https://arxiv.org/pdf/2605.00001",
            projectUrl: "https://example.com/project",
            newsroomHeatScore: 42,
            implementations: [{ id: "repo", name: "owner/repo", repoUrl: "https://github.com/owner/repo" }],
            benchmarks: [{ id: "bench", name: "MMLU", metric: "acc", value: 90 }],
            aiSummary: {
              paperId: "arxiv-2605.00001",
              locale: "en",
              modelRoute: "writer-primary",
              abstractHash: "hash",
              summary: "A summary.",
              keyInsights: ["A"],
              limitations: [],
              generatedAt: "2026-05-24T00:00:00Z",
              cached: true
            },
            isPublished: true
          }
        ]
      }
    })

    const papers = await loadApiPapers()

    expect(mockedSafeApiGet).toHaveBeenCalledWith("/api/v1/papers?limit=1000")
    expect(papers).toHaveLength(1)
    expect(papers[0]).toMatchObject({
      id: "arxiv-2605.00001",
      title: "Agent Paper",
      pdfUrl: "https://arxiv.org/pdf/2605.00001",
      projectUrl: "https://example.com/project",
      newsroomHeatScore: 42,
      implementations: [{ id: "repo", name: "owner/repo", repoUrl: "https://github.com/owner/repo" }],
      benchmarks: [{ id: "bench", name: "MMLU", metric: "acc", value: 90 }],
      aiSummary: expect.objectContaining({ summary: "A summary." }),
      isPublished: true
    })
    expect(papers[0].githubStars).toBeUndefined()
    expect(papers[0].citationCount).toBeUndefined()
  })

  it("returns an empty list when the backend API is unavailable", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: false,
      errorCode: "request_failed",
      errorMessage: "connect ECONNREFUSED"
    })

    await expect(loadApiPapers()).resolves.toEqual([])
  })

  it("filters and sorts real paper fallback results for the BFF list", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: true,
      data: {
        papers: [
          realPaper({
            id: "paper-agent",
            title: "Agent Planning Paper",
            publishedAt: "2026-05-24T00:00:00Z",
            citationCount: 3,
            taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
            methodRefs: [{ id: "method-planning", slug: "planning", name: "Planning" }]
          }),
          realPaper({
            id: "paper-vision",
            title: "Vision Paper",
            publishedAt: "2026-05-20T00:00:00Z",
            citationCount: 100,
            taskRefs: [{ id: "task-vision", slug: "visual-question-answering", name: "Visual QA" }],
            methodRefs: [{ id: "method-llm", slug: "large-language-model", name: "Large Language Model" }]
          })
        ]
      }
    })

    const result = await getPaperListResult({ q: "agent", task: "agents", sort: "most_cited", limit: 10 })

    expect(result.source).toBe("backend")
    expect(result.dataState).toBe("ready")
    expect(result.total_count).toBe(1)
    expect(result.papers[0].id).toBe("paper-agent")
  })

  it("uses taxonomy with real paper-derived counts when task API is unavailable", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          papers: [
            realPaper({
              id: "paper-agent",
              title: "Agent Planning Paper",
              taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
              methodRefs: [{ id: "method-planning", slug: "planning", name: "Planning" }]
            })
          ]
        }
      })

    const result = await getPaperTasksResult()
    const agents = result.items.find((task) => task.slug === "agents")

    expect(result.source).toBe("taxonomy")
    expect(result.dataState).toBe("degraded")
    expect(agents?.paperCount).toBe(1)
    expect(agents?.latestPaperIds).toEqual(["paper-agent"])
  })
})

function realPaper(overrides: Partial<Paper>) {
  return { ...basePaper(), ...overrides }
}

function basePaper() {
  return {
    id: "paper",
    slug: "paper",
    title: "Paper",
    abstractSnippet: "A real collected paper abstract.",
    authors: ["Alice Example"],
    publishedAt: "2026-05-24T00:00:00Z",
    venue: "arXiv",
    tags: ["cs.AI"],
    paperUrl: "https://arxiv.org/abs/2605.00001",
    arxivUrl: "https://arxiv.org/abs/2605.00001",
    pdfUrl: "https://arxiv.org/pdf/2605.00001",
    repoUrl: "https://github.com/owner/repo",
    taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
    methodRefs: [{ id: "method-agent", slug: "agent", name: "Agent" }],
    isPublished: true
  }
}
