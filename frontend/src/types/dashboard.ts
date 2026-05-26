export type DashboardDataState = "ready" | "partial" | "empty" | "fallback"

export type DashboardBoardType = "cross_board" | "news" | "paper" | "project" | "community"

export type DashboardMetric = {
  id: string
  label: string
  value: number | string
  description?: string
  delta?: string
  tone?: "neutral" | "success" | "warning" | "danger" | "info" | "accent"
}

export type DashboardReadingPathItem = {
  id: string
  label: string
  href: string
  description?: string
  board?: DashboardBoardType
}

export type IntelligenceBrief = {
  title: string
  summary: string
  keyFindings: string[]
  coreJudgments: string[]
  readingPath: DashboardReadingPathItem[]
  agentNotes: string[]
  mainTrend?: string
  riskNote?: string
  updatedAt: string | null
  reportId?: string
}

export type TopStory = {
  id: string
  title: string
  summary: string
  board: Exclude<DashboardBoardType, "cross_board">
  objectType?: string
  objectId?: string
  href: string
  score?: number
  confidence?: number
  publishedAt?: string
  sourceName?: string
  tags?: string[]
  reason?: string
}

export type TrendingTopic = {
  id: string
  name: string
  summary: string
  trend: "rising" | "stable" | "falling"
  heatScore?: number
  signalCount?: number
  boards: DashboardBoardType[]
  confidence?: number
  href?: string
}

export type TechRadarItem = {
  id: string
  name: string
  summary: string
  category: "paper" | "project" | "framework" | "model" | "tool" | "community"
  href?: string
  board?: DashboardBoardType
  score?: number
  metric?: string
}

export type RightInsight = {
  id: string
  title: string
  summary: string
  tone?: "neutral" | "success" | "warning" | "danger" | "info" | "accent"
  value?: string | number
  items?: string[]
  updatedAt?: string
}

export type DashboardQuality = {
  status: "passed" | "review" | "failed" | "unknown"
  score?: number
  summary: string
  generatedAt?: string | null
  freshness?: string
  checks?: Array<{
    id: string
    label: string
    status: "passed" | "review" | "failed" | "unknown"
    detail?: string
  }>
}

export type DashboardOverview = {
  generatedAt: string | null
  dataState: DashboardDataState
  metrics: DashboardMetric[]
  brief: IntelligenceBrief
  topStories: TopStory[]
  trendingTopics: TrendingTopic[]
  techRadar: TechRadarItem[]
  rightInsights: RightInsight[]
  quality: DashboardQuality
  notices?: string[]
}

export type LegacyDashboardOverview = {
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
  topStories: Array<{
    id: string
    title: string
    summary: string
    heatScore?: number
    qualityScore?: number
    publishedAt?: string
    sourceName?: string
    tags?: string[]
  }>
  trendingTopics: Array<{
    id: string
    name: string
    summary: string
    trend: "rising" | "stable" | "falling"
    heatScore?: number
    itemCount?: number
    sourceCount?: number
  }>
  latestRun?: {
    id: string
    workflowName?: string
    status?: string
    finishedAt?: string
    durationSeconds?: number
  }
  latestReport?: {
    id: string
    title: string
    qualityScore?: number
  }
  sourceHealth: Array<{
    id: string
    name: string
    type: string
    status: string
    successRate?: number
  }>
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
