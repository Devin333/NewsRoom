import { describe, expect, it, vi } from "vitest"
import { loadApiPapers } from "@/lib/papers/real-data"
import { safeApiGet } from "@/lib/api/server"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn()
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)

describe("Papers API data loading", () => {
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
})
