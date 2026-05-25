import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPost } from "@/lib/api/client"
import {
  askPaper,
  fetchPaperDetail,
  fetchPaperGraph,
  fetchPaperMethods,
  fetchPaperReaderPayload,
  fetchPaperRelated,
  fetchPaperSections,
  fetchPapers,
  fetchPaperTasks,
  refreshPaperSummary,
  requestPaperSummary
} from "@/lib/papers/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn()
}))

describe("paper browser API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
  })

  it("uses BFF routes for list, detail, summary, reader payload, derived surfaces, and ask", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { papers: [] } })
    await fetchPapers({ limit: 10, period: "weekly" })
    expect(apiGet).toHaveBeenCalledWith("/api/papers?limit=10&period=weekly", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { paper: { id: "p" } } })
    await fetchPaperDetail("paper/1")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1", undefined)

    vi.mocked(apiPost).mockResolvedValueOnce({ success: true, data: { summary: { paperId: "p" } } })
    await requestPaperSummary("paper/1", "en")
    expect(apiPost).toHaveBeenCalledWith("/api/papers/paper%2F1/summary?locale=en", undefined, undefined)

    vi.mocked(apiPost).mockResolvedValueOnce({ success: true, data: { summary: { paperId: "p" } } })
    await refreshPaperSummary("paper/1", "en", "stale summary")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/papers/paper%2F1/summary?locale=en&refresh=true",
      { reason: "stale summary" },
      undefined
    )

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { reader: { paper: { id: "p" } } } })
    await fetchPaperReaderPayload("paper/1", "en")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1/reader?locale=en", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { sections: [] } })
    await fetchPaperSections("paper/1", "en")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1/sections?locale=en", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { relatedPapers: [] } })
    await fetchPaperRelated("paper/1")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1/related", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { graph: { paperId: "p", nodes: [], edges: [] } } })
    await fetchPaperGraph("paper/1")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1/graph", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { tasks: [] } })
    await fetchPaperTasks()
    expect(apiGet).toHaveBeenCalledWith("/api/papers/tasks", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { methods: [] } })
    await fetchPaperMethods()
    expect(apiGet).toHaveBeenCalledWith("/api/papers/methods", undefined)

    vi.mocked(apiPost).mockResolvedValueOnce({ success: true, data: { answer: { paperId: "p" } } })
    await askPaper("paper/1", "What is new?", "en")
    expect(apiPost).toHaveBeenCalledWith(
      "/api/papers/paper%2F1/ask",
      { question: "What is new?", locale: "en" },
      undefined
    )
  })
})
