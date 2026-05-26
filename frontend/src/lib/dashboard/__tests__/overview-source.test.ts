import { mkdir, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { safeApiGet } from "@/lib/api/server"
import {
  getDashboardOverview,
  loadBackendDashboardOverview,
  loadLocalDashboardOverview
} from "@/lib/dashboard/overview-source"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn()
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)
let tempDir = ""

describe("dashboard overview source", () => {
  beforeEach(async () => {
    tempDir = path.join(tmpdir(), `newsroom-dashboard-${Date.now()}-${Math.random().toString(16).slice(2)}`)
    await mkdir(tempDir, { recursive: true })
    vi.stubEnv("NEWSROOM_RUNS_ROOT", tempDir)
    mockedSafeApiGet.mockReset()
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("prefers backend cross-board artifacts", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({
        ok: true,
        data: {
          runs: [
            {
              run_id: "run-cross-board",
              workflow_id: "cross_board-daily",
              finished_at: "2026-05-26T01:00:00Z"
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          content: crossBoardPayload("backend-news")
        }
      })

    const result = await loadBackendDashboardOverview()

    expect(result.available).toBe(true)
    expect(result.overview?.dataState).toBe("ready")
    expect(result.overview?.topStories[0]?.href).toBe("/news/backend-news")
  })

  it("loads a local cross-board board_output artifact", async () => {
    const runDir = path.join(tempDir, "local-cross-board")
    await mkdir(runDir, { recursive: true })
    await writeFile(path.join(runDir, "manifest.json"), JSON.stringify({ workflow_id: "cross_board-daily" }), "utf8")
    await writeFile(path.join(runDir, "board_output.json"), JSON.stringify(crossBoardPayload("local-news")), "utf8")

    const result = loadLocalDashboardOverview()

    expect(result.available).toBe(true)
    expect(result.overview?.dataState).toBe("ready")
    expect(result.overview?.topStories[0]?.href).toBe("/news/local-news")
  })

  it("returns empty when local runs are available but contain no displayable content", () => {
    const result = loadLocalDashboardOverview()

    expect(result.available).toBe(true)
    expect(result.overview).toBeNull()
    expect(result.notices.join(" ")).toContain("No local cross_board artifact")
  })

  it("returns explicit fallback when backend and local artifacts are unavailable", async () => {
    vi.stubEnv("NEWSROOM_RUNS_ROOT", path.join(tempDir, "missing"))
    mockedSafeApiGet.mockResolvedValueOnce({
      ok: false,
      errorCode: "request_failed",
      errorMessage: "offline"
    })

    const overview = await getDashboardOverview()

    expect(overview.dataState).toBe("fallback")
    expect(overview.notices).toContain("Showing local fallback")
  })
})

function crossBoardPayload(objectId: string) {
  return {
    board_type: "cross_board",
    generated_at: "2026-05-26T00:00:00Z",
    stats: { signal_count: 1 },
    cards: [
      {
        board_type: "ai_news",
        card_id: `${objectId}-card`,
        title: "Backend story",
        summary: "Backend story summary",
        score: { value: 0.8 },
        primary_object_ref: {
          object_type: "ai_news",
          object_id: objectId,
          label: "Backend story"
        }
      }
    ]
  }
}
