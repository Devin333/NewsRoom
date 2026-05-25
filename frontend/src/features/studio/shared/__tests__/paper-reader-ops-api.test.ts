import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPost } from "@/lib/api/client"
import { fetchPaperReaderOpsStats, refreshPaperReaderSummary } from "@/features/studio/shared/api/paper-reader-ops-api"

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn()
}))

describe("paper reader ops API client", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset()
    vi.mocked(apiPost).mockReset()
  })

  it("uses BFF routes for stats and summary refresh", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        stats: {
          dataState: "ready",
          windowHours: 24,
          paperCache: { paperCount: 1 }
        }
      }
    })

    await fetchPaperReaderOpsStats(24)

    expect(apiGet).toHaveBeenCalledWith("/api/papers/ops/stats?windowHours=24")
    expect(apiGet).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1"))

    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: {
        summary: {
          paperId: "paper-1",
          summary: "Updated"
        }
      }
    })

    await refreshPaperReaderSummary({ paperId: "paper/1", locale: "en", reason: "stale" })

    expect(apiPost).toHaveBeenCalledWith(
      "/api/papers/paper%2F1/summary?locale=en&refresh=true",
      { reason: "stale" }
    )
  })
})
