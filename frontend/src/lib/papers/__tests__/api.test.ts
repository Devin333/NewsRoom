import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPost } from "@/lib/api/client"
import { fetchPaperDetail, fetchPaperReaderPayload, fetchPapers, requestPaperSummary } from "@/lib/papers/api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn()
}))

describe("paper browser API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
  })

  it("uses BFF routes for list, detail, summary, and reader payload", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { papers: [] } })
    await fetchPapers({ limit: 10, period: "weekly" })
    expect(apiGet).toHaveBeenCalledWith("/api/papers?limit=10&period=weekly", undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { paper: { id: "p" } } })
    await fetchPaperDetail("paper/1")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1", undefined)

    vi.mocked(apiPost).mockResolvedValueOnce({ success: true, data: { summary: { paperId: "p" } } })
    await requestPaperSummary("paper/1", "en")
    expect(apiPost).toHaveBeenCalledWith("/api/papers/paper%2F1/summary?locale=en", undefined, undefined)

    vi.mocked(apiGet).mockResolvedValueOnce({ success: true, data: { reader: { paper: { id: "p" } } } })
    await fetchPaperReaderPayload("paper/1", "en")
    expect(apiGet).toHaveBeenCalledWith("/api/papers/paper%2F1/reader?locale=en", undefined)
  })
})
