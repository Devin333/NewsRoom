import type {
  CommunityDataState,
  CommunityFilterOptions,
  CommunityListParams,
  CommunityListResult,
  CommunityMetrics,
  CommunitySentiment,
  CommunitySort,
  CommunitySourceType,
  CommunityTopic,
  CommunityTopicKey
} from "@/types/community"

export const COMMUNITY_PAGE_SIZE = 8

export const COMMUNITY_SOURCE_TYPES: CommunitySourceType[] = [
  "hackernews",
  "reddit",
  "github_discussion",
  "stackoverflow",
  "lobsters",
  "other"
]

export const COMMUNITY_SENTIMENTS: CommunitySentiment[] = ["positive", "negative", "mixed", "neutral", "unknown"]

export const COMMUNITY_SORTS: CommunitySort[] = ["trending", "newest", "controversial", "adoption"]

export const COMMUNITY_TOPIC_KEYS: CommunityTopicKey[] = ["agents", "rag", "inference", "evaluation", "coding"]

export function communityFiltersFromSearchParams(params: URLSearchParams): CommunityListParams {
  return compactCommunityParams({
    q: params.get("q") ?? undefined,
    source: readEnum(params.get("source"), COMMUNITY_SOURCE_TYPES),
    sentiment: readEnum(params.get("sentiment"), COMMUNITY_SENTIMENTS),
    sort: readEnum(params.get("sort"), COMMUNITY_SORTS) ?? "trending",
    topic: readEnum(params.get("topic"), COMMUNITY_TOPIC_KEYS),
    page: Math.max(1, Number(params.get("page") ?? "1") || 1)
  })
}

export function communityFiltersToSearchParams(filters: CommunityListParams): URLSearchParams {
  const params = new URLSearchParams()
  setIf(params, "q", filters.q)
  setIf(params, "source", filters.source)
  setIf(params, "sentiment", filters.sentiment)
  setIf(params, "sort", filters.sort && filters.sort !== "trending" ? filters.sort : undefined)
  setIf(params, "topic", filters.topic)
  setIf(params, "page", filters.page && filters.page > 1 ? String(filters.page) : undefined)
  return params
}

export function updateCommunityFilters(
  filters: CommunityListParams,
  patch: Partial<CommunityListParams>
): CommunityListParams {
  return compactCommunityParams({ ...filters, ...patch, page: patch.page ?? 1 })
}

export function buildCommunityListResult(
  allTopics: CommunityTopic[],
  params: CommunityListParams,
  options: {
    source: CommunityListResult["source"]
    dataState?: CommunityDataState
    generatedAt?: string
    notices?: string[]
  }
): CommunityListResult {
  const filtered = filterCommunityTopics(allTopics, params)
  const page = paginateCommunityTopics(filtered, params.page, params.pageSize)
  const dataState = options.dataState ?? (allTopics.length ? "ready" : "empty")

  return {
    topics: page.items,
    allTopics,
    page,
    metrics: getCommunityMetrics(allTopics),
    options: getCommunityFilterOptions(allTopics),
    dataState,
    source: options.source,
    generatedAt: options.generatedAt,
    notices: options.notices ?? []
  }
}

export function filterCommunityTopics(items: CommunityTopic[], filters: CommunityListParams): CommunityTopic[] {
  const query = filters.q?.trim().toLowerCase()

  return [...items]
    .filter((item) => {
      if (query && !topicSearchText(item).includes(query)) return false
      if (filters.source && item.sourceType !== filters.source) return false
      if (filters.sentiment && item.sentiment !== filters.sentiment) return false
      if (filters.topic && !matchesTopicKey(item, filters.topic)) return false
      return true
    })
    .sort((left, right) => compareCommunityTopics(left, right, filters.sort ?? "trending"))
}

export function paginateCommunityTopics(items: CommunityTopic[], page = 1, pageSize = COMMUNITY_PAGE_SIZE) {
  const safePage = Math.max(1, page)
  const safePageSize = Math.min(50, Math.max(1, pageSize))
  const start = (safePage - 1) * safePageSize
  return {
    items: items.slice(start, start + safePageSize),
    total: items.length,
    page: safePage,
    pageSize: safePageSize,
    hasNext: start + safePageSize < items.length
  }
}

