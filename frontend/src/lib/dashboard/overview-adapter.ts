import type {
  DashboardBoardType,
  DashboardMetric,
  DashboardOverview,
  DashboardQuality,
  LegacyDashboardOverview,
  RightInsight,
  TechRadarItem,
  TopStory,
  TrendingTopic
} from "@/types/dashboard"

type JsonRecord = Record<string, unknown>

export type DashboardAdapterContext = {
  dataState?: DashboardOverview["dataState"]
  generatedAt?: string | null
  sourceLabel?: string
  notices?: string[]
}

export type BoardOutputSource = {
  boardType: string
  payload: unknown
  generatedAt?: string | null
  sourceLabel?: string
}

const BOARD_TO_STORY_BOARD: Record<string, TopStory["board"]> = {
  ai_news: "news",
  news: "news",
  paper_radar: "paper",
  paper: "paper",
  project_radar: "project",
  project: "project",
  github_project: "project",
  community_pulse: "community",
  community: "community",
  community_thread: "community"
}

const REQUIRED_BOARDS = ["ai_news", "project_radar", "paper_radar", "community_pulse"]

export function adaptDashboardArtifact(payload: unknown, context: DashboardAdapterContext = {}): DashboardOverview | null {
  const crossBoard = findCrossBoardPayload(payload)
  if (!crossBoard) {
    return null
  }

  const boardType = text(crossBoard.board_type) || text(crossBoard.boardType) || "cross_board"
  if (boardType !== "cross_board" && !isBoardOutputLike(crossBoard)) {
    return null
  }

  return buildOverviewFromRecords([crossBoard], {
    ...context,
    dataState: context.dataState ?? "ready"
  })
}

export function adaptBoardGroupToOverview(sources: BoardOutputSource[], context: DashboardAdapterContext = {}): DashboardOverview | null {
  const records = sources
    .map((source): JsonRecord | null => {
      const payload = unwrapPayload(source.payload)
      const record = asRecord(payload)
      if (!record) {
        return null
      }
      return {
        ...record,
        board_type: text(record.board_type) || text(record.boardType) || source.boardType,
        generated_at: text(record.generated_at) || text(record.generatedAt) || source.generatedAt || undefined
      } as JsonRecord
    })
    .filter((item): item is JsonRecord => item !== null)

  if (!records.length) {
    return null
  }

  const presentBoards = new Set(records.map((record) => text(record.board_type)).filter(Boolean))
  const missingBoards = REQUIRED_BOARDS.filter((board) => !presentBoards.has(board))
  const notices = [...(context.notices ?? [])]
  if (missingBoards.length) {
    notices.push(`Partial cross-board overview: missing ${missingBoards.join(", ")} output.`)
  }

  return buildOverviewFromRecords(records, {
    ...context,
    dataState: "partial",
    notices
  })
}

