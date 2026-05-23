import type { AgentRun } from "@/types/agent"
import type { NewsItem } from "@/types/news"
import type { Report } from "@/types/report"
import type { SourceHealth } from "@/types/source"
import type { Topic } from "@/types/topic"

export type DashboardOverview = {
  metrics: {
    newsCollectedToday: number
    deduplicatedItems: number
    topicsUpdatedToday: number
    reportsGeneratedToday: number
    sourceSuccessRate: number
    avgQualityScore: number
  }
  metricDeltas?: Record<string, string>
  brief: {
    title: string
    summary: string
    keyFindings: string[]
    mainTrend: string
    riskNote?: string
    updatedAt: string
    reportId?: string
  }
  topStories: NewsItem[]
  trendingTopics: Topic[]
  latestRun?: AgentRun
  latestReport?: Report
  sourceHealth: SourceHealth[]
  qualityGate: {
    status: "passed" | "review" | "failed"
    passedChecks: number
    totalChecks: number
    summary: string
  }
  techRadar: {
    paper: string
    repo: string
    framework: string
  }
}
