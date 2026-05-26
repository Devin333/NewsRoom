import { describe, expect, it } from "vitest"
import {
  adaptBoardGroupToOverview,
  adaptDashboardArtifact,
  adaptMockDashboardOverview
} from "@/lib/dashboard/overview-adapter"
import { mockDashboardOverview } from "@/lib/api/mock-data"

describe("dashboard overview adapter", () => {
  it("maps a cross-board artifact to a ready overview", () => {
    const overview = adaptDashboardArtifact({
      board_type: "cross_board",
      generated_at: "2026-05-26T00:00:00Z",
      metadata: {
        report: {
          title: "Daily cross-board brief",
          summary: "A real cross-board summary."
        }
      },
      stats: {
        signal_count: 4,
        insight_count: 1
      },
      cards: [
        card("ai_news", "news-1", "Model launch"),
        card("paper_radar", "paper-1", "Agent paper"),
        card("project_radar", "project-1", "Agent repo"),
        card("community_pulse", "community-1", "Agent debate")
      ],
      insights: [{ title: "Runtime evidence is rising", summary: "Several boards point to runtime evidence." }],
      quality: { status: "passed", score: 0.91, summary: "Quality checks passed." }
    })

    expect(overview?.dataState).toBe("ready")
    expect(overview?.generatedAt).toBe("2026-05-26T00:00:00Z")
    expect(overview?.brief.title).toBe("Daily cross-board brief")
    expect(overview?.topStories.map((story) => story.href)).toEqual(
      expect.arrayContaining(["/news/news-1", "/papers/paper-1", "/projects/project-1", "/community/community-1"])
    )
    expect(overview?.quality.status).toBe("passed")
  })

  it("aggregates productized board outputs into a partial cross-board overview", () => {
    const overview = adaptBoardGroupToOverview([
      { boardType: "ai_news", payload: { board_type: "ai_news", cards: [card("ai_news", "news-1", "News")] } },
      { boardType: "paper_radar", payload: { board_type: "paper_radar", cards: [card("paper_radar", "paper-1", "Paper")] } },
      { boardType: "project_radar", payload: { board_type: "project_radar", cards: [card("project_radar", "project-1", "Project")] } },
      { boardType: "community_pulse", payload: { board_type: "community_pulse", cards: [card("community_pulse", "community-1", "Community")] } }
    ])

    expect(overview?.dataState).toBe("partial")
    expect(metricValue(overview, "signals")).toBe(4)
    expect(metricValue(overview, "news")).toBe(1)
    expect(metricValue(overview, "projects")).toBe(1)
    expect(metricValue(overview, "papers")).toBe(1)
    expect(metricValue(overview, "community")).toBe(1)
  })

  it("marks bundled mock data as explicit fallback", () => {
    const overview = adaptMockDashboardOverview(mockDashboardOverview)

    expect(overview.dataState).toBe("fallback")
    expect(overview.notices).toContain("Showing local fallback")
  })
})

function card(boardType: string, objectId: string, title: string) {
  return {
    board_type: boardType,
    card_id: `${objectId}-card`,
    title,
    summary: `${title} summary`,
    score: { value: 0.8 },
    confidence: { value: 0.9 },
    primary_object_ref: {
      object_type: boardType,
      object_id: objectId,
      label: title
    },
    related_refs: [{ object_type: "topic", object_id: "topic-agent", label: "Agent runtime" }]
  }
}

function metricValue(overview: ReturnType<typeof adaptBoardGroupToOverview>, id: string) {
  return overview?.metrics.find((metric) => metric.id === id)?.value
}
