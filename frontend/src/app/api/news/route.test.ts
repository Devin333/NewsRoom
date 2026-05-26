import { beforeEach, describe, expect, it, vi } from "vitest"
import { NextRequest } from "next/server"
import { GET } from "@/app/api/news/route"
import { getNewsListResult } from "@/lib/news/server-data"

vi.mock("@/lib/news/server-data", () => ({
  getNewsListResult: vi.fn(),
}))

describe("/api/news route", () => {
  beforeEach(() => {
    vi.mocked(getNewsListResult).mockReset()
  })

  it("returns a success envelope for news list requests", async () => {
    vi.mocked(getNewsListResult).mockResolvedValueOnce({
      page: { items: [], total: 0, page: 1, pageSize: 8, hasNext: false },
      allItems: [],
      allFiltered: [],
      options: { categories: [], sourceTypes: [], credibility: ["high", "medium", "low"], qualityStatuses: ["passed", "review", "failed"] },
      dataState: "ready",
      source: "backend",
      notices: [],
    })

    const response = await GET(new NextRequest("http://localhost/api/news?dateRange=today&sort=heatScore"))
    const payload = await response.json()

    expect(response.status).toBe(200)
    expect(payload.success).toBe(true)
    expect(getNewsListResult).toHaveBeenCalledWith(expect.objectContaining({ dateRange: "today", sort: "heatScore" }))
  })
})
