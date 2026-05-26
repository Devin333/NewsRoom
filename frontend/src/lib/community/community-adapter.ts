import type {
  CommunityCommentExcerpt,
  CommunityDataState,
  CommunityDiscussion,
  CommunityEntity,
  CommunitySentiment,
  CommunitySourceDistribution,
  CommunitySourceType,
  CommunityTimelineItem,
  CommunityTopic,
  CommunityTopicDetail,
  EvidenceRef,
  RelatedNewsRef,
  RelatedPaperRef,
  RelatedProjectRef
} from "@/types/community"

type CommunityBoardDataSet = {
  topics: CommunityTopic[]
  details: CommunityTopicDetail[]
  generatedAt?: string
  dataState: CommunityDataState
  notices: string[]
}

const COMMUNITY_SOURCE_TYPES = new Set<CommunitySourceType>([
  "hackernews",
  "reddit",
  "github_discussion",
  "stackoverflow",
  "lobsters",
  "other"
])

export function adaptCommunityBoardPayload(
  payload: unknown,
  options: { notice?: string } = {}
): CommunityBoardDataSet {
  const output = communityBoardOutput(payload)
  if (!output) {
    return {
      topics: [],
      details: [],
      dataState: "empty",
      notices: [options.notice, "未找到可用的社区脉搏 board output。"].filter(Boolean) as string[]
    }
  }

  const cards = readArray(output.cards)
  const detailPages = readArray(output.detail_pages)
  const generatedAt = readString(output.generated_at) ?? readString(readObject(output.metadata)?.generated_at)
  const slugCounts = new Map<string, number>()
  const idCounts = new Map<string, number>()

  const topics = cards.map((card, index) => {
    const raw = readObject(card) ?? {}
    const baseId = readString(raw.card_id) ?? readString(raw.id) ?? `community-topic-${index + 1}`
    const id = uniqueValue(baseId, idCounts)
    const title = readString(raw.title) ?? readString(readObject(raw.primary_object_ref)?.label) ?? `Community topic ${index + 1}`
    const slug = uniqueValue(slugify(`${title}-${readString(raw.published_at) ?? index + 1}`), slugCounts)
    return adaptCommunityTopic(raw, index, { id, slug, title, generatedAt })
  })

  const details = topics.map((topic, index) =>
    buildCommunityTopicDetail(topic, readObject(cards[index]) ?? {}, findDetailPageForTopic(topic, detailPages), generatedAt)
  )

  return {
    topics,
    details,
    generatedAt,
    dataState: topics.length ? "ready" : "empty",
    notices: [options.notice].filter(Boolean) as string[]
  }
}

export function findCommunityTopicDetail(payload: unknown, slug: string): CommunityTopicDetail | undefined {
  return adaptCommunityBoardPayload(payload).details.find((detail) => detail.slug === slug)
}

