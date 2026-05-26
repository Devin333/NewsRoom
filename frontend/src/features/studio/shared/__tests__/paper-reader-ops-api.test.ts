import { beforeEach, describe, expect, it, vi } from "vitest"
import { apiGet, apiPost } from "@/lib/api/client"
import {
  fetchPaperIngestOpsState,
  fetchPaperReaderOpsStats,
  refreshPaperReaderSummary,
  triggerPaperIngest,
} from "@/features/studio/shared/api/paper-reader-ops-api"

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

    vi.mocked(apiGet).mockResolvedValueOnce({
      success: true,
      data: {
        ingest: {
          runs: [{ runId: "paper-run-1" }],
          repairQueue: [],
          blockedItems: [],
          taxonomyEvents: [],
          promptMemory: [],
          config: {
            candidateLimit: 100,
            minGithubStars: 50,
            autoTaxonomyConfidence: 0.85,
            arxivQuery: "cat:cs.AI",
            classifierModelRoute: "writer-primary"
          }
        }
      }
    })

    await fetchPaperIngestOpsState(20)

    expect(apiGet).toHaveBeenCalledWith("/api/papers/ops/ingest?limit=20")

    vi.mocked(apiPost).mockResolvedValueOnce({
      success: true,
      data: {
        enqueued: {
          message_id: "1-0",
          task_id: "task-1",
          task_type: "papers.ingest_github_arxiv_daily",
          queue_name: "news:queue:papers",
          status: "queued"
        }
      }
    })

    await triggerPaperIngest({ candidateLimit: 100, minGithubStars: 50 })

    expect(apiPost).toHaveBeenCalledWith(
      "/api/papers/ops/ingest",
      { candidateLimit: 100, minGithubStars: 50 }
    )
  })
})