export function adaptMockDashboardOverview(value: unknown): DashboardOverview {
  const maybeOverview = asRecord(value)
  if (maybeOverview && Array.isArray(maybeOverview.metrics) && "dataState" in maybeOverview) {
    return {
      ...(maybeOverview as DashboardOverview),
      dataState: "fallback",
      notices: uniqueStrings([...(arrayStrings(maybeOverview.notices)), "Showing local fallback"])
    }
  }

  const legacy = value as LegacyDashboardOverview
  const generatedAt = legacy.brief?.updatedAt ?? new Date().toISOString()
  const topStories: TopStory[] = (legacy.topStories ?? []).slice(0, 6).map((story, index) => ({
    id: story.id || `fallback-story-${index + 1}`,
    title: story.title || "Fallback story",
    summary: story.summary || "Bundled fallback dashboard story.",
    board: "news",
    objectId: story.id,
    href: `/news/${encodeURIComponent(story.id || `fallback-story-${index + 1}`)}`,
    score: story.heatScore,
    confidence: story.qualityScore,
    publishedAt: story.publishedAt,
    sourceName: story.sourceName,
    tags: story.tags
  }))
  const trendingTopics: TrendingTopic[] = (legacy.trendingTopics ?? []).slice(0, 6).map((topic, index) => ({
    id: topic.id || `fallback-topic-${index + 1}`,
    name: topic.name || "Fallback topic",
    summary: topic.summary || "Bundled fallback topic.",
    trend: topic.trend ?? "stable",
    heatScore: topic.heatScore,
    signalCount: topic.itemCount,
    boards: ["cross_board"]
  }))

  return {
    generatedAt,
    dataState: "fallback",
    metrics: [
      metric("signals", "Today signals", legacy.metrics?.newsCollectedToday ?? 0, "Collected AI signals", legacy.metricDeltas?.newsCollectedToday),
      metric("news", "Important news", legacy.metrics?.deduplicatedItems ?? topStories.length, "Ranked news stories", legacy.metricDeltas?.deduplicatedItems),
      metric("projects", "Hot projects", 0, "Project radar items"),
      metric("papers", "Hot papers", 0, "Paper radar items"),
      metric("community", "Community discussions", 0, "Community pulse topics"),
      metric("high_confidence", "High-confidence insights", legacy.metrics?.avgQualityScore ?? 0, "Quality score", legacy.metricDeltas?.avgQualityScore)
    ],
    brief: {
      title: legacy.brief?.title ?? "Local fallback dashboard",
      summary: legacy.brief?.summary ?? "Showing bundled fallback data because no live cross-board output is available.",
      keyFindings: legacy.brief?.keyFindings ?? [],
      coreJudgments: [legacy.brief?.mainTrend].filter(isNonEmptyString),
      readingPath: topStories.slice(0, 4).map((story) => ({
        id: story.id,
        label: story.title,
        href: story.href,
        description: story.summary,
        board: story.board
      })),
      agentNotes: ["Showing local fallback"],
      mainTrend: legacy.brief?.mainTrend,
      riskNote: legacy.brief?.riskNote,
      updatedAt: generatedAt,
      reportId: legacy.brief?.reportId
    },
    topStories,
    trendingTopics,
    techRadar: [
      radarItem("fallback-paper", legacy.techRadar?.paper, "paper", "/papers"),
      radarItem("fallback-project", legacy.techRadar?.repo, "project", "/projects"),
      radarItem("fallback-framework", legacy.techRadar?.framework, "framework")
    ].filter((item): item is TechRadarItem => item !== null),
    rightInsights: [
      {
        id: "fallback",
        title: "Fallback mode",
        summary: "Showing local fallback",
        tone: "warning"
      }
    ],
    quality: {
      status: legacy.qualityGate?.status ?? "unknown",
      score: legacy.metrics?.avgQualityScore,
      summary: legacy.qualityGate?.summary ?? "Fallback quality status.",
      generatedAt
    },
    notices: ["Showing local fallback"]
  }
}

export function emptyDashboardOverview(notices: string[] = []): DashboardOverview {
  return {
    generatedAt: null,
    dataState: "empty",
    metrics: [
      metric("signals", "Today signals", 0, "Collected AI signals"),
      metric("news", "Important news", 0, "Ranked news stories"),
      metric("projects", "Hot projects", 0, "Project radar items"),
      metric("papers", "Hot papers", 0, "Paper radar items"),
      metric("community", "Community discussions", 0, "Community pulse topics"),
      metric("high_confidence", "High-confidence insights", 0, "Cross-board insights")
    ],
    brief: {
      title: "No cross-board intelligence yet",
      summary: "No backend or local cross-board output currently has displayable content.",
      keyFindings: [],
      coreJudgments: [],
      readingPath: [],
      agentNotes: notices,
      updatedAt: null
    },
    topStories: [],
    trendingTopics: [],
    techRadar: [],
    rightInsights: [],
    quality: {
      status: "unknown",
      summary: "No quality signal is available yet.",
      generatedAt: null
    },
    notices
  }
}

export function hasDashboardContent(overview: DashboardOverview | null | undefined): overview is DashboardOverview {
  if (!overview) {
    return false
  }
  return Boolean(
    overview.topStories.length ||
      overview.trendingTopics.length ||
      overview.techRadar.length ||
      overview.rightInsights.length ||
      overview.metrics.some((item) => numericValue(item.value) > 0) ||
      overview.brief.keyFindings.length ||
      overview.brief.coreJudgments.length
  )
}

