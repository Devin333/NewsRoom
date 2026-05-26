import type { CredibilityLevel, QualityStatus, SourceType } from "@/types/common"
import type { NewsFilterOptions, NewsFilters, NewsItem, NewsViewMode } from "@/types/news"

export const NEWS_PAGE_SIZE = 8

const sourceTypes: SourceType[] = [
  "official_blog",
  "rss",
  "atom",
  "github",
  "hackernews",
  "reddit",
  "arxiv",
  "lobsters",
  "stackoverflow",
  "devto",
  "medium",
  "html",
  "web_page",
  "manual",
  "media",
  "custom",
]
const credibilityLevels: CredibilityLevel[] = ["high", "medium", "low"]
const qualityStatuses: QualityStatus[] = ["passed", "review", "failed"]
const viewModes: NewsViewMode[] = ["card", "dense", "table"]
const sortFields: NonNullable<NewsFilters["sort"]>[] = ["publishedAt", "collectedAt", "heatScore", "qualityScore"]
const topicStatusValues: NonNullable<NewsFilters["topicStatus"]>[] = ["all", "clustered", "unclustered"]

export function qualityStatusFromScore(score?: number): QualityStatus | undefined {
  if (score === undefined || Number.isNaN(score)) {
    return undefined
  }
  if (score >= 80) {
    return "passed"
  }
  if (score >= 60) {
    return "review"
  }
  return "failed"
}

export function filtersFromSearchParams(params: URLSearchParams): NewsFilters {
  const topicParam = params.get("topic")
  const topicStatus = readEnum(params.get("topicStatus"), topicStatusValues) ?? readEnum(topicParam, topicStatusValues)
  const periodRange = dateRangeFromPeriod(params.get("period"))
  const sourceTypeParam = params.get("sourceType") ?? params.get("source")
  const filters: NewsFilters = {
    keyword: params.get("q") ?? undefined,
    dateRange: readEnum(params.get("dateRange") ?? params.get("date"), ["today", "week", "month", "custom"]) ?? periodRange,
    category: readCsv(params.get("category")),
    sourceType: readEnumList(sourceTypeParam, sourceTypes),
    topic: topicParam && !readEnum(topicParam, topicStatusValues) ? topicParam : undefined,
    credibility: readEnumList(params.get("credibility"), credibilityLevels),
    qualityStatus: readEnumList(params.get("quality"), qualityStatuses),
    topicStatus: topicStatus ?? "all",
    reportStatus: readEnum(params.get("report"), ["all", "included", "not_included"]) ?? "all",
    sort: sortFromAlias(params.get("sort")) ?? "publishedAt",
    viewMode: readEnum(params.get("view"), viewModes) ?? "card",
    page: Math.max(1, Number(params.get("page") ?? "1") || 1),
    pageSize: positiveNumber(params.get("pageSize")),
  }
  return compactFilters(filters)
}

export function filtersToSearchParams(filters: NewsFilters): URLSearchParams {
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
  setIf(params, "sort", filters.sort && filters.sort !== "publishedAt" ? filters.sort : undefined)
  setIf(params, "view", filters.viewMode && filters.viewMode !== "card" ? filters.viewMode : undefined)
  setIf(params, "page", filters.page && filters.page > 1 ? String(filters.page) : undefined)
  setIf(params, "pageSize", filters.pageSize && filters.pageSize !== NEWS_PAGE_SIZE ? String(filters.pageSize) : undefined)
  return params
}

export function updateFilters(filters: NewsFilters, patch: Partial<NewsFilters>): NewsFilters {
  return compactFilters({ ...filters, ...patch, page: patch.page ?? 1 })
}

export function applyNewsFilters(items: NewsItem[], filters: NewsFilters, now = Date.now()) {
  const keyword = filters.keyword?.trim().toLowerCase()
  const topic = filters.topic?.trim().toLowerCase()
  const filtered = items.filter((item) => {
    if (keyword) {
      const haystack = searchableText(item)
      if (!haystack.includes(keyword)) {
        return false
      }
    }
    if (topic) {
      const topicText = [item.topicId, item.topicName, ...item.tags, ...relatedTitles(item)].filter(Boolean).join(" ").toLowerCase()
      if (!topicText.includes(topic)) {
        return false
      }
    }
    if (filters.dateRange && !matchesDateRange(item, filters.dateRange, now)) {
      return false
    }
    if (filters.category?.length && !filters.category.includes(item.category)) {
      return false
    }
    if (filters.sourceType?.length && !filters.sourceType.includes(item.sourceType)) {
      return false
    }
    if (filters.credibility?.length && !filters.credibility.includes(item.credibility)) {
      return false
    }
    const qualityStatus = qualityStatusFromScore(item.qualityScore)
    if (filters.qualityStatus?.length && (!qualityStatus || !filters.qualityStatus.includes(qualityStatus))) {
      return false
    }
    if (filters.topicStatus === "clustered" && !item.topicId) {
      return false
    }
    if (filters.topicStatus === "unclustered" && item.topicId) {
      return false
    }
    if (filters.reportStatus === "included" && !item.reportIds?.length) {
      return false
    }
    if (filters.reportStatus === "not_included" && item.reportIds?.length) {
      return false
    }
    return true
  })

  const sort = filters.sort ?? "publishedAt"
  return [...filtered].sort((a, b) => compareNews(a, b, sort))
}

