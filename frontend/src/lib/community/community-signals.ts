import {
  communitySentimentLabel,
  communitySourceLabel
} from "@/lib/community/community-filters"
import type {
  CommunityDataState,
  CommunitySignal,
  CommunitySignalDetailResult,
  CommunitySignalFacets,
  CommunitySignalListParams,
  CommunitySignalListResult,
  CommunitySignalMetrics,
  CommunitySignalPeriod,
  CommunitySignalSort,
  CommunitySentiment,
  CommunitySource,
  CommunitySourceType,
  CommunityTopic,
  CommunityTopicDetail,
  CommunityTopicSentiment,
  DebateCluster
} from "@/types/community"

export const COMMUNITY_SIGNAL_PAGE_SIZE = 10

export const COMMUNITY_SIGNAL_SOURCES: CommunitySource[] = [
  "hackernews",
  "reddit",
  "github",
  "github_trending",
  "x",
  "blog",
  "other"
]

export const COMMUNITY_SIGNAL_SENTIMENTS: CommunitySentiment[] = [
  "positive",
  "neutral",
  "negative",
  "mixed",
  "controversial"
]

export const COMMUNITY_SIGNAL_PERIODS: CommunitySignalPeriod[] = ["daily", "weekly", "monthly", "all"]

export const COMMUNITY_SIGNAL_SORTS: CommunitySignalSort[] = ["hot", "newest", "controversial", "adoption"]

export function communitySignalFiltersFromSearchParams(params: URLSearchParams): CommunitySignalListParams {
  return compactSignalParams({
    q: params.get("q") ?? undefined,
    source: readCommunitySource(params.get("source")),
    sentiment: readEnum(params.get("sentiment"), COMMUNITY_SIGNAL_SENTIMENTS),
    topic: params.get("topic") ?? undefined,
    period: readPeriod(params.get("period") ?? params.get("dateRange") ?? params.get("date")) ?? "all",
    sort: readSort(params.get("sort")),
    limit: positiveNumber(params.get("limit") ?? params.get("pageSize")),
    cursor: params.get("cursor") ?? undefined,
    page: positiveNumber(params.get("page")),
    pageSize: positiveNumber(params.get("pageSize"))
  })
}

export function communitySignalFiltersToSearchParams(filters: CommunitySignalListParams): URLSearchParams {
  const params = new URLSearchParams()
  setIf(params, "q", filters.q)
  setIf(params, "source", filters.source)
  setIf(params, "sentiment", filters.sentiment)
  setIf(params, "topic", filters.topic)
  setIf(params, "period", filters.period && filters.period !== "all" ? filters.period : undefined)
  setIf(params, "sort", filters.sort && filters.sort !== "hot" && filters.sort !== "trending" ? filters.sort : undefined)
  setIf(params, "limit", filters.limit && filters.limit !== COMMUNITY_SIGNAL_PAGE_SIZE ? String(filters.limit) : undefined)
  setIf(params, "cursor", filters.cursor)
  return params
}

export function updateCommunitySignalFilters(
  filters: CommunitySignalListParams,
  patch: Partial<CommunitySignalListParams>
): CommunitySignalListParams {
  return compactSignalParams({
    ...filters,
    ...patch,
    cursor: patch.cursor,
    page: undefined
  })
}

export function buildCommunitySignalListResult(
  topics: CommunityTopic[],
  details: CommunityTopicDetail[],
  params: CommunitySignalListParams,
  options: {
    source: CommunitySignalListResult["source"]
    dataState?: CommunityDataState
    generatedAt?: string
    notices?: string[]
    now?: number
  }
): CommunitySignalListResult {
  const detailByTopicId = detailMap(details)
  const allItems = topics.map((topic) => communitySignalFromTopic(topic, detailByTopicId.get(topic.id), options.generatedAt))
  const allFiltered = filterCommunitySignals(allItems, params, options.now)
  const page = paginateCommunitySignals(allFiltered, params)
  const clusters = buildDebateClusters(allFiltered, detailByTopicId)

  return {
    items: page.items,
    allItems,
    allFiltered,
    clusters,
    facets: getCommunitySignalFacets(allItems),
    nextCursor: page.nextCursor,
    page,
    metrics: getCommunitySignalMetrics(allItems, allFiltered, params.period ?? "all"),
    dataState: options.dataState ?? (allItems.length ? "ready" : "empty"),
    source: allItems.length ? options.source : "empty",
    generatedAt: options.generatedAt,
    notices: options.notices ?? []
  }
}

