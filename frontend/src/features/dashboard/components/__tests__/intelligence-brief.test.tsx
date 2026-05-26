import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { IntelligenceBrief } from "@/features/dashboard/components/intelligence-brief"
import type { DashboardOverview } from "@/types/dashboard"

describe("IntelligenceBrief", () => {
  it("renders summary, judgments, reading path, and agent notes", () => {
    render(<IntelligenceBrief brief={brief} />)

    expect(screen.getByText("今日摘要")).toBeInTheDocument()
    expect(screen.getByText("关键发现")).toBeInTheDocument()
    expect(screen.getByText("核心判断")).toBeInTheDocument()
    expect(screen.getByText("推荐阅读路径")).toBeInTheDocument()
    expect(screen.getByText("Agent notes")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /新闻线索/ })).toHaveAttribute("href", "/news/news-1")
  })
})

const brief: DashboardOverview["brief"] = {
  title: "今日简报",
  summary: "今日摘要内容",
  keyFindings: ["关键发现一"],
  coreJudgments: ["核心判断一"],
  readingPath: [
    {
      id: "news-1",
      label: "新闻线索",
      href: "/news/news-1",
      board: "news"
    }
  ],
  agentNotes: ["已从真实产物生成"],
  updatedAt: "2026-05-26T00:00:00Z"
}
