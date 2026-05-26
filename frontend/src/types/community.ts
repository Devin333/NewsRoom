import type { PageResponse } from "@/types/common"

export type CommunitySource =
  | "hackernews"
  | "reddit"
  | "github"
  | "github_trending"
  | "x"
  | "blog"
  | "other"

export type CommunitySourceType =
  | CommunitySource
  | "github_discussion"
  | "stackoverflow"
  | "lobsters"
  | "devto"
  | "medium"

export type CommunitySentiment = "positive" | "neutral" | "negative" | "mixed" | "controversial"

export type CommunityTopicSentiment = CommunitySentiment | "unknown"

export type CommunitySort = "trending" | "hot" | "newest" | "controversial" | "adoption"

export type CommunitySignalSort = "hot" | "newest" | "controversial" | "adoption"

export type CommunitySignalPeriod = "daily" | "weekly" | "monthly" | "all"

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

export type CommunitySignal = {
  id: string
  slug: string
  source: CommunitySource
  sourceName?: string
  title: string
  url: string
  author?: string
  summary: string
  postedAt: string
  collectedAt: string
  score?: number
  comments?: number
  sentiment: CommunitySentiment
  topics: string[]
  entities: CommunityEntity[]
  heatScore: number
  controversyScore: number
  adoptionScore: number
  relatedPaperIds: string[]
  relatedProjectIds: string[]
  relatedNewsIds: string[]
  relatedPapers?: RelatedPaperRef[]
  relatedProjects?: RelatedProjectRef[]
  relatedNews?: RelatedNewsRef[]
  evidenceLinks?: EvidenceRef[]
}

export type DebateCluster = {
  id: string
  title: string
  summary: string
  signalIds: string[]
  topicIds: string[]
  positiveArguments: string[]
  negativeArguments: string[]
  neutralFacts: string[]
  controversyScore: number
  lastUpdatedAt: string
}

export type CommunitySignalFacets = {
  sources: Array<{ source: CommunitySource; label: string; count: number }>
  topics: Array<{ topic: string; label: string; count: number }>
  sentiments: Array<{ sentiment: CommunitySentiment; label: string; count: number }>
}

export type CommunitySignalMetrics = {
  totalSignals: number
  periodSignals: number
  activeSources: number
  hotSignals: number
  controversialSignals: number
  averageHeatScore?: number
  averageControversyScore?: number
  heatSummary: string
}

export type CommunitySignalListParams = {
  q?: string
  source?: CommunitySource
  sentiment?: CommunitySentiment
  topic?: string
  period?: CommunitySignalPeriod
  sort?: CommunitySignalSort | "trending"
  limit?: number
  cursor?: string
  page?: number
  pageSize?: number
}

export type CommunitySignalListResult = {
  items: CommunitySignal[]
  allItems: CommunitySignal[]
  allFiltered: CommunitySignal[]
  clusters: DebateCluster[]
  facets: CommunitySignalFacets
  nextCursor: string | null
  page: PageResponse<CommunitySignal> & { nextCursor: string | null }
  metrics: CommunitySignalMetrics
  dataState: CommunityDataState
  source: "backend" | "artifact" | "empty"
  generatedAt?: string
  notices: string[]
}

export type CommunitySignalDetailResult = {
  signal: CommunitySignal
  relatedPapers: RelatedPaperRef[]
  relatedProjects: RelatedProjectRef[]
  relatedNews: RelatedNewsRef[]
  evidenceLinks: EvidenceRef[]
  clusters: DebateCluster[]
  notices: string[]
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
  sentiment: CommunityTopicSentiment
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
  sentiment: CommunityTopicSentiment
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
  sentiment?: CommunityTopicSentiment
  sort?: CommunitySort
  topic?: CommunityTopicKey
  page?: number
  pageSize?: number
}

export type CommunityFilterOptions = {
  sources: Array<{ sourceType: CommunitySourceType; label: string; count: number }>
  sentiments: Array<{ sentiment: CommunityTopicSentiment; count: number }>
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
