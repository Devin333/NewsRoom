import { NextRequest } from "next/server"
import { describe, expect, it, vi } from "vitest"
import { GET } from "@/app/api/v1/projects/route"
import { getProjectList } from "@/lib/projects/data-source"
import { safeApiGet } from "@/lib/api/server"
import type { ProjectListResult } from "@/types/projects"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn(),
  safeApiPost: vi.fn(),
}))

vi.mock("@/lib/projects/data-source", () => ({
  getProjectList: vi.fn(),
}))

describe("projects v1 API route", () => {
  it("proxies backend Projects API data when the NewsRoom API is available", async () => {
    vi.mocked(safeApiGet).mockResolvedValueOnce({
      ok: true,
      data: {
        hot: [],
        rising: [],
        tools: [],
        cases: [],
        collections: [],
        watchlist: [],
        recommendations: [],
        meta: { source: "backend", data_state: "ready", notices: [] },
        metrics: [],
      },
    })

    const response = await GET(new NextRequest("http://localhost/api/v1/projects?limit=4"))
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.data.meta.source).toBe("backend")
    expect(safeApiGet).toHaveBeenCalledWith("/api/v1/projects?limit=4")
    expect(getProjectList).not.toHaveBeenCalled()
  })

  it("falls back to real local Project Radar data when the backend is unavailable", async () => {
    vi.mocked(safeApiGet).mockResolvedValueOnce({
      ok: false,
      errorCode: "request_failed",
      errorMessage: "fetch failed",
    })
    vi.mocked(getProjectList).mockResolvedValueOnce(projectListFixture())

    const response = await GET(new NextRequest("http://localhost/api/v1/projects?limit=2"))
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.data.hot).toHaveLength(1)
    expect(payload.data.hot[0]).toMatchObject({
      name: "OpenAI Codex",
      canonical_url: "https://openai.com/index/gartner-2026-agentic-coding-leader",
      github_url: "https://openai.com/index/gartner-2026-agentic-coding-leader",
    })
    expect(payload.data.meta).toMatchObject({ source: "artifact", data_state: "ready" })
    expect(getProjectList).toHaveBeenCalledWith(expect.objectContaining({ limit: 2, sort: "trending" }))
  })
})

function projectListFixture(): ProjectListResult {
  const project = {
    id: "openai-codex",
    slug: "openai-codex",
    name: "OpenAI Codex",
    fullName: "OpenAI Codex",
    description: "OpenAI Codex enterprise coding agent signal.",
    repoUrl: "https://openai.com/index/gartner-2026-agentic-coding-leader",
    scores: { trendScore: 91, starVelocityScore: 12 },
    categoryRefs: [{ category: "coding" as const, label: "Coding" }],
    categories: ["coding" as const],
    tags: ["agent"],
    topics: ["AI Coding"],
    relationCounts: { papers: 0, news: 1, community: 0 },
    sourceRefs: [{ sourceName: "OpenAI News", sourceType: "official_blog", url: "https://openai.com/index/gartner-2026-agentic-coding-leader" }],
    sources: ["manual" as const],
  }
  return {
    items: [project],
    allItems: [project],
    allFiltered: [project],
    metrics: [{ label: "Projects", value: 1 }],
    options: {
      categories: [{ value: "coding", label: "Coding", count: 1 }],
      sources: [{ value: "manual", label: "Manual", count: 1 }],
      languages: [],
      topics: [{ value: "AI Coding", label: "AI Coding", count: 1 }],
      maturity: [],
    },
    page: { page: 1, pageSize: 2, total: 1, hasNext: false, nextCursor: null },
    dataState: "ready",
    source: "artifact",
    sourceRunId: "project-radar-run",
    generatedAt: "2026-05-22T17:09:42.208694Z",
    notices: [],
  }
}
