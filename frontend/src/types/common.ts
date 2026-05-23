export type PageResponse<T> = {
  items: T[]
  total: number
  page: number
  pageSize: number
  hasNext: boolean
}

export type DetailResponse<T> = {
  data: T
}

export type ApiError = {
  code: string
  message: string
  detail?: unknown
  requestId?: string
}

export type SourceType =
  | "official_blog"
  | "rss"
  | "atom"
  | "github"
  | "hackernews"
  | "reddit"
  | "arxiv"
  | "lobsters"
  | "stackoverflow"
  | "devto"
  | "medium"
  | "html"
  | "web_page"
  | "manual"
  | "media"
  | "custom"

export type CredibilityLevel = "high" | "medium" | "low"

export type QualityStatus = "passed" | "review" | "failed"

export type MockHookResult<T> = {
  data: T
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
}