export function paginateNews(items: NewsItem[], page = 1, pageSize = NEWS_PAGE_SIZE) {
  const safePage = Math.max(1, page)
  const safePageSize = Math.max(1, pageSize)
  const start = (safePage - 1) * safePageSize
  return {
    items: items.slice(start, start + safePageSize),
    total: items.length,
    page: safePage,
    pageSize: safePageSize,
    hasNext: start + safePageSize < items.length,
  }
}

export function getFilterOptions(items: NewsItem[]): NewsFilterOptions {
  return {
    categories: unique(items.map((item) => item.category)),
    sourceTypes: unique(items.map((item) => item.sourceType)),
    credibility: credibilityLevels,
    qualityStatuses,
  }
}

function compareNews(a: NewsItem, b: NewsItem, sort: NonNullable<NewsFilters["sort"]>) {
  if (sort === "heatScore") {
    return scoreValue(b.heatScore) - scoreValue(a.heatScore)
  }
  if (sort === "qualityScore") {
    return scoreValue(b.qualityScore) - scoreValue(a.qualityScore)
  }
  const left = new Date(a[sort] ?? a.collectedAt ?? 0).getTime()
  const right = new Date(b[sort] ?? b.collectedAt ?? 0).getTime()
  return safeTime(right) - safeTime(left)
}

function matchesDateRange(item: NewsItem, dateRange: NonNullable<NewsFilters["dateRange"]>, now: number) {
  if (dateRange === "custom") {
    return true
  }
  const date = safeTime(new Date(item.publishedAt ?? item.collectedAt ?? 0).getTime())
  const oneDay = 24 * 60 * 60 * 1000
  const ranges = {
    today: oneDay,
    week: oneDay * 7,
    month: oneDay * 30,
  }
  return now - date <= ranges[dateRange]
}

function searchableText(item: NewsItem) {
  return [
    item.title,
    item.summary,
    item.category,
    item.sourceName,
    item.topicName,
    ...item.tags,
    ...relatedTitles(item),
    ...(item.entities ?? []).map((entity) => entity.name),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function relatedTitles(item: NewsItem) {
  return [
    ...(item.relatedPapers ?? []).map((ref) => ref.title),
    ...(item.relatedProjects ?? []).map((ref) => ref.title),
    ...(item.relatedCommunityTopics ?? []).map((ref) => ref.title),
  ]
}

function readCsv(value: string | null) {
  if (!value) {
    return undefined
  }
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
  return items.length ? items : undefined
}

function readEnum<T extends string>(value: string | null, allowed: readonly T[]) {
  return value && allowed.includes(value as T) ? (value as T) : undefined
}

function readEnumList<T extends string>(value: string | null, allowed: readonly T[]) {
  const items = readCsv(value)?.filter((item): item is T => allowed.includes(item as T))
  return items?.length ? items : undefined
}

function dateRangeFromPeriod(value: string | null): NewsFilters["dateRange"] | undefined {
  if (value === "daily" || value === "today") return "today"
  if (value === "weekly" || value === "week") return "week"
  if (value === "monthly" || value === "month") return "month"
  return undefined
}

function sortFromAlias(value: string | null): NewsFilters["sort"] | undefined {
  if (value === "top" || value === "trending") return "heatScore"
  if (value === "newest") return "publishedAt"
  return readEnum(value, sortFields)
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

function compactFilters(filters: NewsFilters): NewsFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => {
      if (Array.isArray(value)) {
        return value.length > 0
      }
      return value !== undefined && value !== ""
    })
  ) as NewsFilters
}

function unique<T extends string>(items: T[]) {
  return [...new Set(items)].sort()
}

function scoreValue(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : Number.NEGATIVE_INFINITY
}

function safeTime(value: number) {
  return Number.isFinite(value) ? value : 0
}

function positiveNumber(value: string | null) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : undefined
}