function buildOverviewFromRecords(records: JsonRecord[], context: DashboardAdapterContext): DashboardOverview {
  const cards = records.flatMap((record) => extractCards(record))
  const insights = records.flatMap((record) => extractInsights(record))
  const generatedAt = context.generatedAt ?? latestGeneratedAt(records, cards)
  const topStories = cardsToTopStories(cards).slice(0, 8)
  const trendingTopics = buildTrendingTopics(cards, records).slice(0, 8)
  const techRadar = buildTechRadar(records, cards).slice(0, 6)
  const quality = buildQuality(records, generatedAt)
  const notices = uniqueStrings(context.notices ?? [])
  const metrics = buildMetrics(records, cards, insights)
  const brief = buildBrief({
    records,
    cards,
    insights,
    topStories,
    trendingTopics,
    generatedAt,
    dataState: context.dataState ?? "ready",
    notices
  })
  const rightInsights = buildRightInsights({
    records,
    generatedAt,
    quality,
    notices,
    dataState: context.dataState ?? "ready",
    sourceLabel: context.sourceLabel
  })

  return {
    generatedAt,
    dataState: context.dataState ?? "ready",
    metrics,
    brief,
    topStories,
    trendingTopics,
    techRadar,
    rightInsights,
    quality,
    notices
  }
}

function findCrossBoardPayload(payload: unknown): JsonRecord | null {
  const root = unwrapPayload(payload)
  const record = asRecord(root)
  if (!record) {
    return null
  }

  for (const key of ["cross_board_output", "crossBoardOutput", "board_output", "boardOutput"]) {
    const nested = findCrossBoardPayload(record[key])
    if (nested) {
      return nested
    }
  }

  const output = asRecord(record.output)
  if (output) {
    for (const key of ["cross_board_output", "crossBoardOutput", "board_output", "boardOutput"]) {
      const nested = findCrossBoardPayload(output[key])
      if (nested) {
        return nested
      }
    }
  }

  const boardType = text(record.board_type) || text(record.boardType)
  if (boardType === "cross_board" || isBoardOutputLike(record)) {
    return record
  }

  return null
}

function isBoardOutputLike(record: JsonRecord) {
  return Array.isArray(record.cards) || Array.isArray(record.radar_items) || Array.isArray(record.insights)
}

function unwrapPayload(payload: unknown): unknown {
  const record = asRecord(payload)
  if (!record) {
    return payload
  }
  return record.content ?? record.data ?? payload
}

function extractCards(record: JsonRecord): JsonRecord[] {
  const direct = arrayRecords(record.cards)
  const nestedSections = arrayRecords(record.sections).flatMap((section) => arrayRecords(section.cards))
  return uniqueBy([...direct, ...nestedSections], (card) => text(card.card_id) || text(card.id) || `${text(card.title)}:${text(card.summary)}`)
}

function extractInsights(record: JsonRecord): JsonRecord[] {
  return [
    ...arrayRecords(record.insights),
    ...arrayRecords(record.right_insights),
    ...arrayRecords(record.agent_notes).map((note) => ({ summary: text(note.summary) || text(note.title) }))
  ]
}

function cardsToTopStories(cards: JsonRecord[]): TopStory[] {
  return cards
    .map(cardToTopStory)
    .filter((story): story is TopStory => story !== null)
    .sort((left, right) => (right.score ?? 0) - (left.score ?? 0))
}

function cardToTopStory(card: JsonRecord): TopStory | null {
  const board = storyBoardFromCard(card)
  if (!board) {
    return null
  }
  const primaryRef = asRecord(card.primary_object_ref) ?? asRecord(card.primaryObjectRef)
  const objectId = text(primaryRef?.object_id) || text(primaryRef?.objectId) || text(card.object_id) || text(card.card_id) || text(card.id)
  const id = stableId(objectId || text(card.title) || text(card.summary) || board)
  const title = firstText([card.title, primaryRef?.label, card.name, card.subtitle]) || titleCase(board)
  const summary = firstText([card.summary, card.description, card.ranking_reason]) || title
  return {
    id,
    title,
    summary,
    board,
    objectType: text(primaryRef?.object_type) || text(primaryRef?.objectType) || text(card.board_type),
    objectId: objectId || id,
    href: storyHref(board, objectId || id),
    score: scorePercent(asRecord(card.score)?.value ?? asRecord(card.ranking_features)?.weighted_score ?? asRecord(card.ranking_features)?.score),
    confidence: scorePercent(asRecord(card.confidence)?.value ?? asRecord(card.quality)?.confidence),
    publishedAt: firstText([card.published_at, card.publishedAt, card.generated_at, card.generatedAt]),
    sourceName: firstText(sourceRefs(card).map((ref) => ref.sourceName)),
    tags: uniqueStrings([...badgeLabels(card.badges), ...relatedLabels(card.related_refs)]).slice(0, 6),
    reason: text(card.ranking_reason) || undefined
  }
}

