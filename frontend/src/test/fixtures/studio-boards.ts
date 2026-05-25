export type StudioTestBoardType =
  | "ai_news"
  | "project_radar"
  | "paper_radar"
  | "community_pulse"
  | "cross_board"

export type StudioTestBoardFixture = {
  boardType: StudioTestBoardType
  title: string
  status: "ready" | "partial" | "fallback"
  lastRunId?: string
  qualityScore?: number
  cardCount: number
  insightCount: number
}

export const studioBoardFixtures: StudioTestBoardFixture[] = [
  {
    boardType: "ai_news",
    title: "AI News",
    status: "ready",
    lastRunId: "run-daily-20260522-0800",
    qualityScore: 82,
    cardCount: 12,
    insightCount: 4
  },
  {
    boardType: "project_radar",
    title: "Project Radar",
    status: "ready",
    lastRunId: "run-daily-20260522-0800",
    qualityScore: 84,
    cardCount: 8,
    insightCount: 3
  },
  {
    boardType: "paper_radar",
    title: "Paper Radar",
    status: "partial",
    lastRunId: "run-daily-20260522-0800",
    qualityScore: 79,
    cardCount: 6,
    insightCount: 2
  },
  {
    boardType: "community_pulse",
    title: "Community Pulse",
    status: "partial",
    lastRunId: "run-daily-20260522-0800",
    qualityScore: 76,
    cardCount: 9,
    insightCount: 3
  },
  {
    boardType: "cross_board",
    title: "Cross Board",
    status: "fallback",
    lastRunId: "run-daily-20260522-0800",
    qualityScore: 74,
    cardCount: 5,
    insightCount: 5
  }
]

export const crossBoardInsightFixture = {
  boardType: "cross_board",
  title: "Agent observability connects product releases, papers, and community incidents.",
  sharedEntities: ["OpenAI", "LangSmith", "agent traces"],
  conflictSignals: ["Community reports mention failures before official release notes."],
  trendPath: ["project_radar", "paper_radar", "community_pulse", "ai_news"]
} as const
