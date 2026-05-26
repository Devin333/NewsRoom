import type { CredibilityLevel, QualityStatus, SourceType } from "@/types/common"
import type { PageResponse } from "@/types/common"

export type NewsProcessingStatus = "collected" | "analyzed" | "clustered" | "reported" | "needs_review"

export type KeyFact = {
  id: string
  text: string
  sourceName?: string
  confidence?: "high" | "medium" | "low"
  evidenceId?: string
}

export type NewsEntity = {
  id: string
  name: string
  type: string
  url?: string
  confidence?: number
}

export type EvidenceRef = {
  id: string
  title?: string
  url?: string
  sourceName?: string
  sourceType?: SourceType
  capturedAt?: string
  summary?: string
  quote?: string
  credibility?: CredibilityLevel
  confidenceScore?: number
  relationReason?: string
}

export type RelatedRef = {
  id: string
  title: string
  url?: string
  type?: string
  sourceType?: string
  relationReason?: string
  score?: number
}

export type NewsItem = {
  id: string
  title: string
  summary: string
  detailedSummary?: string
  whyItMatters?: string
  url?: string
  sourceName: string
  sourceType: SourceType
  sourceUrl: string
  publishedAt?: string
  collectedAt?: string
  category: string
  tags: string[]
  heatScore?: number
  qualityScore?: number
  credibility: CredibilityLevel
  topicId?: string
  topicName?: string
  reportIds?: string[]
  evidenceIds?: string[]
  entities?: NewsEntity[]
  evidenceRefs?: EvidenceRef[]
  relatedPapers?: RelatedRef[]
  relatedProjects?: RelatedRef[]
  relatedCommunityTopics?: RelatedRef[]
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
  topic?: string
  credibility?: CredibilityLevel[]
  qualityStatus?: QualityStatus[]
  topicStatus?: "all" | "clustered" | "unclustered"
  reportStatus?: "all" | "included" | "not_included"
  sort?: "publishedAt" | "collectedAt" | "heatScore" | "qualityScore"
  viewMode?: NewsViewMode
  page?: number
  pageSize?: number
}

export type NewsFilterOptions = {
  categories: string[]
  sourceTypes: SourceType[]
  credibility: CredibilityLevel[]
  qualityStatuses: QualityStatus[]
}

export type NewsDataState = "ready" | "fallback"

export type NewsDataSource = "backend" | "artifact" | "fallback"

export type NewsListResult = {
  page: PageResponse<NewsItem>
  allItems: NewsItem[]
  allFiltered: NewsItem[]
  options: NewsFilterOptions
  dataState: NewsDataState
  source: NewsDataSource
  notices: string[]
  generatedAt?: string
}

export type NewsDetailResult = {
  news?: NewsItem
  evidence: import("@/types/evidence").EvidenceItem[]
  topic?: import("@/types/topic").Topic
  reports: import("@/types/report").Report[]
  dataState: NewsDataState
  source: NewsDataSource
  notices: string[]
}
