import { mkdir, rm, writeFile } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "node:os"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { safeApiGet } from "@/lib/api/server"
import { getNewsListResult, loadNewsData } from "@/lib/news/server-data"

vi.mock("@/lib/api/server", () => ({
  safeApiGet: vi.fn(),
}))

const mockedSafeApiGet = vi.mocked(safeApiGet)
let tempDir = ""

describe("news server data loader", () => {
  beforeEach(async () => {
    tempDir = path.join(tmpdir(), `newsroom-news-${Date.now()}-${Math.random().toString(16).slice(2)}`)
    await mkdir(tempDir, { recursive: true })
    vi.stubEnv("NEWSROOM_RUNS_ROOT", tempDir)
    mockedSafeApiGet.mockReset()
  })

  afterEach(async () => {
    vi.unstubAllEnvs()
    await rm(tempDir, { recursive: true, force: true })
  })

  it("prefers backend ai_news output and exposes only public HTTPS fields", async () => {
    mockedSafeApiGet
      .mockResolvedValueOnce({
        ok: true,
        data: { runs: [{ run_id: "run-ai-news", workflow_id: "ai_news-productized-board", finished_at: "2026-05-26T00:00:00Z" }] },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          content: {
            cards: [
              {
                card_id: "card-1",
                summary: "OpenAI released a new model update.",
                published_at: "2026-05-25T00:00:00Z",
                metadata: { signal_id: "sig-1", board_focus: "model_release" },
                score: { value: 0.82 },
                evidence_refs: [
                  {
                    external_id: "ev-1",
                    source_name: "OpenAI",
                    source_type: "official_blog",
                    source_url: "https://openai.com/news/model?token=hidden",
                    reliability: "official",
                  },
                ],
              },
            ],
            board_signals: [
              {
                signal_id: "sig-1",
                title: "OpenAI model update",
                summary: "OpenAI released a new model update.",
                tags: ["models"],
                raw_payload: { raw_content: "must not leak" },
              },
            ],
          },
        },
      })

    const data = await loadNewsData()

    expect(data.source).toBe("backend")
    expect(data.items).toHaveLength(1)
    expect(data.items[0]).toMatchObject({
      title: "OpenAI model update",
      sourceUrl: "https://openai.com/news/model",
      sourceType: "official_blog",
      heatScore: 82,
      credibility: "high",
    })
    expect(JSON.stringify(data.items)).not.toMatch(/raw_payload|raw_content|token|secret/i)
  })

  it("falls back to the latest local ai_news artifact when backend data is unavailable", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })
    const runDir = path.join(tempDir, "local-ai-news")
    await mkdir(runDir, { recursive: true })
    await writeFile(
      path.join(runDir, "manifest.json"),
      JSON.stringify({ workflow_id: "ai_news-productized-board", run_id: "local-ai-news", business_productization: { board_type: "ai_news" } }),
      "utf8"
    )
    await writeFile(
      path.join(runDir, "output.json"),
      JSON.stringify({
        cards: [
          {
            card_id: "local-card",
            summary: "A local AI news artifact.",
            metadata: { signal_id: "local-sig" },
            evidence_refs: [{ source_name: "Local Source", source_type: "rss", source_url: "https://example.com/local-news" }],
          },
        ],
        board_signals: [{ signal_id: "local-sig", title: "Local artifact news", summary: "A local AI news artifact." }],
      }),
      "utf8"
    )

    const data = await loadNewsData()

    expect(data.source).toBe("artifact")
    expect(data.items[0]).toMatchObject({ title: "Local artifact news", sourceUrl: "https://example.com/local-news" })
  })

  it("marks bundled mock data as explicit fallback", async () => {
    mockedSafeApiGet.mockResolvedValueOnce({ ok: false, errorCode: "request_failed", errorMessage: "offline" })

    const result = await getNewsListResult({ pageSize: 2 })

    expect(result.dataState).toBe("fallback")
    expect(result.source).toBe("fallback")
    expect(result.page.items).toHaveLength(2)
    expect(result.notices.join(" ")).toContain("fallback")
  })
})
