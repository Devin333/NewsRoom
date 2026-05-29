export type ProjectCategory =
  | "agent_framework"
  | "rag"
  | "llm_infra"
  | "inference"
  | "evaluation"
  | "coding"
  | "multimodal"
  | "data"
  | "memory"
  | "workflow"

export type ProjectCategoryAlias =
  | ProjectCategory
  | "agent"
  | "devtool"
  | "framework"
  | "infra"
  | "llm"
  | "dataset"

export type ProjectMaturity = "new" | "rising" | "active" | "mature" | "dormant" | "experimental"

export type ProjectSource = "github" | "huggingface" | "paper" | "manual"

export type ProjectLanguage = "python" | "typescript" | "rust" | "go" | "other"

export type ProjectPeriod = "daily" | "weekly" | "monthly" | "all"

export type ProjectSort = "trending" | "newest" | "stars" | "activity" | "growth" | "quality"

export type ProjectDataState = "ready" | "partial" | "empty"

export type ProjectProductRoute =
  | "home"
  | "hot"
  | "rising"
  | "tools"
  | "cases"
  | "lab"
  | "collections"
  | "watchlist"

export type ProjectProductSection = {
  id: ProjectProductRoute
  title: string
  description: string
  href: string
  params: ProjectListParams
}

export type ProjectScores = {
  trendScore?: number
  starVelocityScore?: number
  freshnessScore?: number
  activityScore?: number
  adoptionScore?: number
  evidenceScore?: number
  qualityScore?: number
}

export type EvidenceRef = {
  id?: string
  title?: string
  sourceName?: string
  sourceType?: string
  sourceUrl?: string
  url?: string
  collectedAt?: string
  publishedAt?: string
  reliability?: string
  summary?: string
}

export type ProjectCategoryRef = {
  category: ProjectCategory
  label: string
  confidence?: number
}

export type RelatedPaperRef = {
  id?: string
  title: string
  url?: string
  summary?: string
}

export type RelatedNewsRef = {
  id?: string
  title: string
  url?: string
  sourceName?: string
  publishedAt?: string
}

export type RelatedCommunityRef = {
  id?: string
  title: string
  url?: string
  sourceName?: string
  publishedAt?: string
}

export type ProjectRelationCounts = {
  papers: number
  news: number
  community: number
}

export type ProjectItem = {
  id: string
  slug: string
  name: string
  fullName: string
  description: string
  repoUrl: string
  homepageUrl?: string
  owner?: string
  language?: string
  license?: string
  stars?: number
  forks?: number
  watchers?: number
  openIssues?: number
  starGrowth24h?: number
  starGrowth7d?: number
  projectMomentum?: number
  qualityScore?: number
  scores: ProjectScores
  categoryRefs: ProjectCategoryRef[]
  categories: ProjectCategory[]
  tags: string[]
  topics: string[]
  maturity?: ProjectMaturity
  createdAt?: string
  updatedAt?: string
  pushedAt?: string
  lastPushedAt?: string
  firstSeenAt?: string
  sourceRefs?: EvidenceRef[]
  relatedPapers?: RelatedPaperRef[]
  relatedNews?: RelatedNewsRef[]
  relatedCommunityTopics?: RelatedCommunityRef[]
  relationCounts: ProjectRelationCounts
  problemSolved?: string
  whyItMatters?: string
  sources?: ProjectSource[]
}

export type ProjectListParams = {
  q?: string
  category?: ProjectCategoryAlias
  topic?: string
  sort?: ProjectSort
  source?: ProjectSource
  language?: ProjectLanguage
  maturity?: ProjectMaturity
  period?: ProjectPeriod
  page?: number
  pageSize?: number
  limit?: number
  cursor?: string
}

export type ProjectClientRequest = {
  params?: ProjectListParams
  init?: RequestInit
}

export type ProjectMetric = {
  label: string
  value: string | number
  hint?: string
}

export type ProjectFilterOption = {
  value: string
  label: string
  count: number
}

export type ProjectListOptions = {
  categories: ProjectFilterOption[]
  sources: ProjectFilterOption[]
  languages: ProjectFilterOption[]
  topics: ProjectFilterOption[]
  maturity: ProjectFilterOption[]
}

export type ProjectPageInfo = {
  page: number
  pageSize: number
  total: number
  hasNext: boolean
  nextCursor?: string | null
}

export type ProjectListResult = {
  items: ProjectItem[]
  allItems: ProjectItem[]
  allFiltered: ProjectItem[]
  metrics: ProjectMetric[]
  options: ProjectListOptions
  page: ProjectPageInfo
  dataState: ProjectDataState
  source: "backend" | "artifact" | "none"
  sourceRunId?: string
  generatedAt?: string
  notices: string[]
}

export type ProjectDetailResult = {
  project: ProjectItem
  dataState: ProjectDataState
  source: "backend" | "artifact"
  sourceRunId?: string
  generatedAt?: string
  notices: string[]
}
