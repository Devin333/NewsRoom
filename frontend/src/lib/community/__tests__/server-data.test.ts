import { mkdir, rm, utimes, writeFile } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "node:os"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { safeApiGet } from "@/lib/api/server"
import { getCommunityList, getCommunityTopic } from "@/lib/community/server-data"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn()
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)
let tempDir = ""

describe("community server data", () => {
  beforeEach(async () => {
    tempDir = path.join(tmpdir(), `newsroom-community-${Date.now()}-${Math.random().toString(16).slice(2)}`)
    await mkdir(tempDir, { recursive: true })
    vi.stubEnv("NEWSROOM_RUNS_ROOT", tempDir)
    mockedSafeApiGet.mockReset()
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("prefers backend community_pulse run artifacts and exposes only public HTTPS fields", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({
        ok: true,
        data: {
          runs: [
            {
              run_id: "run-community",
              workflow_id: "community_pulse-productized-board",
              finished_at: "2026-05-26T00:00:00Z"
            }
          ]
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          content: boardPayload({
            source_url: "https://news.ycombinator.com/item?id=1&token=hidden",
            title: "Agent memory debate"
          })
        }
      })

    const result = await getCommunityList({})

    expect(mockedSafeApiGet).toHaveBeenNthCalledWith(
      1,
      "/api/v1/runs?limit=50&workflow_id=community_pulse-productized-board"
    )
    expect(mockedSafeApiGet).toHaveBeenNthCalledWith(2, "/api/v1/runs/run-community/artifacts/board_output")
    expect(result.source).toBe("backend")
    expect(result.dataState).toBe("ready")
    expect(result.topics[0]).toMatchObject({
      title: "Agent memory debate",
      sourceType: "hackernews",
      sourceUrl: "https://news.ycombinator.com/item?id=1",
      heatScore: 84,
      sentiment: "mixed"
    })
    expect(JSON.stringify(result)).not.toMatch(/raw_payload|raw_content|token|secret/i)
  })

  it("falls back to the latest local community_pulse artifact when backend data is unavailable", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })
    const oldRun = await writeRunArtifact("old-community", "Old community topic", "2026-05-24T00:00:00Z")
    const latestRun = await writeRunArtifact("latest-community", "Latest community topic", "2026-05-25T00:00:00Z")

    await touchRun(oldRun, new Date("2026-05-24T00:00:00Z"))
    await touchRun(latestRun, new Date("2026-05-25T00:00:00Z"))

    const result = await getCommunityList({})

    expect(result.source).toBe("artifact")
    expect(result.topics[0]?.title).toBe("Latest community topic")
  })

  it("returns explicit empty state when backend and local artifacts are unavailable", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })

    const result = await getCommunityList({})

    expect(result.source).toBe("empty")
    expect(result.dataState).toBe("empty")
    expect(result.topics).toEqual([])
    expect(result.notices.join(" ")).toContain("local community_pulse artifact")
  })

  it("builds topic detail from the same artifact source", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })
    await writeRunArtifact("detail-community", "Agent memory detail", "2026-05-25T00:00:00Z")

    const detail = await getCommunityTopic("agent-memory-detail-2026-05-25t00-00-00z")

    expect(detail?.title).toBe("Agent memory detail")
    expect(detail?.topDiscussions).toHaveLength(1)
    expect(detail?.representativeComments[0]?.excerpt).toBe("Latency is the main blocker.")
  })
})

async function writeRunArtifact(runName: string, title: string, publishedAt: string) {
  const runDir = path.join(tempDir, runName)
  await mkdir(runDir, { recursive: true })
  await writeFile(
    path.join(runDir, "manifest.json"),
    JSON.stringify({
      workflow_id: "community_pulse-productized-board",
      run_id: runName,
      business_productization: { board_type: "community_pulse" }
    }),
    "utf8"
  )
  await writeFile(path.join(runDir, "board_output.json"), JSON.stringify(boardPayload({ title, published_at: publishedAt })), "utf8")
  return runDir
}

async function touchRun(runDir: string, date: Date) {
  await utimes(path.join(runDir, "manifest.json"), date, date)
  await utimes(path.join(runDir, "board_output.json"), date, date)
}

function boardPayload(overrides: Record<string, unknown> = {}) {
  const title = String(overrides.title ?? "Agent memory debate")
  const publishedAt = String(overrides.published_at ?? "2026-05-25T00:00:00Z")
  return {
    board_type: "community_pulse",
    generated_at: "2026-05-26T00:00:00Z",
    cards: [
      {
        card_id: `card-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
        title,
        summary: "Developers discuss memory latency and reliability.",
        published_at: publishedAt,
        sentiment: "mixed",
        metadata: {
          raw_payload: { token: "hidden" },
          secret: "hidden"
        },
        metrics: [
          { label: "Heat", value: 0.84 },
          { label: "Sentiment Divergence", value: 0.41 }
        ],
        evidence_refs: [
          {
            external_id: "evidence-1",
            source_name: "Hacker News",
            source_type: "hackernews",
            source_url: overrides.source_url ?? "https://news.ycombinator.com/item?id=1",
            content_excerpt: "Public excerpt only.",
            raw_content: "private full thread"
          }
        ],
        representative_comments: [
          {
            id: "comment-1",
            excerpt: "Latency is the main blocker.",
            sentiment: "mixed",
            source_name: "Hacker News"
          }
        ],
        related_refs: [{ object_type: "topic", object_id: "agents", label: "agents" }]
      }
    ],
    detail_pages: [{ title, summary: "Public detail summary." }]
  }
}