function storyBoardFromCard(card: JsonRecord): TopStory["board"] | null {
  const values = [
    text(card.board_type),
    text(card.boardType),
    text(asRecord(card.metadata)?.board_type),
    text(asRecord(card.metadata)?.boardType),
    text(asRecord(card.primary_object_ref)?.object_type),
    text(asRecord(card.primaryObjectRef)?.objectType)
  ]
  for (const value of values) {
    const normalized = value.toLowerCase()
    if (BOARD_TO_STORY_BOARD[normalized]) {
      return BOARD_TO_STORY_BOARD[normalized]
    }
  }
  return null
}

function storyHref(board: TopStory["board"], id: string) {
  const encoded = encodeURIComponent(id)
  if (board === "paper") return `/papers/${encoded}`
  if (board === "project") return `/projects/${encoded}`
  if (board === "community") return `/community/${encoded}`
  return `/news/${encoded}`
}

function buildTrendingTopics(cards: JsonRecord[], records: JsonRecord[]): TrendingTopic[] {
  const explicit = records.flatMap((record) => {
    return [...arrayRecords(record.trending_topics), ...arrayRecords(record.trendingTopics), ...arrayRecords(record.topics)].map((topic) => {
      const id = stableId(text(topic.id) || text(topic.topic_id) || text(topic.name) || text(topic.title))
      return {
        id,
        name: firstText([topic.name, topic.title, topic.label]) || "Topic",
        summary: firstText([topic.summary, topic.description]) || "Cross-board topic",
        trend: trendValue(topic.trend),
        heatScore: scorePercent(topic.heatScore ?? topic.heat_score ?? topic.score),
        signalCount: numberValue(topic.signalCount ?? topic.signal_count ?? topic.itemCount ?? topic.item_count),
        boards: boardList(topic.boards),
        confidence: scorePercent(topic.confidence),
        href: text(topic.href) || undefined
      } satisfies TrendingTopic
    })
  })

  const grouped = new Map<string, { name: string; summaries: string[]; count: number; score: number; boards: Set<DashboardBoardType> }>()
  for (const card of cards) {
    const board = storyBoardFromCard(card)
    for (const ref of arrayRecords(card.related_refs)) {
      const type = text(ref.object_type) || text(ref.objectType)
      if (type !== "topic") {
        continue
      }
      const name = text(ref.label) || text(ref.name) || text(ref.object_id) || "Topic"
      const key = stableId(text(ref.object_id) || name)
      const existing = grouped.get(key) ?? { name, summaries: [], count: 0, score: 0, boards: new Set<DashboardBoardType>() }
      existing.count += 1
      existing.score += scorePercent(asRecord(card.score)?.value ?? asRecord(card.ranking_features)?.score) ?? 0
      existing.summaries.push(text(card.summary))
      if (board) {
        existing.boards.add(board)
      }
      grouped.set(key, existing)
    }
  }

  const inferred = [...grouped.entries()].map(([id, value]) => ({
    id,
    name: value.name,
    summary: firstText(value.summaries) || `${value.count} related signal(s) across boards.`,
    trend: value.count > 1 ? "rising" : "stable",
    heatScore: value.count ? Math.round(value.score / value.count) : undefined,
    signalCount: value.count,
    boards: value.boards.size ? [...value.boards] : ["cross_board"]
  } satisfies TrendingTopic))

  return uniqueBy([...explicit, ...inferred], (topic) => topic.id).sort((left, right) => (right.signalCount ?? 0) - (left.signalCount ?? 0))
}

