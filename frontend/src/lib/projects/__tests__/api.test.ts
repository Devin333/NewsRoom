import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet } from "@/lib/api/client"
import { fetchProjectDetail, fetchProjects } from "@/lib/projects/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
}))

describe("projects API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
  })

  it("uses project BFF routes for list and detail", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        items: [],
        allItems: [],
        metrics: [],
        options: { categories: [], sources: [], languages: [] },
        page: { page: 1, pageSize: 24, total: 0, hasNext: false },
        dataState: "empty",
        source: "none",
        notices: [],
      },
    })

    await fetchProjects({ q: "agent", category: "agent", sort: "growth", source: "github", language: "python" })
    expect(apiGet).toHaveBeenCalledWith(
      "/api/projects?q=agent&category=agent&sort=growth&source=github&language=python",
      undefined
    )

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        project: {
          id: "p1",
          slug: "openai-codex",
          name: "codex",
          description: "Terminal coding agent",
          repoUrl: "https://github.com/openai/codex",
          categoryRefs: [],
          tags: [],
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
})