function adaptCommunityTopic(
  card: Record<string, unknown>,
  index: number,
  context: { id: string; slug: string; title: string; generatedAt?: string }
): CommunityTopic {
  const provenance = readObject(card.provenance)
  const evidenceRefs = uniqueEvidenceRefs(
    adaptEvidenceRefs(
      [
        ...readArray(card.evidence_refs),
        ...readArray(provenance?.evidence_refs),
        ...readArray(provenance?.source_refs)
      ],
      card.summary
    )
  )
  const firstEvidence = evidenceRefs[0]
  const metrics = mergeMetricMaps(metricMap(card.metrics), scoreFactorMap(card.score))
  const ranking = readObject(card.ranking_features)
  const metadata = readObject(card.metadata)
  const boardSpecificFeatures =
    readObject(ranking?.board_specific_features) ?? readObject(metadata?.board_specific_features)
  const sourceType = normalizeSourceType(firstEvidence?.sourceType)
  const sourceName = firstEvidence?.sourceName ?? sourceNameFromSubtitle(readString(card.subtitle))
  const sourceUrl = safeHttpsUrl(firstEvidence?.url)
  const relatedRefs = readArray(card.related_refs).map(adaptObjectRef).filter(isPresent)
  const primaryRef = adaptObjectRef(card.primary_object_ref)
  const entities = uniqueEntities([primaryRef, ...relatedRefs].map(entityFromObjectRef).filter(isPresent))
  const publishedAt = readString(card.published_at) ?? dateFromSubtitle(readString(card.subtitle))
  const tags = topicTags(card, relatedRefs)

  return {
    id: context.id,
    slug: context.slug,
    title: context.title,
    summary: publicExcerpt(card.summary, 420) ?? "暂无公开摘要。",
    sourceType,
    sourceName,
    sourceUrl,
    publishedAt,
    lastActivityAt:
      readString(card.last_activity_at) ??
      readString(metadata?.last_activity_at) ??
      readString(metadata?.lastActivityAt) ??
      context.generatedAt ??
      publishedAt,
    sentiment: readSentiment(card, metadata, ranking),
    controversyScore: readScore(
      metrics,
      ranking,
      [boardSpecificFeatures],
      ["Controversy", "Sentiment Divergence"],
      ["controversy_score", "sentiment_divergence"]
    ),
    adoptionScore: readScore(
      metrics,
      ranking,
      [boardSpecificFeatures],
      ["Adoption", "Adoption Score"],
      ["adoption_score", "adoption"]
    ),
    heatScore: readScore(
      metrics,
      ranking,
      [boardSpecificFeatures],
      ["Heat", "Discussion Heat"],
      ["discussion_heat", "heat_score", "heat"]
    ),
    commentCount: readCount(card, metadata, ["comment_count", "commentCount", "comments"]),
    upvoteCount: readCount(card, metadata, ["upvote_count", "upvoteCount", "score", "points"]),
    tags,
    entities,
    evidenceRefs,
    relatedPapers: relatedRefs.map(relatedPaperFromObjectRef).filter(isPresent),
    relatedProjects: relatedRefs.map(relatedProjectFromObjectRef).filter(isPresent),
    relatedNews: relatedRefs.map(relatedNewsFromObjectRef).filter(isPresent)
  }
}

function buildCommunityTopicDetail(
  topic: CommunityTopic,
  card: Record<string, unknown>,
  detailPage: Record<string, unknown> | undefined,
  generatedAt?: string
): CommunityTopicDetail {
  const representativeComments = readArray(card.representative_comments)
    .map((comment, index) => adaptCommentExcerpt(comment, index))
    .filter(isPresent)
  const topDiscussions = buildTopDiscussions(topic)
  const timeline = buildTimeline(topic, generatedAt)
  const notices = representativeComments.length
    ? []
    : ["公开 artifact 未包含代表性评论摘录，当前仅展示公开摘要。"]

  return {
    ...topic,
    summary: publicExcerpt(readString(detailPage?.summary) ?? topic.summary, 700) ?? topic.summary,
    sourceDistribution: buildSourceDistribution(topic),
    topDiscussions,
    representativeComments,
    timeline,
    generatedAt,
    notices
  }
}

function communityBoardOutput(payload: unknown): Record<string, unknown> | undefined {
  const root = readObject(payload)
  if (!root) return undefined
  const contentOutput = communityBoardOutput(root.content)
  if (contentOutput) return contentOutput
  const nestedOutput = readObject(root.board_output)
  if (nestedOutput) return nestedOutput
  const nestedCamelOutput = readObject(root.boardOutput)
  if (nestedCamelOutput) return nestedCamelOutput
  const nestedDataOutput = readObject(readObject(root.data)?.board_output)
  if (nestedDataOutput) return nestedDataOutput
  const nestedCamelDataOutput = readObject(readObject(root.data)?.boardOutput)
  if (nestedCamelDataOutput) return nestedCamelDataOutput
  if (Array.isArray(root.cards) || Array.isArray(root.detail_pages) || Array.isArray(root.detailPages)) {
    return {
      ...root,
      detail_pages: readArray(root.detail_pages).length ? root.detail_pages : root.detailPages
    }
  }
  return undefined
}

function adaptEvidenceRefs(values: unknown[], fallbackSummary: unknown): EvidenceRef[] {
  return values.map((value, index) => {
    const ref = readObject(value) ?? {}
    const id =
      readString(ref.evidence_id) ??
      readString(ref.external_id) ??
      readString(ref.source_item_id) ??
      readString(ref.url) ??
      `community-evidence-${index + 1}`
    return {
      id,
      sourceId: readString(ref.source_id),
      sourceName: readString(ref.source_name),
      sourceType: readString(ref.source_type),
      url: safeHttpsUrl(readString(ref.source_url) ?? readString(ref.url)),
      title: publicExcerpt(ref.title, 160),
      excerpt: publicExcerpt(ref.excerpt ?? ref.content_excerpt ?? ref.summary ?? ref.description ?? fallbackSummary, 360),
      collectedAt: readString(ref.collected_at),
      publishedAt: readString(ref.published_at),
      reliability: readString(ref.reliability)
    }
  })
}

