export type StudioBoardType =
  | "ai_news"
  | "project_radar"
  | "paper_radar"
  | "community_pulse"
  | "cross_board"

export type StudioBoardStatus = "ready" | "partial" | "fallback"

export type StudioBoardSummary = {
  boardType: StudioBoardType
  title: string
  description?: string
  status: StudioBoardStatus
  lastRunId?: string
  qualityScore?: number
  cardCount?: number
  insightCount?: number
  notices: string[]
}

export type StudioBoardDefinition = {
  boardType: StudioBoardType
  title: string
  description: string
  inputObject: string
  outputObject: string
  signalTypes: string[]
  visibleSections: string[]
  defaultTimeWindowHours?: number
  enabled: boolean
  notices: string[]
}

export type StudioBoardMetric = {
  label: string
  value: string | number
  unit?: string
}

export type StudioBoardBadge = {
  label: string
  tone?: string
  value?: string
}

export type StudioBoardObjectRef = {
  objectType: string
  objectId: string
  label?: string
}

export type StudioBoardCard = {
  id: string
  boardType: StudioBoardType
  title: string
  subtitle?: string
  summary: string
  badges: StudioBoardBadge[]
  metrics: StudioBoardMetric[]
  relatedRefs: StudioBoardObjectRef[]
  score?: number
  confidence?: number
  rankingReason?: string
  publishedAt?: string
}

export type StudioBoardInsight = {
  id: string
  title: string
  summary: string
  insightType?: string
  relatedRefs: StudioBoardObjectRef[]
  confidence?: number
  importance?: number
}

export type StudioBoardDetailPage = {
  id: string
  title: string
  summary: string
  sectionCount: number
}

export type StudioBoardSection = {
  title: string
  content?: string
  metricCount: number
  cardCount: number
  insightCount: number
}

export type StudioBoardStats = {
  signalCount: number
  cardCount: number
  detailPageCount: number
  insightCount: number
  relationCount: number
  radarItemCount: number
}

export type StudioBoardQualitySummary = {
  status: StudioBoardStatus
  score?: number
  label: string
  source: "api" | "derived" | "fallback"
  checks: string[]
}

export type StudioCrossBoardViewModel = {
  associations: string[]
  trendPaths: string[]
  sharedEntities: string[]
  conflictSignals: string[]
  reportTitle?: string
  reportSummary?: string
  notices: string[]
}

export type StudioBoardOutputViewModel = {
  boardType: StudioBoardType
  title: string
  description: string
  generatedAt?: string
  cards: StudioBoardCard[]
  insights: StudioBoardInsight[]
  detailPages: StudioBoardDetailPage[]
  sections: StudioBoardSection[]
  stats: StudioBoardStats
  quality: StudioBoardQualitySummary
  notices: string[]
  crossBoard?: StudioCrossBoardViewModel
}

export type StudioBoardBuildRequest = {
  items: Record<string, unknown>[]
  topic?: string
}

export type StudioBoardListViewModel = {
  summaries: StudioBoardSummary[]
  definitions: Record<StudioBoardType, StudioBoardDefinition>
  notices: string[]
}

export type StudioBoardDetailViewModel = {
  summary: StudioBoardSummary
  definition: StudioBoardDefinition
  output: StudioBoardOutputViewModel
  sampleItemsJson: string
  notices: string[]
}
