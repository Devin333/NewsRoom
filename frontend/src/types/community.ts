import type { PageResponse } from "@/types/common"

export type CommunitySourceType =
  | "hackernews"
  | "reddit"
  | "github_discussion"
  | "stackoverflow"
  | "lobsters"
  | "other"

export type CommunitySentiment = "positive" | "negative" | "mixed" | "neutral" | "unknown"

export type CommunitySort = "trending" | "newest" | "controversial" | "adoption"

export type CommunityTopicKey = "agents" | "rag" | "inference" | "evaluation" | "coding"

export type CommunityDataState = "ready" | "empty" | "partial" | "error"

export type CommunityEntity = {
  id: string
  name: string
  type: "company" | "project" | "paper" | "topic" | "person" | "model" | "dataset" | "other"
  url?: string
}

export type EvidenceRef = {
  id: string
  sourceId?: string
  sourceName?: string
  sourceType?: string
  url?: string
  title?: string
  excerpt?: string
  collectedAt?: string
  publishedAt?: string
  reliability?: string
}

export type RelatedPaperRef = {
  id: string
  slug?: string
  title: string
  url?: string
}

export type RelatedProjectRef = {
  id: string
  slug?: string
  name: string
  url?: string
}

export type RelatedNewsRef = {
  id: string
  title: string
  url?: string
  publishedAt?: string
}

export type CommunityTopic = {
  id: string
  slug: string
  title: string
  summary: string
  sourceType: CommunitySourceType
  sourceName?: string
  sourceUrl?: string
  publishedAt?: string
  lastActivityAt?: string
  sentiment: CommunitySentiment
  controversyScore?: number
  adoptionScore?: number
  heatScore?: number
  commentCount?: number
  upvoteCount?: number
  tags: string[]
  entities?: CommunityEntity[]
  evidenceRefs?: EvidenceRef[]
  relatedPapers?: RelatedPaperRef[]
  relatedProjects?: RelatedProjectRef[]
  relatedNews?: RelatedNewsRef[]
}

export type CommunitySourceDistribution = {
  sourceType: CommunitySourceType
  count: number
}

export type CommunityDiscussion = {
  id: string
  title: string
  sourceName?: string
  sourceType: CommunitySourceType
  url?: string
  excerpt: string
  publishedAt?: string
  commentCount?: number
  upvoteCount?: number
}

export type CommunityCommentExcerpt = {
  id: string
  authorName?: string
  sourceName?: string
  excerpt: string
  sentiment: CommunitySentiment
  publishedAt?: string
}

export type CommunityTimelineItem = {
  id: string
  label: string
  timestamp: string
  description?: string
  sourceName?: string
}

export type CommunityTopicDetail = CommunityTopic & {
  sourceDistribution: CommunitySourceDistribution[]
  topDiscussions: CommunityDiscussion[]
  representativeComments: CommunityCommentExcerpt[]
  timeline: CommunityTimelineItem[]
  generatedAt?: string
  notices: string[]
}

export type CommunityListParams = {
  q?: string
  source?: CommunitySourceType
  sentiment?: Exclude<CommunitySentiment, "unknown"> | "unknown"
  sort?: CommunitySort
  topic?: CommunityTopicKey
  page?: number
  pageSize?: number
}

export type CommunityFilterOptions = {
  sources: Array<{ sourceType: CommunitySourceType; label: string; count: number }>
  sentiments: Array<{ sentiment: CommunitySentiment; count: number }>
  topics: Array<{ topic: CommunityTopicKey; label: string; count: number }>
  tags: string[]
}

export type CommunityMetrics = {
  totalTopics: number
  activeSources: number
  positiveCount: number
  negativeCount: number
  mixedCount: number
  averageHeatScore?: number
  averageControversyScore?: number
}

export type CommunityListResult = {
  topics: CommunityTopic[]
  allTopics: CommunityTopic[]
  page: PageResponse<CommunityTopic>
  metrics: CommunityMetrics
  options: CommunityFilterOptions
  dataState: CommunityDataState
  source: "backend" | "artifact" | "empty"
  generatedAt?: string
  notices: string[]
}