function uniqueEvidenceRefs(values: EvidenceRef[]) {
  const seen = new Set<string>()
  return values.filter((value) => {
    const key = value.id || value.url || `${value.sourceName}:${value.excerpt}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function adaptObjectRef(value: unknown) {
  const ref = readObject(value)
  if (!ref) return undefined
  const objectId = readString(ref.object_id) ?? readString(ref.id)
  const objectType = readString(ref.object_type) ?? readString(ref.type)
  if (!objectId || !objectType) return undefined
  return {
    objectId,
    objectType,
    label: readString(ref.label) ?? readString(ref.title) ?? readString(ref.name),
    url: safeHttpsUrl(readString(ref.url))
  }
}

function entityFromObjectRef(ref: ReturnType<typeof adaptObjectRef>): CommunityEntity | undefined {
  if (!ref) return undefined
  const type = normalizeEntityType(ref.objectType)
  if (type === undefined) return undefined
  return {
    id: ref.objectId,
    name: ref.label ?? ref.objectId,
    type,
    url: ref.url
  }
}

function relatedPaperFromObjectRef(ref: ReturnType<typeof adaptObjectRef>): RelatedPaperRef | undefined {
  if (!ref || !["paper", "paper_radar", "research_paper"].includes(ref.objectType)) return undefined
  return {
    id: ref.objectId,
    slug: slugify(ref.label ?? ref.objectId),
    title: ref.label ?? ref.objectId,
    url: ref.url
  }
}

function relatedProjectFromObjectRef(ref: ReturnType<typeof adaptObjectRef>): RelatedProjectRef | undefined {
  if (!ref || !["project", "repo", "repository", "github_project"].includes(ref.objectType)) return undefined
  return {
    id: ref.objectId,
    slug: slugify(ref.label ?? ref.objectId),
    name: ref.label ?? ref.objectId,
    url: ref.url
  }
}

function relatedNewsFromObjectRef(ref: ReturnType<typeof adaptObjectRef>): RelatedNewsRef | undefined {
  if (!ref || !["news", "ai_news", "article"].includes(ref.objectType)) return undefined
  return {
    id: ref.objectId,
    title: ref.label ?? ref.objectId,
    url: ref.url
  }
}

function adaptCommentExcerpt(value: unknown, index: number): CommunityCommentExcerpt | undefined {
  const comment = readObject(value)
  if (!comment) return undefined
  const excerpt = publicExcerpt(comment.excerpt ?? comment.content_excerpt ?? comment.summary ?? comment.text, 320)
  if (!excerpt) return undefined
  return {
    id: readString(comment.id) ?? readString(comment.comment_id) ?? `comment-excerpt-${index + 1}`,
    authorName: readString(comment.author_name) ?? readString(comment.author),
    sourceName: readString(comment.source_name),
    excerpt,
    sentiment: normalizeSentiment(readString(comment.sentiment)) ?? "unknown",
    publishedAt: readString(comment.published_at)
  }
}

function buildTopDiscussions(topic: CommunityTopic): CommunityDiscussion[] {
  if (topic.evidenceRefs?.length) {
    return topic.evidenceRefs.map((evidence, index) => ({
      id: evidence.id,
      title: evidence.title ?? topic.title,
      sourceName: evidence.sourceName ?? topic.sourceName,
      sourceType: normalizeSourceType(evidence.sourceType),
      url: evidence.url,
      excerpt: evidence.excerpt ?? topic.summary,
      publishedAt: evidence.publishedAt ?? topic.publishedAt,
      commentCount: index === 0 ? topic.commentCount : undefined,
      upvoteCount: index === 0 ? topic.upvoteCount : undefined
    }))
  }
  return [
    {
      id: `${topic.id}-discussion`,
      title: topic.title,
      sourceName: topic.sourceName,
      sourceType: topic.sourceType,
      url: topic.sourceUrl,
      excerpt: topic.summary,
      publishedAt: topic.publishedAt,
      commentCount: topic.commentCount,
      upvoteCount: topic.upvoteCount
    }
  ]
}

function buildTimeline(topic: CommunityTopic, generatedAt?: string): CommunityTimelineItem[] {
  const items: CommunityTimelineItem[] = []
  if (topic.publishedAt) {
    items.push({
      id: `${topic.id}-published`,
      label: "发布",
      timestamp: topic.publishedAt,
      description: topic.sourceName,
      sourceName: topic.sourceName
    })
  }
  if (topic.lastActivityAt && topic.lastActivityAt !== topic.publishedAt) {
    items.push({
      id: `${topic.id}-activity`,
      label: "最近活跃",
      timestamp: topic.lastActivityAt,
      description: topic.summary,
      sourceName: topic.sourceName
    })
  }
  if (generatedAt) {
    items.push({
      id: `${topic.id}-generated`,
      label: "完成分析",
      timestamp: generatedAt,
      description: "社区脉搏 board output 已生成。"
    })
  }
  return items
}

function buildSourceDistribution(topic: CommunityTopic): CommunitySourceDistribution[] {
  const counts = new Map<CommunitySourceType, number>()
  const refs = topic.evidenceRefs?.length ? topic.evidenceRefs : [{ sourceType: topic.sourceType }]
  for (const ref of refs) {
    const sourceType = normalizeSourceType(ref.sourceType)
    counts.set(sourceType, (counts.get(sourceType) ?? 0) + 1)
  }
  return [...counts.entries()].map(([sourceType, count]) => ({ sourceType, count }))
}

function findDetailPageForTopic(topic: CommunityTopic, detailPages: unknown[]) {
  return detailPages
    .map((page) => readObject(page))
    .find((page) => {
      if (!page) return false
      if (readString(page.page_id) === topic.id) return true
      if (slugify(readString(page.title) ?? "") === slugify(topic.title)) return true
      return readArray(page.related_cards).some((card) => {
        const related = readObject(card)
        return readString(related?.title) === topic.title && readString(related?.published_at) === topic.publishedAt
      })
    })
}

function readSentiment(
  card: Record<string, unknown>,
  metadata: Record<string, unknown> | undefined,
  ranking: Record<string, unknown> | undefined
): CommunitySentiment {
  return (
    normalizeSentiment(readString(card.sentiment)) ??
    normalizeSentiment(readString(metadata?.sentiment)) ??
    normalizeSentiment(readString(ranking?.sentiment)) ??
    normalizeSentiment(readString(ranking?.sentiment_label)) ??
    "unknown"
  )
}

function normalizeSentiment(value?: string): CommunitySentiment | undefined {
  const normalized = value?.trim().toLowerCase()
  if (!normalized) return undefined
  if (["positive", "negative", "mixed", "neutral", "unknown"].includes(normalized)) {
    return normalized as CommunitySentiment
  }
  return undefined
}

function normalizeSourceType(value?: string): CommunitySourceType {
  const normalized = value?.trim().toLowerCase().replaceAll("-", "_")
  if (normalized === "github" || normalized === "github_discussions" || normalized === "github_discussion") {
    return "github_discussion"
  }
  if (normalized === "hn" || normalized === "hacker_news") return "hackernews"
  if (normalized === "stack_overflow") return "stackoverflow"
  return normalized && COMMUNITY_SOURCE_TYPES.has(normalized as CommunitySourceType)
    ? (normalized as CommunitySourceType)
    : "other"
}

function normalizeEntityType(value: string): CommunityEntity["type"] | undefined {
  const normalized = value.trim().toLowerCase()
  if (["entity", "company", "organization"].includes(normalized)) return "company"
  if (["project", "repo", "repository", "github_project"].includes(normalized)) return "project"
  if (["paper", "paper_radar", "research_paper"].includes(normalized)) return "paper"
  if (["topic", "technology"].includes(normalized)) return "topic"
  if (["person", "author"].includes(normalized)) return "person"
  if (["model", "ai_model"].includes(normalized)) return "model"
  if (["dataset"].includes(normalized)) return "dataset"
  return "other"
}

function readScore(
  metrics: Map<string, number>,
  ranking: Record<string, unknown> | undefined,
  featureRecords: Array<Record<string, unknown> | undefined>,
  metricNames: string[],
  rankingNames: string[]
) {
  for (const name of metricNames) {
    const value = metrics.get(normalizeMetricName(name))
    if (value !== undefined) return scoreToDisplayNumber(value)
  }
  for (const name of rankingNames) {
    const value = readNumber(ranking?.[name])
    if (value !== undefined) return scoreToDisplayNumber(value)
  }
  for (const record of featureRecords) {
    for (const name of rankingNames) {
      const value = readNumber(record?.[name])
      if (value !== undefined) return scoreToDisplayNumber(value)
    }
  }
  return undefined
}

function readCount(
  card: Record<string, unknown>,
  metadata: Record<string, unknown> | undefined,
  names: string[]
) {
  for (const name of names) {
    const value = readNumber(card[name]) ?? readNumber(metadata?.[name])
    if (value !== undefined) return Math.max(0, Math.round(value))
  }
  return undefined
}

function metricMap(value: unknown) {
  const map = new Map<string, number>()
  for (const item of readArray(value)) {
    const metric = readObject(item)
    const label = readString(metric?.label)
    const number = readNumber(metric?.value)
    if (label && number !== undefined) {
      map.set(normalizeMetricName(label), number)
    }
  }
  return map
}

function scoreFactorMap(value: unknown) {
  const score = readObject(value)
  const map = new Map<string, number>()
  for (const item of readArray(score?.factors)) {
    const factor = readObject(item)
    const name = readString(factor?.name)
    const number = readNumber(factor?.value)
    if (name && number !== undefined) {
      map.set(normalizeMetricName(name), number)
    }
  }
  return map
}

function mergeMetricMaps(...maps: Array<Map<string, number>>) {
  const merged = new Map<string, number>()
  for (const map of maps) {
    for (const [key, value] of map) {
      merged.set(key, value)
    }
  }
  return merged
}

function topicTags(card: Record<string, unknown>, relatedRefs: Array<NonNullable<ReturnType<typeof adaptObjectRef>>>) {
  const explicitTags = readArray(card.tags).map((tag) => readString(tag)).filter(isString)
  const badgeTags = readArray(card.badges)
    .map((badge) => readString(readObject(badge)?.label))
    .filter(isString)
    .filter((label) => !["community_pulse", "community_discussion_pulse"].includes(label))
  const relatedTags = relatedRefs
    .filter((ref) => ref.objectType === "topic")
    .map((ref) => ref.label ?? ref.objectId)
  return uniqueStrings([...explicitTags, ...badgeTags, ...relatedTags]).slice(0, 10)
}

function sourceNameFromSubtitle(value?: string) {
  return value?.split("|")[0]?.trim() || undefined
}

function dateFromSubtitle(value?: string) {
  const candidate = value?.split("|")[1]?.trim()
  if (!candidate) return undefined
  const date = new Date(candidate)
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString()
}

function scoreToDisplayNumber(value: number) {
  return Math.round((value <= 1 ? value * 100 : value) * 10) / 10
}

function normalizeMetricName(value: string) {
  return value.trim().toLowerCase().replaceAll("_", " ")
}

function safeHttpsUrl(value?: string) {
  if (!value) return undefined
  try {
    const url = new URL(value)
    if (url.protocol !== "https:") return undefined
    for (const key of [...url.searchParams.keys()]) {
      if (/token|secret|key|password|auth/i.test(key)) {
        url.searchParams.delete(key)
      }
    }
    return url.toString()
  } catch {
    return undefined
  }
}

function publicExcerpt(value: unknown, maxLength: number) {
  const text = readString(value)?.replace(/\s+/g, " ").trim()
  if (!text) return undefined
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 3).trimEnd()}...`
}

function uniqueEntities(values: CommunityEntity[]) {
  const seen = new Set<string>()
  return values.filter((entity) => {
    const key = `${entity.type}:${entity.id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.filter(Boolean))]
}

function uniqueValue(value: string, counts: Map<string, number>) {
  const normalized = value || "community-topic"
  const count = counts.get(normalized) ?? 0
  counts.set(normalized, count + 1)
  return count === 0 ? normalized : `${normalized}-${count + 1}`
}

function slugify(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
  return slug || "community-topic"
}

function readObject(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

function readNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function isString(value: string | undefined): value is string {
  return typeof value === "string" && value.length > 0
}

function isPresent<T>(value: T | undefined): value is T {
  return value !== undefined
}
