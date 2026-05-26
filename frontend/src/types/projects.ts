export type ProjectCategory =
  | "agent"
  | "rag"
  | "inference"
  | "evaluation"
  | "multimodal"
  | "data"
  | "devtool"

export type ProjectSource = "github" | "huggingface" | "paper" | "manual"

export type ProjectLanguage = "python" | "typescript" | "rust" | "go" | "other"

export type ProjectSort = "trending" | "newest" | "stars" | "growth" | "quality"

export type ProjectDataState = "ready" | "partial" | "empty"

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

export type ProjectItem = {
  id: string
  slug: string
  name: string
  description: string
  repoUrl: string
  homepageUrl?: string
  owner?: string
  language?: string
  license?: string
  stars?: number
  forks?: number
  watchers?: number
  starGrowth24h?: number
  starGrowth7d?: number
  projectMomentum?: number
  qualityScore?: number
  categoryRefs: ProjectCategoryRef[]
  tags: string[]
  lastPushedAt?: string
  firstSeenAt?: string
  sourceRefs?: EvidenceRef[]
  relatedPapers?: RelatedPaperRef[]
  relatedNews?: RelatedNewsRef[]
  relatedCommunityTopics?: RelatedCommunityRef[]
  problemSolved?: string
  whyItMatters?: string
  sources?: ProjectSource[]
}

export type ProjectListParams = {
  q?: string
  category?: ProjectCategory
  sort?: ProjectSort
  source?: ProjectSource
  language?: ProjectLanguage
  page?: number
  pageSize?: number
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
}

export type ProjectPageInfo = {
  page: number
  pageSize: number
  total: number
  hasNext: boolean
}

export type ProjectListResult = {
  items: ProjectItem[]
  allItems: ProjectItem[]
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