export function buildCommunitySignalDetailResult(
  topics: CommunityTopic[],
  details: CommunityTopicDetail[],
  signalId: string,
  options: { generatedAt?: string; notices?: string[] } = {}
): CommunitySignalDetailResult | undefined {
  const detailByTopicId = detailMap(details)
  const topic = topics.find((item) => item.id === signalId || item.slug === signalId)
  if (!topic) return undefined

  const detail = detailByTopicId.get(topic.id)
  const signal = communitySignalFromTopic(topic, detail, options.generatedAt)
  return {
    signal,
    relatedPapers: signal.relatedPapers ?? [],
    relatedProjects: signal.relatedProjects ?? [],
    relatedNews: signal.relatedNews ?? [],
    evidenceLinks: signal.evidenceLinks ?? [],
    clusters: buildDebateClusters([signal], detailByTopicId),
    notices: [...(options.notices ?? []), ...(detail?.notices ?? [])]
  }
}

export function communitySignalFromTopic(
  topic: CommunityTopic,
  detail?: CommunityTopicDetail,
  generatedAt?: string
): CommunitySignal {
  const source = communitySignalSource(topic.sourceType, topic.sourceName, topic.sourceUrl)
  const sentiment = communitySignalSentiment(topic.sentiment, topic.controversyScore)
  const evidenceLinks = topic.evidenceRefs ?? []
  const postedAt = topic.publishedAt ?? topic.lastActivityAt ?? detail?.generatedAt ?? generatedAt ?? ""
  const collectedAt =
    firstString(evidenceLinks.map((evidence) => evidence.collectedAt)) ??
    detail?.generatedAt ??
    generatedAt ??
    topic.lastActivityAt ??
    postedAt
  const topics = communitySignalTopics(topic)

  return {
    id: topic.id,
    slug: topic.slug,
    source,
    sourceName: topic.sourceName,
    title: topic.title,
    url: topic.sourceUrl ?? firstString(evidenceLinks.map((evidence) => evidence.url)) ?? "",
    summary: detail?.summary ?? topic.summary,
    postedAt,
    collectedAt,
    score: topic.upvoteCount,
    comments: topic.commentCount,
    sentiment,
    topics,
    entities: topic.entities ?? [],
    heatScore: scoreNumber(topic.heatScore),
    controversyScore: scoreNumber(topic.controversyScore),
    adoptionScore: scoreNumber(topic.adoptionScore),
    relatedPaperIds: (topic.relatedPapers ?? []).map((paper) => paper.id),
    relatedProjectIds: (topic.relatedProjects ?? []).map((project) => project.id),
    relatedNewsIds: (topic.relatedNews ?? []).map((news) => news.id),
    relatedPapers: topic.relatedPapers ?? [],
    relatedProjects: topic.relatedProjects ?? [],
    relatedNews: topic.relatedNews ?? [],
    evidenceLinks
  }
}

export function filterCommunitySignals(
  items: CommunitySignal[],
  filters: CommunitySignalListParams,
  now = Date.now()
): CommunitySignal[] {
  const query = filters.q?.trim().toLowerCase()
  const topic = filters.topic?.trim().toLowerCase()
  const period = filters.period ?? "all"

  return [...items]
    .filter((item) => {
      if (query && !signalSearchText(item).includes(query)) return false
      if (filters.source && item.source !== filters.source) return false
      if (filters.sentiment && item.sentiment !== filters.sentiment) return false
      if (topic && !signalTopicText(item).includes(topic)) return false
      if (period !== "all" && !matchesPeriod(item, period, now)) return false
      return true
    })
    .sort((left, right) => compareCommunitySignals(left, right, filters.sort ?? "hot"))
}

export function paginateCommunitySignals(items: CommunitySignal[], params: CommunitySignalListParams) {
  const limit = Math.min(50, Math.max(1, params.limit ?? params.pageSize ?? COMMUNITY_SIGNAL_PAGE_SIZE))
  const cursorOffset = offsetFromCursor(params.cursor)
  const pageOffset = params.page && params.page > 1 ? (params.page - 1) * limit : 0
  const start = cursorOffset ?? pageOffset
  const nextOffset = start + limit
  const pageNumber = Math.floor(start / limit) + 1
  const hasNext = nextOffset < items.length
  return {
    items: items.slice(start, nextOffset),
    total: items.length,
    page: pageNumber,
    pageSize: limit,
    hasNext,
    nextCursor: hasNext ? cursorFromOffset(nextOffset) : null
  }
}

export function getCommunitySignalFacets(items: CommunitySignal[]): CommunitySignalFacets {
  return {
    sources: COMMUNITY_SIGNAL_SOURCES.map((source) => ({
      source,
      label: communitySourceLabel(source),
      count: items.filter((item) => item.source === source).length
    })).filter((item) => item.count > 0 || item.source !== "other"),
    topics: countFacet(items.flatMap((item) => item.topics), "topic")
      .slice(0, 24)
      .map((item) => ({ topic: item.value, label: item.label, count: item.count })),
    sentiments: COMMUNITY_SIGNAL_SENTIMENTS.map((sentiment) => ({
      sentiment,
      label: communitySentimentLabel(sentiment),
      count: items.filter((item) => item.sentiment === sentiment).length
    }))
  }
}

