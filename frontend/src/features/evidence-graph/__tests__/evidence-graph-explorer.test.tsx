import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { EvidenceGraphExplorer } from "@/features/evidence-graph/evidence-graph-explorer"
import type { EvidenceGraphResponse } from "@/types/evidence-graph"

const push = vi.fn()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

const graph: EvidenceGraphResponse = {
  generatedAt: "2026-05-26T00:00:00Z",
  query: { topic: "Agent Memory", period: "all", depth: 2, limit: 48 },
  summary: {
    topicId: "topic:agent-memory",
    topicName: "Agent Memory",
    summary: "Agent Memory has cross-board evidence.",
    trendScore: 81,
    evidenceScore: 74,
    confidenceScore: 79,
    paperCount: 1,
    projectCount: 1,
    newsCount: 1,
    communitySignalCount: 1,
    firstSeenAt: "2026-05-25T00:00:00Z",
    lastUpdatedAt: "2026-05-25T00:00:00Z",
    trajectory: "rising",
    keyEvidenceNodeIds: ["paper:agent-memory"],
  },
  nodes: [
    { id: "topic:agent-memory", type: "topic", title: "Agent Memory", tags: ["Agent Memory"] },
    { id: "paper:agent-memory", type: "paper", title: "Agent Memory Paper", summary: "Paper summary", source: "arXiv", confidence: 88 },
    { id: "project:agent-memory", type: "project", title: "agent-memory", summary: "Project summary", source: "GitHub", confidence: 82 },
    { id: "news:agent-memory", type: "news", title: "Agent Memory news", summary: "News summary", source: "Official Blog", confidence: 90 },
    { id: "community:agent-memory", type: "community_signal", title: "Agent Memory discussion", summary: "Community summary", source: "Hacker News", confidence: 70 },
  ],
  edges: [
    {
      id: "edge-1",
      sourceNodeId: "topic:agent-memory",
      targetNodeId: "paper:agent-memory",
      type: "same_topic",
      confidence: 0.88,
      evidenceText: "Matched topic.",
    },
  ],
  timeline: [
    {
      id: "timeline-1",
      topicId: "topic:agent-memory",
      occurredAt: "2026-05-25T00:00:00Z",
      title: "Paper signal",
      summary: "Paper timeline",
      sourceCount: 1,
      nodeIds: ["paper:agent-memory"],
      importance: "high",
      board: "paper",
    },
  ],
  relatedReports: [{ id: "report:agent-memory", title: "Agent Memory brief", href: "/reports/report-agent-memory", status: "published", evidenceNodeIds: [] }],
  sourceStates: [],
  notices: [],
}

describe("EvidenceGraphExplorer", () => {
  it("renders summary, evidence sections, timeline, and inspector", () => {
    render(<EvidenceGraphExplorer data={graph} />)

    expect(screen.getByRole("heading", { name: "Cross-board Evidence Graph" })).toBeInTheDocument()
    expect(screen.getByText("Trend Score")).toBeInTheDocument()
    expect(screen.getByText("Evidence Score")).toBeInTheDocument()
    expect(screen.getByText("Confidence")).toBeInTheDocument()
    expect(screen.getAllByText("Papers").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Projects").length).toBeGreaterThan(0)
    expect(screen.getByText("Paper signal")).toBeInTheDocument()
    expect(screen.getByText("Evidence Inspector")).toBeInTheDocument()
    expect(screen.getByText("Agent Memory brief")).toBeInTheDocument()
  })

  it("updates the URL when searching a topic", () => {
    render(<EvidenceGraphExplorer data={graph} />)

    fireEvent.change(screen.getByLabelText("搜索主题"), { target: { value: "RAG Evaluation" } })
    fireEvent.click(screen.getByRole("button", { name: "搜索证据图谱" }))

    expect(push).toHaveBeenCalledWith("/topics?view=evidence-graph&topic=RAG+Evaluation")
  })

  it("shows empty states when evidence is missing", () => {
    render(<EvidenceGraphExplorer data={{ ...graph, nodes: [graph.nodes[0]], edges: [], timeline: [], relatedReports: [] }} />)

    expect(screen.getByText("暂无证据链")).toBeInTheDocument()
    expect(screen.getByText("暂无时间线")).toBeInTheDocument()
    expect(screen.getByText("暂无相关报告")).toBeInTheDocument()
  })
})
