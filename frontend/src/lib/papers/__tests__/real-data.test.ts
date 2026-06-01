import fs from "node:fs"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { getPaperById, getPaperListResult, getPaperMethodsResult, getPaperTasksResult, loadApiPapers, loadCachedPapers } from "@/lib/papers/real-data"
import { safeApiGet } from "@/lib/api/server"
import type { Paper } from "@/lib/papers/types"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn()
}))

vi.mock("node:fs", () => ({
  default: {
    existsSync: vi.fn(() => false),
    readFileSync: vi.fn(),
    readdirSync: vi.fn(() => []),
    statSync: vi.fn()
  }
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)
const mockedExistsSync = vi.mocked(fs.existsSync)
const mockedReadFileSync = vi.mocked(fs.readFileSync)
const mockedReaddirSync = vi.mocked(fs.readdirSync)
const mockedStatSync = vi.mocked(fs.statSync)

describe("Papers API data loading", () => {
  beforeEach(() => {
    mockedSafeApiGet.mockReset()
    mockedExistsSync.mockReset()
    mockedExistsSync.mockReturnValue(false)
    mockedReadFileSync.mockReset()
    mockedReaddirSync.mockReset()
    mockedReaddirSync.mockReturnValue([])
    mockedStatSync.mockReset()
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

    expect(mockedSafeApiGet).toHaveBeenCalledWith("/api/v1/papers?limit=5000")
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

  it("loads cached papers from the shared ingest cache path", () => {
    mockedExistsSync.mockImplementation((filePath) => String(filePath).endsWith(".newsroom/papers/arxiv-papers.json"))
    mockedReadFileSync.mockReturnValue(JSON.stringify({
      papers: [
        realPaper({
          id: "cache-paper",
          slug: "cache-paper",
          title: "Shared Cache Paper",
          paperUrl: "https://arxiv.org/abs/2605.99999"
        })
      ]
    }))

    const papers = loadCachedPapers()

    expect(mockedReadFileSync).toHaveBeenCalledWith(
      expect.stringContaining(".newsroom/papers/arxiv-papers.json"),
      "utf8"
    )
    expect(papers).toHaveLength(1)
    expect(papers[0]).toMatchObject({
      id: "cache-paper",
      title: "Shared Cache Paper"
    })
  })

  it("does not expose unpublished papers through detail lookup", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: true,
      data: {
        paper: realPaper({
          id: "paper-draft",
          slug: "paper-draft",
          title: "Draft Paper",
          isPublished: false
        })
      }
    })

    await expect(getPaperById("paper-draft")).resolves.toBeNull()
    expect(mockedSafeApiGet).toHaveBeenCalledWith("/api/v1/papers/paper-draft")
  })

  it("marks the paper list empty when the backend only returns unpublished papers", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: true,
      data: {
        papers: [
          realPaper({
            id: "paper-draft",
            slug: "paper-draft",
            title: "Draft Paper",
            isPublished: false
          })
        ]
      }
    })

    const result = await getPaperListResult()

    expect(result.source).toBe("empty")
    expect(result.dataState).toBe("empty")
    expect(result.total_count).toBe(0)
    expect(result.papers).toEqual([])
    expect(result.notices).toContain("No public papers are available from backend, tracked cache, or artifacts.")
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
              methodRefs: [{ id: "method-planning", slug: "planning", name: "Planning" }],
              benchmarks: [{ id: "bench-agent", name: "Agent Bench" }]
            })
          ]
        }
      })

    const result = await getPaperTasksResult()
    const agents = result.items.find((task) => task.slug === "agents")
    const reasoning = result.items.find((task) => task.slug === "reasoning")

    expect(result.source).toBe("taxonomy")
    expect(result.dataState).toBe("degraded")
    expect(agents?.paperCount).toBe(1)
    expect(agents?.benchmarkCount).toBe(1)
    expect(agents?.methodCount).toBe(1)
    expect(agents?.latestPaperIds).toEqual(["paper-agent"])
    expect(reasoning?.paperCount).toBe(0)
    expect(reasoning?.benchmarkCount).toBe(0)
    expect(reasoning?.methodCount).toBe(0)
  })

  it("marks API-backed task taxonomy empty when paper data is unavailable", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({
        ok: true,
        data: {
          tasks: [
            {
              id: "task-live",
              slug: "live-task",
              name: "Live Task",
              group: "agents",
              description: "A backend task.",
              paperCount: 9,
              benchmarkCount: 4,
              methodCount: 3,
              sisterTasks: [],
              commonMethods: []
            }
          ]
        }
      })
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "papers offline" })

    const result = await getPaperTasksResult()

    expect(result.source).toBe("backend")
    expect(result.dataState).toBe("empty")
    expect(result.notices).toContain("No backend, tracked cache, or artifact papers are available.")
    expect(result.items[0]).toMatchObject({
      slug: "live-task",
      paperCount: 0,
      benchmarkCount: 0,
      methodCount: 0
    })
  })

  it("uses taxonomy with real paper-derived method counts when method API is unavailable", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "methods offline" })
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "tasks offline" })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          papers: [
            realPaper({
              id: "paper-tool-use",
              title: "Tool Use Paper",
              taskRefs: [{ id: "task-custom", slug: "custom-task", name: "Custom Task" }],
              methodRefs: [{ id: "method-tool-use", slug: "tool-use", name: "Tool Use" }]
            })
          ]
        }
      })

    const result = await getPaperMethodsResult()
    const toolUse = result.items.find((method) => method.slug === "tool-use")
    const planning = result.items.find((method) => method.slug === "planning")

    expect(result.source).toBe("taxonomy")
    expect(result.dataState).toBe("degraded")
    expect(toolUse?.paperCount).toBe(1)
    expect(toolUse?.taskCount).toBe(1)
    expect(toolUse?.representativePaperIds).toEqual(["paper-tool-use"])
    expect(planning?.paperCount).toBe(0)
    expect(planning?.taskCount).toBe(0)
  })

  it("marks API-backed method taxonomy empty when paper data is unavailable", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({
        ok: true,
        data: {
          methods: [
            {
              id: "method-live",
              slug: "live-method",
              name: "Live Method",
              description: "A backend method.",
              paperCount: 9,
              taskCount: 4,
              implementationCount: 2,
              area: "Agents",
              relatedTasks: [],
              relatedMethods: []
            }
          ]
        }
      })
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "tasks offline" })
      .mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "papers offline" })

    const result = await getPaperMethodsResult()

    expect(result.source).toBe("backend")
    expect(result.dataState).toBe("empty")
    expect(result.notices).toContain("No backend, tracked cache, or artifact papers are available.")
    expect(result.items[0]).toMatchObject({
      slug: "live-method",
      paperCount: 0,
      taskCount: 0,
      implementationCount: 0
    })
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
