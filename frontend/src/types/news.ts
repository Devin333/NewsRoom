import type { CredibilityLevel, QualityStatus, SourceType } from "@/types/common"

export type NewsProcessingStatus = "collected" | "analyzed" | "clustered" | "reported" | "needs_review"

export type KeyFact = {
  id: string
  text: string
  sourceName?: string
  confidence?: "high" | "medium" | "low"
  evidenceId?: string
}

export type NewsItem = {
  id: string
  title: string
  summary: string
  detailedSummary?: string
  whyItMatters?: string
  sourceName: string
  sourceType: SourceType
  sourceUrl: string
  publishedAt?: string
  collectedAt: string
  category: string
  tags: string[]
  heatScore: number
  qualityScore: number
  credibility: CredibilityLevel
  topicId?: string
  topicName?: string
  reportIds?: string[]
  evidenceIds?: string[]
  status?: NewsProcessingStatus
  keyFacts?: KeyFact[]
  agentExplanation?: string[]
}

export type NewsViewMode = "card" | "dense" | "table"

export type NewsFilters = {
  keyword?: string
  dateRange?: "today" | "week" | "month" | "custom"
  category?: string[]
  sourceType?: SourceType[]
  credibility?: CredibilityLevel[]
  qualityStatus?: QualityStatus[]
  topicStatus?: "all" | "clustered" | "unclustered"
  reportStatus?: "all" | "included" | "not_included"
  sort?: "publishedAt" | "collectedAt" | "heatScore" | "qualityScore"
  viewMode?: NewsViewMode
  page?: number
}