export function getCommunitySignalMetrics(
  allItems: CommunitySignal[],
  filteredItems: CommunitySignal[],
  period: CommunitySignalPeriod
): CommunitySignalMetrics {
  const heatScores = allItems.map((item) => item.heatScore).filter(isNumber)
  const controversyScores = allItems.map((item) => item.controversyScore).filter(isNumber)
  const hotSignals = allItems.filter((item) => item.heatScore >= 70).length
  const controversialSignals = allItems.filter((item) => item.controversyScore >= 50 || item.sentiment === "controversial").length
  const lead = [...filteredItems].sort((left, right) => right.heatScore - left.heatScore)[0]

  return {
    totalSignals: allItems.length,
    periodSignals: filteredItems.length,
    activeSources: new Set(allItems.map((item) => item.source)).size,
    hotSignals,
    controversialSignals,
    averageHeatScore: average(heatScores),
    averageControversyScore: average(controversyScores),
    heatSummary: lead
      ? `${period === "all" ? "Current" : periodLabel(period)} lead: ${lead.title}`
      : "No community signals are available from the current data source."
  }
}

export function buildDebateClusters(
  signals: CommunitySignal[],
  detailsByTopicId: Map<string, CommunityTopicDetail>
): DebateCluster[] {
  return signals
    .filter((signal) => signal.controversyScore >= 30 || signal.sentiment === "mixed" || signal.sentiment === "controversial")
    .slice(0, 4)
    .map((signal) => {
      const detail = detailsByTopicId.get(signal.id)
      const comments = detail?.representativeComments ?? []
      const positiveArguments = comments
        .filter((comment) => comment.sentiment === "positive")
        .map((comment) => comment.excerpt)
        .slice(0, 3)
      const negativeArguments = comments
        .filter((comment) => comment.sentiment === "negative")
        .map((comment) => comment.excerpt)
        .slice(0, 3)
      const neutralFacts = [
        ...comments
          .filter((comment) => ["neutral", "mixed", "unknown", "controversial"].includes(comment.sentiment))
          .map((comment) => comment.excerpt),
        ...(signal.evidenceLinks ?? []).map((evidence) => evidence.excerpt).filter(isString)
      ].slice(0, 3)

      return {
        id: `cluster-${signal.id}`,
        title: signal.title,
        summary: detail?.summary ?? signal.summary,
        signalIds: [signal.id],
        topicIds: signal.topics,
        positiveArguments,
        negativeArguments,
        neutralFacts,
        controversyScore: signal.controversyScore,
        lastUpdatedAt: signal.collectedAt || signal.postedAt
      }
    })
}

export function communitySignalSource(
  sourceType: CommunitySourceType,
  sourceName?: string,
  url?: string
): CommunitySource {
  if (sourceType === "github_trending") return "github_trending"
  if (sourceType === "github" || sourceType === "github_discussion") return "github"
  if (sourceType === "hackernews" || sourceType === "reddit" || sourceType === "x" || sourceType === "blog") return sourceType
  const normalizedName = sourceName?.toLowerCase() ?? ""
  const normalizedUrl = url?.toLowerCase() ?? ""
  if (normalizedName.includes("github trending") || normalizedUrl.includes("github.com/trending")) return "github_trending"
  if (normalizedName.includes("github") || normalizedUrl.includes("github.com")) return "github"
  if (normalizedName.includes("hacker news") || normalizedUrl.includes("news.ycombinator.com")) return "hackernews"
  if (normalizedName.includes("reddit") || normalizedUrl.includes("reddit.com")) return "reddit"
  if (normalizedName.includes("twitter") || normalizedName === "x" || normalizedUrl.includes("twitter.com") || normalizedUrl.includes("x.com")) return "x"
  if (sourceType === "devto" || sourceType === "medium" || normalizedName.includes("blog")) return "blog"
  return "other"
}

export function communitySignalSentiment(
  sentiment: CommunityTopicSentiment,
  controversyScore?: number
): CommunitySentiment {
  if (sentiment === "controversial") return "controversial"
  if ((controversyScore ?? 0) >= 70) return "controversial"
  if (sentiment === "unknown") return "neutral"
  return sentiment
}

function detailMap(details: CommunityTopicDetail[]) {
  return new Map(details.map((detail) => [detail.id, detail]))
}

function communitySignalTopics(topic: CommunityTopic) {
  return uniqueStrings([
    ...topic.tags,
    ...(topic.entities ?? []).filter((entity) => entity.type === "topic").map((entity) => entity.name)
  ]).slice(0, 10)
}

