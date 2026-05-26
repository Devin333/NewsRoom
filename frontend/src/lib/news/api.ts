import { apiGet } from "@/lib/api/client"
import type { EvidenceItem } from "@/types/evidence"
import type { NewsDetailResult, NewsFilters, NewsItem, NewsListResult } from "@/types/news"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    details?: unknown
    detail?: unknown
    request_id?: string | null
    requestId?: string
    retryable?: boolean
  } | null
  request_id?: string | null
}

export class NewsApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "news_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "NewsApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchNewsList(filters: NewsFilters, init?: RequestInit): Promise<NewsListResult> {
  const envelope = await apiGet<ApiEnvelope<NewsListResult>>(`/api/news${queryString(filters)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchNewsDetail(id: string, init?: RequestInit): Promise<NewsDetailResult> {
  const list = await fetchNewsList({ pageSize: 1000 }, init)
  const news = list.allItems.find((item) => item.id === id)
  return {
    news,
    evidence: evidenceItems(news),
    topic: undefined,
    reports: [],
    dataState: list.dataState,
    source: list.source,
    notices: list.notices,
  }
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  const error = envelope.error
  throw new NewsApiError(
    error?.message ?? "News API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable
  )
}

function queryString(filters: NewsFilters) {
  const params = new URLSearchParams()
  setIf(params, "q", filters.keyword)
  setIf(params, "dateRange", filters.dateRange)
  setCsv(params, "category", filters.category)
  setCsv(params, "sourceType", filters.sourceType)
  setIf(params, "topic", filters.topic)
  setCsv(params, "credibility", filters.credibility)
  setCsv(params, "quality", filters.qualityStatus)
  setIf(params, "topicStatus", filters.topicStatus && filters.topicStatus !== "all" ? filters.topicStatus : undefined)
  setIf(params, "report", filters.reportStatus && filters.reportStatus !== "all" ? filters.reportStatus : undefined)
  setIf(params, "sort", filters.sort)
  setIf(params, "page", filters.page ? String(filters.page) : undefined)
  setIf(params, "pageSize", filters.pageSize ? String(filters.pageSize) : undefined)
  const text = params.toString()
  return text ? `?${text}` : ""
}

function evidenceItems(news?: NewsItem): EvidenceItem[] {
  if (!news?.evidenceRefs?.length) {
    return []
  }
  return news.evidenceRefs.map((ref) => ({
    id: ref.id,
    title: ref.title ?? news.title,
    sourceName: ref.sourceName ?? news.sourceName,
    sourceType: ref.sourceType ?? news.sourceType,
    sourceUrl: ref.url,
    originalUrl: ref.url,
    capturedAt: ref.capturedAt ?? news.collectedAt ?? news.publishedAt ?? new Date().toISOString(),
    summary: ref.summary ?? news.summary,
    quote: ref.quote,
    credibility: ref.credibility ?? news.credibility,
    confidenceScore: ref.confidenceScore,
    relationReason: ref.relationReason ?? "Source evidence for this AI news item.",
  }))
}

function setIf(params: URLSearchParams, key: string, value?: string) {
  if (value) {
    params.set(key, value)
  }
}

function setCsv(params: URLSearchParams, key: string, value?: string[]) {
  if (value?.length) {
    params.set(key, value.join(","))
  }
}
