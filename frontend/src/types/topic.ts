import type { CredibilityLevel, SourceType } from "@/types/common"

export type TopicTrend = "rising" | "stable" | "falling"

export type TopicFilters = {
  keyword?: string
  trend?: TopicTrend[]
  category?: string[]
  entity?: string
  dateRange?: "today" | "week" | "month" | "custom"
  sort?: "heatScore" | "lastSeenAt" | "itemCount" | "qualityScore"
  viewMode?: "grid" | "list" | "dense"
}

export type TrendPoint = {
  date: string
  heatScore: number
  itemCount: number
}

export type TopicTimelineItem = {
  id: string
  topicId: string
  occurredAt: string
  title: string
  summary: string
  sourceCount: number
  evidenceIds: string[]
  importance: "low" | "medium" | "high"
  type: "official" | "community" | "paper" | "repo" | "media" | "agent"
  relatedNewsId?: string
}

export type TopicSourceCoverage = {
  sourceName: string
  sourceType: SourceType
  itemCount: number
  firstSeenAt: string
  lastSeenAt: string
  credibility: CredibilityLevel
  coverageSummary?: string
}

export type AgentAnalysis = {
  agent: "HistorianAgent" | "AnalystAgent" | "WriterAgent" | "ReviewerAgent" | "TrendHunterAgent"
  summary: string
}

export type Topic = {
  id: string
  name: string
  summary: string
  executiveSummary?: string
  trend: TopicTrend
  heatScore: number
  qualityScore?: number
  itemCount: number
  sourceCount: number
  firstSeenAt?: string
  lastSeenAt?: string
  category?: string
  entities?: string[]
  tags?: string[]
  timeline?: TopicTimelineItem[]
  sourceCoverage?: TopicSourceCoverage[]
  evidenceIds?: string[]
  relatedNewsIds?: string[]
  relatedTechItemIds?: string[]
  agentAnalysis?: AgentAnalysis[]
  trendHistory?: TrendPoint[]
  qualityGate?: {
    status: "passed" | "review" | "failed"
    summary: string
    checks: string[]
  }
}