function compareCommunitySignals(left: CommunitySignal, right: CommunitySignal, sort: CommunitySignalListParams["sort"]) {
  if (sort === "newest") return signalTimestamp(right) - signalTimestamp(left)
  if (sort === "controversial") return right.controversyScore - left.controversyScore || signalTimestamp(right) - signalTimestamp(left)
  if (sort === "adoption") return right.adoptionScore - left.adoptionScore || signalTimestamp(right) - signalTimestamp(left)
  return right.heatScore - left.heatScore || signalTimestamp(right) - signalTimestamp(left)
}

function matchesPeriod(item: CommunitySignal, period: CommunitySignalPeriod, now: number) {
  const timestamp = signalTimestamp(item)
  if (!timestamp) return false
  const ageMs = now - timestamp
  const day = 24 * 60 * 60 * 1000
  if (period === "daily") return ageMs <= day
  if (period === "weekly") return ageMs <= day * 7
  if (period === "monthly") return ageMs <= day * 30
  return true
}

function signalTimestamp(signal: CommunitySignal) {
  const date = new Date(signal.postedAt || signal.collectedAt || 0).getTime()
  return Number.isFinite(date) ? date : 0
}

function signalSearchText(signal: CommunitySignal) {
  return [
    signal.title,
    signal.summary,
    signal.source,
    signal.sourceName,
    ...signal.topics,
    ...(signal.entities ?? []).map((entity) => entity.name),
    ...(signal.relatedPapers ?? []).map((paper) => paper.title),
    ...(signal.relatedProjects ?? []).map((project) => project.name),
    ...(signal.relatedNews ?? []).map((news) => news.title)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function signalTopicText(signal: CommunitySignal) {
  return [signal.title, signal.summary, ...signal.topics, ...(signal.entities ?? []).map((entity) => entity.name)]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function countFacet(values: string[], key: "topic") {
  const counts = new Map<string, number>()
  for (const value of values.map((item) => item.trim()).filter(Boolean)) {
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([value, count]) => ({ value, label: value, count, key }))
}

function readCommunitySource(value: string | null): CommunitySource | undefined {
  if (!value) return undefined
  const normalized = value.trim().toLowerCase().replaceAll("-", "_")
  if (normalized === "github_discussion" || normalized === "github_discussions") return "github"
  if (normalized === "twitter" || normalized === "x_twitter") return "x"
  return COMMUNITY_SIGNAL_SOURCES.includes(normalized as CommunitySource) ? (normalized as CommunitySource) : undefined
}

function readPeriod(value: string | null): CommunitySignalPeriod | undefined {
  if (value === "today" || value === "daily") return "daily"
  if (value === "week" || value === "weekly") return "weekly"
  if (value === "month" || value === "monthly") return "monthly"
  if (value === "all") return "all"
  return undefined
}

function readSort(value: string | null): CommunitySignalSort {
  if (value === "trending" || value === "top" || value === "heatScore") return "hot"
  return readEnum(value, COMMUNITY_SIGNAL_SORTS) ?? "hot"
}

function offsetFromCursor(cursor?: string) {
  if (!cursor) return undefined
  const value = Number(cursor)
  if (Number.isFinite(value) && value >= 0) return Math.floor(value)
  const decoded = decodeCursor(cursor)
  return decoded !== undefined && decoded >= 0 ? decoded : undefined
}

function cursorFromOffset(offset: number) {
  return globalThis
    .btoa(String(offset))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "")
}

function decodeCursor(cursor: string) {
  try {
    const padded = cursor.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(cursor.length / 4) * 4, "=")
    const offset = Number(globalThis.atob(padded))
    return Number.isFinite(offset) ? Math.floor(offset) : undefined
  } catch {
    return undefined
  }
}

function scoreNumber(value?: number) {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value * 10) / 10) : 0
}

function average(values: number[]) {
  if (!values.length) return undefined
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length)
}

function periodLabel(period: CommunitySignalPeriod) {
  const labels: Record<CommunitySignalPeriod, string> = {
    daily: "Daily",
    weekly: "Weekly",
    monthly: "Monthly",
    all: "Current"
  }
  return labels[period]
}

function firstString(values: Array<string | undefined>) {
  return values.find((value): value is string => Boolean(value))
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))]
}

function positiveNumber(value: string | null) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : undefined
}

function readEnum<T extends string>(value: string | null, allowed: readonly T[]) {
  return value && allowed.includes(value as T) ? (value as T) : undefined
}

function setIf(params: URLSearchParams, key: string, value?: string) {
  if (value) params.set(key, value)
}

function compactSignalParams(params: CommunitySignalListParams): CommunitySignalListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== "")
  ) as CommunitySignalListParams
}

function isNumber(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isString(value: string | undefined): value is string {
  return typeof value === "string" && value.length > 0
}
