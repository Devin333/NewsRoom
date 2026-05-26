import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { RightInsightPanel } from "@/features/dashboard/components/right-insight-panel"
import type { DashboardOverview } from "@/types/dashboard"

describe("RightInsightPanel", () => {
  it("renders freshness and quality status in Chinese", () => {
    render(<RightInsightPanel overview={overview} />)

    expect(screen.getAllByText("质量状态").length).toBeGreaterThan(0)
    expect(screen.getByText("数据新鲜度")).toBeInTheDocument()
    expect(screen.getByText("得分 91")).toBeInTheDocument()
  })
})

const overview: DashboardOverview = {
  generatedAt: "2026-05-26T00:00:00Z",
  dataState: "ready",
  metrics: [],
  brief: {
    title: "简报",
    summary: "摘要",
    keyFindings: [],
    coreJudgments: [],
    readingPath: [],
    agentNotes: [],
    updatedAt: "2026-05-26T00:00:00Z"
  },
  topStories: [],
  trendingTopics: [],
  techRadar: [],
  rightInsights: [
    {
      id: "freshness",
      title: "Data freshness",
      summary: "Generated at 2026-05-26T00:00:00Z",
      tone: "info"
    }
  ],
  quality: {
    status: "passed",
    score: 91,
    summary: "质量检查已通过。"
  }
}
