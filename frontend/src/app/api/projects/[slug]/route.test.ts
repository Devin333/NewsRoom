import { describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { GET } from "@/app/api/projects/[slug]/route"
import { getProjectDetail } from "@/lib/projects/data-source"

vi.mock("@/lib/projects/data-source", () => ({
  getProjectDetail: vi.fn(),
}))

describe("project detail API route", () => {
  it("returns a project detail envelope", async () => {
    vi.mocked(getProjectDetail).mockResolvedValueOnce({
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
    })

    const response = await GET(new NextRequest("http://localhost/api/projects/openai-codex"), { params: { slug: "openai-codex" } })
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.data.project.repoUrl).toBe("https://github.com/openai/codex")
  })

  it("returns 404 when the slug is not present", async () => {
    vi.mocked(getProjectDetail).mockResolvedValueOnce(null)

    const response = await GET(new NextRequest("http://localhost/api/projects/missing"), { params: { slug: "missing" } })
    const payload = await response.json()

    expect(response.status).toBe(404)
    expect(payload.error.code).toBe("project_not_found")
  })
})