function buildTechRadar(records: JsonRecord[], cards: JsonRecord[]): TechRadarItem[] {
  const explicit = records.flatMap((record) => {
    return [...arrayRecords(record.radar_items), ...arrayRecords(record.tech_radar), ...arrayRecords(record.techRadar)].map(radarRecordToItem)
  }).filter((item): item is TechRadarItem => item !== null)

  const inferred = cards
    .map((card): TechRadarItem | null => {
      const board = storyBoardFromCard(card)
      if (board !== "paper" && board !== "project") {
        return null
      }
      const story = cardToTopStory(card)
      if (!story) {
        return null
      }
      return {
        id: `radar-${story.id}`,
        name: story.title,
        summary: story.summary,
        category: board,
        href: story.href,
        board,
        score: story.score
      } satisfies TechRadarItem
    })
    .filter((item): item is TechRadarItem => item !== null)

  return uniqueBy([...explicit, ...inferred], (item) => item.href ?? item.id)
}

function radarRecordToItem(item: JsonRecord): TechRadarItem | null {
  const name = firstText([item.name, item.title, item.label])
  if (!name) {
    return null
  }
  const category = radarCategory(firstText([item.category, item.type, item.item_type, item.board_type]))
  return {
    id: stableId(text(item.id) || text(item.item_id) || name),
    name,
    summary: firstText([item.summary, item.description, item.reason]) || name,
    category,
    href: text(item.href) || text(item.url) || undefined,
    board: boardType(firstText([item.board, item.board_type, item.boardType])),
    score: scorePercent(item.score ?? item.heatScore ?? item.heat_score),
    metric: firstText([item.metric, item.subtitle])
  }
}

function buildMetrics(records: JsonRecord[], cards: JsonRecord[], insights: JsonRecord[]): DashboardMetric[] {
  const stats = records.map((record) => asRecord(record.stats)).filter((item): item is JsonRecord => item !== undefined)
  const cardsByBoard = cards.reduce<Record<TopStory["board"], number>>(
    (acc, card) => {
      const board = storyBoardFromCard(card)
      if (board) {
        acc[board] += 1
      }
      return acc
    },
    { news: 0, paper: 0, project: 0, community: 0 }
  )
  const signalCount = sum(stats.map((item) => numberValue(item.signal_count ?? item.signalCount))) || cards.length
  const highConfidence = cards.filter((card) => (scorePercent(asRecord(card.confidence)?.value ?? asRecord(card.quality)?.confidence) ?? 0) >= 80).length
  const insightCount = sum(stats.map((item) => numberValue(item.insight_count ?? item.insightCount))) || insights.length

  return [
    metric("signals", "Today signals", signalCount, "Collected across boards"),
    metric("news", "Important news", cardsByBoard.news, "AI news stories"),
    metric("projects", "Hot projects", cardsByBoard.project, "Project radar items"),
    metric("papers", "Hot papers", cardsByBoard.paper, "Paper radar items"),
    metric("community", "Community discussions", cardsByBoard.community, "Community pulse topics"),
    metric("high_confidence", "High-confidence insights", highConfidence || insightCount, "Reliable cross-board findings")
  ]
}

function buildBrief(input: {
  records: JsonRecord[]
  cards: JsonRecord[]
  insights: JsonRecord[]
  topStories: TopStory[]
  trendingTopics: TrendingTopic[]
  generatedAt: string | null
  dataState: DashboardOverview["dataState"]
  notices: string[]
}): DashboardOverview["brief"] {
  const report = input.records.map((record) => asRecord(asRecord(record.metadata)?.report)).find(Boolean)
  const title = firstText([
    report?.title,
    ...input.records.map((record) => record.title),
    input.dataState === "partial" ? "Cross-board intelligence snapshot" : "Cross-board intelligence"
  ]) ?? "Cross-board intelligence"
  const summary =
    firstText([report?.summary, ...input.records.map((record) => record.summary)]) ??
    `Synthesized ${input.topStories.length} story(s) and ${input.trendingTopics.length} topic(s) across boards.`
  const findings = uniqueStrings([
    ...input.insights.flatMap((insight) => [text(insight.title), text(insight.summary)]),
    ...input.topStories.slice(0, 3).map((story) => story.reason || story.summary)
  ]).slice(0, 5)
  const coreJudgments = uniqueStrings([
    input.trendingTopics[0] ? `${input.trendingTopics[0].name} is the strongest current cross-board topic.` : undefined,
    ...input.topStories.slice(0, 2).map((story) => `${story.title} is worth following from ${story.board}.`)
  ]).slice(0, 4)
  const readingPath = input.topStories.slice(0, 4).map((story) => ({
    id: story.id,
    label: story.title,
    href: story.href,
    description: story.summary,
    board: story.board
  }))
  const agentNotes = uniqueStrings([
    ...input.notices,
    input.dataState === "partial" ? "Partial cross-board overview generated from available board outputs." : undefined
  ]).slice(0, 5)

  return {
    title,
    summary,
    keyFindings: findings,
    coreJudgments,
    readingPath,
    agentNotes,
    mainTrend: input.trendingTopics[0]?.name,
    riskNote: input.dataState === "partial" ? "Some board outputs were unavailable, so trend attribution is partial." : undefined,
    updatedAt: input.generatedAt
  }
}

