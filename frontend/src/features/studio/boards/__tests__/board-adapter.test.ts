import { describe, expect, it } from "vitest"
import {
  adaptBoardList,
  adaptBoardOutput,
  buildBoardDetailViewModel
} from "@/features/studio/boards/lib/board-adapter"

describe("board adapter", () => {
  it("maps list_boards response to five ordered board summaries", () => {
    const result = adaptBoardList({
      boards: [
        {
          board_type: "project_radar",
          name: "Project Radar API",
          description: "API project board",
          signal_types: ["github_project"],
          visible_sections: ["top_projects"],
          default_time_window_hours: 336,
          enabled: true
        },
        {
          board_type: "unknown_board",
          name: "Unknown"
        }
      ]
    })

    expect(result.summaries.map((summary) => summary.boardType)).toEqual([
      "ai_news",
      "project_radar",
      "paper_radar",
      "community_pulse",
      "cross_board"
    ])
    expect(result.definitions.project_radar.title).toBe("Project Radar API")
    expect(result.summaries.find((summary) => summary.boardType === "project_radar")?.status).toBe("ready")
    expect(result.notices).toContain("An unknown board definition was ignored.")
  })

  it("uses fallback board definitions when API data is missing", () => {
    const result = adaptBoardList(undefined, { fallbackReason: "API down" })

    expect(result.summaries).toHaveLength(5)
    expect(result.summaries[0].status).toBe("fallback")
    expect(result.notices).toEqual(expect.arrayContaining(["API down", "Board definitions are using deterministic fallback data."]))
  })

  it("maps board output cards, insights, detail pages, and derived quality", () => {
    const result = adaptBoardOutput("ai_news", {
      board_type: "ai_news",
      cards: [
        {
          card_id: "card-1",
          title: "Agent Memory",
          summary: "Memory update",
          score: { value: 0.82 },
          confidence: { value: 0.9 },
          badges: [{ label: "ai_news" }],
          metrics: [{ label: "Relations", value: 4 }],
          related_refs: [{ object_type: "technology", object_id: "memory", label: "Memory" }]
        }
      ],
      insights: [{ insight_id: "insight-1", title: "Memory rising", summary: "Signal is rising" }],
      detail_pages: [{ page_id: "detail-1", title: "Memory detail", summary: "Detail", sections: [{ title: "Overview" }] }],
      sections: [{ title: "Top signals", cards: [{}], insights: [] }],
      stats: {
        signal_count: 1,
        card_count: 1,
        detail_page_count: 1,
        insight_count: 1,
        relation_count: 4,
        radar_item_count: 2
      },
      metadata: { board_name: "AI News", report: { title: "AI News Report", summary: "Report" } }
    })

    expect(result.cards[0]).toMatchObject({ id: "card-1", title: "Agent Memory", score: 82 })
    expect(result.insights[0].title).toBe("Memory rising")
    expect(result.detailPages[0].sectionCount).toBe(1)
    expect(result.quality).toMatchObject({ status: "partial", source: "derived", score: 82 })
    expect(result.notices[0]).toContain("quality_summary")
  })

  it("renders cross_board as a partial cross-board structure", () => {
    const result = adaptBoardOutput("cross_board", {
      board_type: "cross_board",
      cards: [
        {
          card_id: "card-cross",
          title: "Agent Memory",
          summary: "Cross board signal",
          related_refs: [{ object_type: "topic", object_id: "agent-memory", label: "Agent Memory" }]
        }
      ],
      insights: [
        {
          insight_id: "conflict-1",
          title: "Quality conflict",
          summary: "Different board quality scores",
          insight_type: "conflict_signal"
        }
      ],
      stats: { card_count: 1, insight_count: 1, relation_count: 2 },
      metadata: { report: { title: "Cross Board Report", summary: "Integrated summary" } }
    })

    expect(result.crossBoard?.sharedEntities).toContain("Agent Memory")
    expect(result.crossBoard?.conflictSignals).toContain("Quality conflict")
    expect(result.crossBoard?.reportTitle).toBe("Cross Board Report")
    expect(result.crossBoard?.notices[0]).toContain("Dedicated cross-board")
  })

  it("marks unknown route board type as partial without crashing", () => {
    const list = adaptBoardList(undefined)
    const detail = buildBoardDetailViewModel("mystery_board", list)

    expect(detail.summary.boardType).toBe("cross_board")
    expect(detail.summary.status).toBe("partial")
    expect(detail.notices[0]).toContain("Unknown board type")
  })
})