export function getCommunityFilterOptions(items: CommunityTopic[]): CommunityFilterOptions {
  return {
    sources: COMMUNITY_SOURCE_TYPES.map((sourceType) => ({
      sourceType,
      label: communitySourceLabel(sourceType),
      count: items.filter((item) => item.sourceType === sourceType).length
    })).filter((item) => item.count > 0 || item.sourceType !== "other"),
    sentiments: COMMUNITY_SENTIMENTS.map((sentiment) => ({
      sentiment,
      count: items.filter((item) => item.sentiment === sentiment).length
    })),
    topics: COMMUNITY_TOPIC_KEYS.map((topic) => ({
      topic,
      label: communityTopicLabel(topic),
      count: items.filter((item) => matchesTopicKey(item, topic)).length
    })),
    tags: uniqueStrings(items.flatMap((item) => item.tags)).slice(0, 24)
  }
}

export function getCommunityMetrics(items: CommunityTopic[]): CommunityMetrics {
  const heatScores = items.map((item) => item.heatScore).filter(isNumber)
  const controversyScores = items.map((item) => item.controversyScore).filter(isNumber)
  return {
    totalTopics: items.length,
    activeSources: new Set(items.map((item) => item.sourceType)).size,
    positiveCount: items.filter((item) => item.sentiment === "positive").length,
    negativeCount: items.filter((item) => item.sentiment === "negative").length,
    mixedCount: items.filter((item) => item.sentiment === "mixed").length,
    averageHeatScore: average(heatScores),
    averageControversyScore: average(controversyScores)
  }
}

export function communitySourceLabel(sourceType: CommunitySourceType): string {
  const labels: Record<CommunitySourceType, string> = {
    hackernews: "Hacker News",
    reddit: "Reddit",
    github_discussion: "GitHub Discussions",
    stackoverflow: "Stack Overflow",
    lobsters: "Lobsters",
    other: "Other"
  }
  return labels[sourceType]
}

export function communitySentimentLabel(sentiment: CommunitySentiment): string {
  const labels: Record<CommunitySentiment, string> = {
    positive: "Positive",
    negative: "Negative",
    mixed: "Mixed",
    neutral: "Neutral",
    unknown: "Unknown"
  }
  return labels[sentiment]
}

export function communityTopicLabel(topic: CommunityTopicKey): string {
  const labels: Record<CommunityTopicKey, string> = {
    agents: "Agents",
    rag: "RAG",
    inference: "Inference",
    evaluation: "Evaluation",
    coding: "Coding"
  }
  return labels[topic]
}

function compareCommunityTopics(left: CommunityTopic, right: CommunityTopic, sort: CommunitySort) {
  if (sort === "newest") {
    return topicTimestamp(right) - topicTimestamp(left)
  }
  if (sort === "controversial") {
    return numberValue(right.controversyScore) - numberValue(left.controversyScore)
  }
  if (sort === "adoption") {
    return numberValue(right.adoptionScore) - numberValue(left.adoptionScore)
  }
  const heat = numberValue(right.heatScore) - numberValue(left.heatScore)
  return heat || topicTimestamp(right) - topicTimestamp(left)
}

function topicSearchText(topic: CommunityTopic) {
  return [
    topic.title,
    topic.summary,
    topic.sourceName,
    topic.sourceType,
    ...topic.tags,
    ...(topic.entities ?? []).map((entity) => entity.name)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function matchesTopicKey(item: CommunityTopic, topic: CommunityTopicKey) {
  const haystack = topicSearchText(item)
  const aliases: Record<CommunityTopicKey, string[]> = {
    agents: ["agent", "agents", "agentic"],
    rag: ["rag", "retrieval"],
    inference: ["inference", "serving", "latency"],
    evaluation: ["evaluation", "eval", "benchmark"],
    coding: ["coding", "code", "developer"]
  }
  return aliases[topic].some((alias) => haystack.includes(alias))
}

function topicTimestamp(topic: CommunityTopic) {
  const date = new Date(topic.lastActivityAt ?? topic.publishedAt ?? 0).getTime()
  return Number.isFinite(date) ? date : 0
}

function numberValue(value: number | undefined) {
  return value ?? -1
}

function average(values: number[]) {
  if (!values.length) return undefined
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length)
}

function readEnum<T extends string>(value: string | null, allowed: readonly T[]) {
  return value && allowed.includes(value as T) ? (value as T) : undefined
}

function setIf(params: URLSearchParams, key: string, value?: string) {
  if (value) params.set(key, value)
}

function compactCommunityParams(params: CommunityListParams): CommunityListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== "")
  ) as CommunityListParams
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))].sort()
}

function isNumber(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value)
}