function buildRightInsights(input: {
  records: JsonRecord[]
  generatedAt: string | null
  quality: DashboardQuality
  notices: string[]
  dataState: DashboardOverview["dataState"]
  sourceLabel?: string
}): RightInsight[] {
  return [
    {
      id: "freshness",
      title: "Data freshness",
      summary: input.generatedAt ? `Generated at ${input.generatedAt}` : "No generated timestamp is available.",
      tone: input.generatedAt ? "info" : "warning"
    },
    {
      id: "quality",
      title: "Quality status",
      summary: input.quality.summary,
      value: input.quality.score,
      tone: qualityTone(input.quality.status)
    },
    {
      id: "source",
      title: "Source",
      summary: input.sourceLabel ?? "Cross-board intelligence output",
      tone: input.dataState === "partial" ? "warning" : "accent"
    },
    {
      id: "agent-notes",
      title: "Agent notes",
      summary: input.notices[0] ?? "No notable source warnings.",
      items: input.notices.slice(0, 4),
      tone: input.notices.length ? "warning" : "success"
    }
  ]
}

function buildQuality(records: JsonRecord[], generatedAt: string | null): DashboardQuality {
  const qualityRecord =
    records.map((record) => asRecord(record.quality) ?? asRecord(record.quality_summary) ?? asRecord(record.qualitySummary)).find(Boolean) ??
    records.map((record) => asRecord(record.gate_result) ?? asRecord(record.gateResult)).find(Boolean)
  const status = qualityStatus(firstText([qualityRecord?.status, qualityRecord?.decision]))
  const checks = arrayRecords(qualityRecord?.checks).map((check, index) => ({
    id: text(check.check_id) || text(check.id) || `check-${index + 1}`,
    label: text(check.check_type) || text(check.label) || text(check.dimension) || `Check ${index + 1}`,
    status: booleanValue(check.passed) === false ? "failed" : booleanValue(check.passed) === true ? "passed" : qualityStatus(text(check.status)),
    detail: text(check.reason) || text(check.detail) || undefined
  }))

  return {
    status,
    score: scorePercent(qualityRecord?.score ?? qualityRecord?.quality_score ?? qualityRecord?.confidence),
    summary: firstText([qualityRecord?.summary, qualityRecord?.reason]) || (status === "passed" ? "Quality checks passed." : "Quality status requires review."),
    generatedAt,
    checks
  }
}

function latestGeneratedAt(records: JsonRecord[], cards: JsonRecord[]) {
  const dates = [
    ...records.flatMap((record) => [text(record.generated_at), text(record.generatedAt), text(record.finished_at), text(record.finishedAt)]),
    ...cards.flatMap((card) => [text(card.generated_at), text(card.generatedAt), text(card.published_at), text(card.publishedAt)])
  ].filter(isNonEmptyString)

  return dates.sort((left, right) => Date.parse(right) - Date.parse(left))[0] ?? null
}

function metric(id: string, label: string, value: number | string, description?: string, delta?: string): DashboardMetric {
  return { id, label, value, description, delta }
}

function sourceRefs(card: JsonRecord) {
  return [...arrayRecords(card.evidence_refs), ...arrayRecords(asRecord(card.provenance)?.source_refs)].map((ref) => ({
    sourceName: text(ref.source_name) || text(ref.sourceName),
    sourceUrl: text(ref.source_url) || text(ref.sourceUrl) || text(ref.url)
  }))
}

