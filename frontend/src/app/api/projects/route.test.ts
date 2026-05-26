import { describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { GET } from "@/app/api/projects/route"
import { getProjectList } from "@/lib/projects/data-source"

vi.mock("@/lib/projects/data-source", () => ({
  getProjectList: vi.fn(),
}))

describe("projects API route", () => {
  it("returns project list data from the project data source", async () => {
    vi.mocked(getProjectList).mockResolvedValueOnce({
      items: [],
      allItems: [],
      allFiltered: [],
      metrics: [],
        options: { categories: [], sources: [], languages: [], topics: [], maturity: [] },
      page: { page: 1, pageSize: 24, total: 0, hasNext: false },
      dataState: "empty",
      source: "none",
      notices: [],
    })

    const response = await GET(new NextRequest("http://localhost/api/projects?q=agent&period=weekly&topic=rag&maturity=rising&sort=activity&limit=12&cursor=2"))
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload).toMatchObject({ success: true, data: { dataState: "empty" } })
    expect(getProjectList).toHaveBeenCalledWith(
      expect.objectContaining({
        q: "agent",
        period: "weekly",
        topic: "rag",
        maturity: "rising",
        sort: "activity",
        limit: 12,
        cursor: "2",
      })
    )
  })
})
