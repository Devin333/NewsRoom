import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client"
import {
  addProjectWatchlistItem,
  answerProjectLabQuestion,
  compareProjectTools,
  deleteProjectWatchlistItem,
  fetchProjectDetail,
  fetchProjects,
  fetchProjectsHot,
  fetchProjectsHome,
  generateProjectLabSolution,
  patchProjectWatchlistItem,
  recommendProjectTools,
  recordProjectInteraction,
  startProjectLabSession,
} from "@/lib/projects/api"

vi.mock("@/lib/api/client", () => ({
  apiDelete: vi.fn(),
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiPost: vi.fn(),
}))

describe("projects API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
    vi.mocked(apiPatch).mockReset()
    vi.mocked(apiDelete).mockReset()
  })

  it("uses project BFF routes for list and detail", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        allItems: [],
        metrics: [],
        options: { categories: [], sources: [], languages: [], topics: [], maturity: [] },
        allFiltered: [],
        page: { page: 1, pageSize: 24, total: 0, hasNext: false },
        dataState: "empty",
        source: "none",
        notices: [],
      },
    })

    await fetchProjects({
      q: "agent",
      category: "agent",
      topic: "workflow",
      sort: "activity",
      source: "github",
      language: "python",
      maturity: "rising",
      period: "weekly",
      limit: 12,
    })
    expect(apiGet).toHaveBeenCalledWith(
      "/api/projects?q=agent&category=agent&topic=workflow&sort=activity&source=github&language=python&maturity=rising&period=weekly&limit=12",
      undefined
    )

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        project: {
          id: "p1",
          slug: "openai-codex",
          name: "codex",
          fullName: "openai/codex",
          description: "Terminal coding agent",
          repoUrl: "https://github.com/openai/codex",
          scores: {},
          categoryRefs: [],
          categories: [],
          tags: [],
          topics: [],
          relationCounts: { papers: 0, news: 0, community: 0 },
        },
        dataState: "ready",
        source: "artifact",
        notices: [],
      },
    })

    const project = await fetchProjectDetail("openai/codex")
    expect(apiGet).toHaveBeenCalledWith("/api/projects/openai%2Fcodex", undefined)
    expect(project.repoUrl).toBe("https://github.com/openai/codex")
  })

  it("uses backend Projects API v1 for product routes", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        hot: [],
        rising: [],
        tools: [],
        cases: [],
        collections: [],
        watchlist: [],
        recommendations: [],
        meta: { source: "none", data_state: "empty", notices: [] },
        metrics: [],
      },
    })

    await fetchProjectsHome({ limit: 6 })
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects?limit=6", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        page: { page: 1, page_size: 18, total: 0, has_next: false },
        meta: { source: "none", data_state: "empty", notices: [] },
        metrics: [],
      },
    })

    await fetchProjectsHot({ q: "agent", topic: "workflow", pageSize: 18, limit: 18 })
    expect(apiGet).toHaveBeenCalledWith("/api/v1/projects/hot?q=agent&tag=workflow&page_size=18&limit=18", undefined)
  })

  it("covers Projects API v1 mutations", async () => {
    vi.mocked(apiPost).mockResolvedValue({ success: true, data: { ok: true } })
    vi.mocked(apiPatch).mockResolvedValue({ success: true, data: { item: { id: "watch-1" } } })
    vi.mocked(apiDelete).mockResolvedValue({ success: true, data: { deleted: true, item_id: "watch-1" } })

    await compareProjectTools({ project_ids: ["project-1"] })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/tools/compare", { project_ids: ["project-1"] }, undefined)

    await recommendProjectTools({ problem: "Need workflow", limit: 1 })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/tools/recommend", { problem: "Need workflow", limit: 1 }, undefined)

    await startProjectLabSession({ user_problem: "Need workflow" })
    expect(apiPost).toHaveBeenCalledWith("/api/v1/projects/lab/sessions", { user_problem: "Need workflow" }, undefined)

    await answerProjectLabQuestion("session/1", { question_id: "q1", answer: "API" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/answer",
      { question_id: "q1", answer: "API" },
      undefined
    )

    await generateProjectLabSolution("session/1")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/lab/sessions/session%2F1/generate-solution",
      undefined,
      undefined
    )

    await addProjectWatchlistItem({ project_id: "project-1", watch_reason: "Track releases" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/watchlist",
      { project_id: "project-1", watch_reason: "Track releases" },
      undefined
    )

    await patchProjectWatchlistItem("watch/1", { priority: "high" })
    expect(apiPatch).toHaveBeenCalledWith("/api/v1/projects/watchlist/watch%2F1", { priority: "high" }, undefined)

    await deleteProjectWatchlistItem("watch/1")
    expect(apiDelete).toHaveBeenCalledWith("/api/v1/projects/watchlist/watch%2F1", undefined)

    await recordProjectInteraction({ event_type: "view", target_type: "project", target_id: "project-1" })
    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/projects/interactions",
      { event_type: "view", target_type: "project", target_id: "project-1" },
      undefined
    )
  })
})