function badgeLabels(value: unknown) {
  return arrayRecords(value).map((badge) => text(badge.label)).filter(Boolean)
}

function relatedLabels(value: unknown) {
  return arrayRecords(value).map((ref) => text(ref.label)).filter(Boolean)
}

function boardList(value: unknown): DashboardBoardType[] {
  const boards = arrayStrings(value).map(boardType).filter((item): item is DashboardBoardType => item !== undefined)
  return boards.length ? boards : ["cross_board"]
}

function boardType(value: unknown): DashboardBoardType | undefined {
  const normalized = text(value).toLowerCase()
  if (normalized === "cross_board") return "cross_board"
  const storyBoard = BOARD_TO_STORY_BOARD[normalized]
  return storyBoard
}

function radarCategory(value: unknown): TechRadarItem["category"] {
  const normalized = text(value).toLowerCase()
  if (normalized.includes("paper")) return "paper"
  if (normalized.includes("project") || normalized.includes("repo")) return "project"
  if (normalized.includes("model")) return "model"
  if (normalized.includes("community")) return "community"
  if (normalized.includes("framework")) return "framework"
  return "tool"
}

function trendValue(value: unknown): TrendingTopic["trend"] {
  const normalized = text(value).toLowerCase()
  if (normalized === "falling") return "falling"
  if (normalized === "stable") return "stable"
  return "rising"
}

function qualityStatus(value: unknown): DashboardQuality["status"] {
  const normalized = text(value).toLowerCase()
  if (normalized === "passed" || normalized === "pass") return "passed"
  if (normalized === "failed" || normalized === "fail" || normalized === "blocked") return "failed"
  if (normalized === "review" || normalized === "needs_review" || normalized === "warning") return "review"
  return "unknown"
}

function qualityTone(status: DashboardQuality["status"]): RightInsight["tone"] {
  if (status === "passed") return "success"
  if (status === "failed") return "danger"
  if (status === "review") return "warning"
  return "neutral"
}

function radarItem(id: string, name: string | undefined, category: TechRadarItem["category"], href?: string): TechRadarItem | null {
  if (!name) {
    return null
  }
  return {
    id,
    name,
    summary: name,
    category,
    href
  }
}

function titleCase(value: string) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function firstText(values: unknown[]) {
  return values.map(text).find(Boolean)
}

function scorePercent(value: unknown): number | undefined {
  const score = numberValue(value)
  if (score === undefined) {
    return undefined
  }
  const normalized = score <= 1 ? score * 100 : score
  return Math.max(0, Math.min(100, Math.round(normalized)))
}

function numericValue(value: unknown) {
  return numberValue(value) ?? 0
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const number = Number(value)
    return Number.isFinite(number) ? number : undefined
  }
  return undefined
}

function booleanValue(value: unknown) {
  return typeof value === "boolean" ? value : undefined
}

function sum(values: Array<number | undefined>) {
  let total = 0
  for (const value of values) {
    total += value ?? 0
  }
  return total
}

function stableId(value: string) {
  const input = value || "dashboard-item"
  const slug = input.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 48) || "dashboard-item"
  let hash = 0
  for (let index = 0; index < input.length; index += 1) {
    hash = (hash * 31 + input.charCodeAt(index)) >>> 0
  }
  return `${slug}-${hash.toString(16).slice(0, 8)}`
}

function uniqueBy<T>(values: T[], key: (value: T) => string): T[] {
  const seen = new Set<string>()
  return values.filter((value) => {
    const id = key(value)
    if (seen.has(id)) return false
    seen.add(id)
    return true
  })
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const clean = value?.trim()
    if (!clean || seen.has(clean)) {
      continue
    }
    seen.add(clean)
    result.push(clean)
  }
  return result
}

function asRecord(value: unknown): JsonRecord | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : undefined
}

function arrayRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is JsonRecord => item !== undefined) : []
}

function arrayStrings(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map(text).filter(Boolean)
}

function text(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : ""
}

function isNonEmptyString(value: string | undefined): value is string {
  return Boolean(value)
}
