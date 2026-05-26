import fs from "node:fs"
import path from "node:path"
import { safeApiGet } from "@/lib/api/server"
import { applyNewsFilters, getFilterOptions, paginateNews } from "@/lib/news/filters"
import type { CredibilityLevel, SourceType } from "@/types/common"
import type { EvidenceRef, NewsEntity, NewsFilters, NewsItem, NewsListResult, RelatedRef } from "@/types/news"

type JsonRecord = Record<string, unknown>

type NewsDataLoad = {
  items: NewsItem[]
  source: "backend" | "artifact" | "fallback"
  generatedAt?: string
  notices: string[]
}

type RunListResponse = {
  runs?: unknown
}

type ArtifactResponse = {
  content?: unknown
}

const AI_NEWS_WORKFLOW_ID = "ai_news-productized-board"
const MAX_ARTIFACT_BYTES = 8_000_000
const SOURCE_TYPES = new Set<SourceType>([
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
])
const FORBIDDEN_TEXT = /raw_payload|raw_content|raw_html|token|secret/i

export async function getNewsListResult(filters: NewsFilters): Promise<NewsListResult> {
  const load = await loadNewsData()
  return buildNewsListResult(load, filters)
}

export function buildNewsListResult(load: NewsDataLoad, filters: NewsFilters): NewsListResult {
  const allFiltered = applyNewsFilters(load.items, filters)
  return {
    page: paginateNews(allFiltered, filters.page, filters.pageSize),
    allItems: load.items,
    allFiltered,
    options: getFilterOptions(load.items),
    dataState: load.source === "fallback" ? "fallback" : "ready",
    source: load.source,
    notices: load.notices,
    generatedAt: load.generatedAt,
  }
}

export async function loadNewsData(): Promise<NewsDataLoad> {
  const notices: string[] = []
  const backend = await loadBackendNewsData()
  notices.push(...backend.notices)
  if (backend.items.length) {
    return backend
  }

  const artifact = loadLatestArtifactNewsData()
  notices.push(...artifact.notices)
  if (artifact.items.length) {
    return {
      ...artifact,
      notices,
    }
  }

  return {
    items: [],
    source: "fallback",
    generatedAt: new Date().toISOString(),
    notices: [...notices, "No real ai_news backend output or local artifact is available; showing an empty AI News Board."],
  }
}

async function loadBackendNewsData(): Promise<NewsDataLoad> {
  const runsResult = await safeApiGet<RunListResponse>(`/api/v1/runs?limit=50&workflow_id=${encodeURIComponent(AI_NEWS_WORKFLOW_ID)}`)
  if (!runsResult.ok) {
    return {
      items: [],
      source: "backend",
      notices: [`Backend run lookup failed: ${runsResult.errorMessage}`],
    }
  }

  const runs = arrayRecords(runsResult.data.runs).filter(isAiNewsRun)
  for (const run of runs) {
    const runId = text(run.run_id)
    if (!runId) {
      continue
    }
    const output = await loadBackendArtifact(runId, "output")
    const outputItems = mapArtifactToNewsItems(output.content)
    if (outputItems.length) {
      return {
        items: outputItems,
        source: "backend",
        generatedAt: generatedAtFromArtifact(output.content) ?? text(run.finished_at) ?? text(run.started_at) ?? undefined,
        notices: [],
      }
    }

    const boardOutput = await loadBackendArtifact(runId, "board_output")
    const boardItems = mapArtifactToNewsItems(boardOutput.content)
    if (boardItems.length) {
      return {
        items: boardItems,
        source: "backend",
        generatedAt: generatedAtFromArtifact(boardOutput.content) ?? text(run.finished_at) ?? text(run.started_at) ?? undefined,
        notices: [],
      }
    }
  }

  return {
    items: [],
    source: "backend",
    notices: ["Backend did not expose a populated ai_news board output."],
  }
}

async function loadBackendArtifact(runId: string, artifactKey: "output" | "board_output"): Promise<ArtifactResponse> {
  const result = await safeApiGet<ArtifactResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${artifactKey}`)
  if (!result.ok) {
    return {}
  }
  return result.data
}

function loadLatestArtifactNewsData(): NewsDataLoad {
  const candidates = localArtifactCandidates()
  for (const candidate of candidates) {
    const output = readJsonFile(path.join(candidate.runDir, "output.json"))
    const outputItems = mapArtifactToNewsItems(output)
    if (outputItems.length) {
      return {
        items: outputItems,
        source: "artifact",
        generatedAt: generatedAtFromArtifact(output) ?? candidate.modifiedAt,
        notices: [],
      }
    }

    const boardOutput = readJsonFile(path.join(candidate.runDir, "board_output.json"))
    const boardItems = mapArtifactToNewsItems(boardOutput)
    if (boardItems.length) {
      return {
        items: boardItems,
        source: "artifact",
        generatedAt: generatedAtFromArtifact(boardOutput) ?? candidate.modifiedAt,
        notices: [],
      }
    }
  }

  return {
    items: [],
    source: "artifact",
    notices: ["No local ai_news artifact with public news cards was found."],
  }
}

function localArtifactCandidates() {
  return runsRoots()
    .flatMap((runsRoot) => {
      if (!fs.existsSync(runsRoot)) {
        return []
      }
      return fs.readdirSync(runsRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => path.join(runsRoot, entry.name))
    })
    .map((runDir) => {
      const manifest = readJsonFile(path.join(runDir, "manifest.json"))
      const modifiedAt = latestModifiedAt([
        path.join(runDir, "output.json"),
        path.join(runDir, "board_output.json"),
        path.join(runDir, "manifest.json"),
      ])
      return { runDir, manifest, modifiedAt }
    })
    .filter((candidate) => isAiNewsManifest(candidate.manifest) || candidate.runDir.toLowerCase().includes("ai_news"))
    .sort((left, right) => Date.parse(right.modifiedAt) - Date.parse(left.modifiedAt))
}

function runsRoots() {
  if (process.env.NEWSROOM_RUNS_ROOT) {
    return [process.env.NEWSROOM_RUNS_ROOT]
  }
  const roots = [
    path.resolve(process.cwd(), ".newsroom", "runs"),
    path.resolve(process.cwd(), "..", ".newsroom", "runs"),
  ]
  return [...new Set(roots)]
}

function latestModifiedAt(filePaths: string[]) {
  const times = filePaths
    .filter((filePath) => fs.existsSync(filePath))
    .map((filePath) => fs.statSync(filePath).mtimeMs)
  return new Date(Math.max(0, ...times)).toISOString()
}

function readJsonFile(filePath: string): unknown {
  if (!fs.existsSync(filePath)) {
    return undefined
  }
  const stat = fs.statSync(filePath)
  if (!stat.isFile() || stat.size <= 2 || stat.size > MAX_ARTIFACT_BYTES) {
    return undefined
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as unknown
  } catch {
    return undefined
  }
}

function mapArtifactToNewsItems(artifact: unknown): NewsItem[] {
  const payload = unwrapArtifactPayload(artifact)
  const cards = extractCards(payload)
  const signals = signalLookup(payload)
  const items = cards
    .map((card) => cardToNewsItem(card, signals.get(signalIdFromCard(card))))
    .filter((item): item is NewsItem => item !== null)
  return dedupeNewsItems(items)
}

function unwrapArtifactPayload(artifact: unknown): unknown {
  const record = asRecord(artifact)
  if (record && "content" in record) {
    return record.content
  }
  return artifact
}

function extractCards(payload: unknown): JsonRecord[] {
  if (Array.isArray(payload)) {
    return arrayRecords(payload)
  }
  const record = asRecord(payload)
  if (!record) {
    return []
  }
  return [
    ...arrayRecords(asRecord(record.board_output)?.cards),
    ...arrayRecords(record.cards),
    ...arrayRecords(asRecord(record.output)?.cards),
  ]
}

function signalLookup(payload: unknown) {
  const lookup = new Map<string, JsonRecord>()
  const record = asRecord(payload)
  if (!record) {
    return lookup
  }
  const signals = [
    ...arrayRecords(record.board_signals),
    ...arrayRecords(record.prepared_signals),
    ...arrayRecords(record.deduplicated_signals),
    ...arrayRecords(record.raw_signals),
    ...arrayRecords(record.evidence_items),
    ...rankedRecords(record.ranked_signals),
    ...rankedRecords(record.ranked_items),
    ...arrayRecords(asRecord(record.evidence_bundle)?.items),
  ]
  for (const signal of signals) {
    const signalId = signalIdFromSignal(signal)
    if (signalId) {
      lookup.set(signalId, signal)
    }
  }
  return lookup
}

function cardToNewsItem(card: JsonRecord, signal?: JsonRecord): NewsItem | null {
  const rawPayload = asRecord(signal?.raw_payload)
  const rawSignal = signal ? { ...(rawPayload ?? {}), ...signal } : rawPayload
  const evidenceRefs = sourceRefsFromCard(card, rawSignal)
  const primarySource = evidenceRefs[0]
  const sourceUrl = cleanHttpsUrl(
    primarySource?.url ??
      text(rawSignal?.url) ??
      text(rawSignal?.source_url) ??
      text(asRecord(rawSignal?.source)?.url) ??
      text(asRecord(rawSignal?.source)?.source_url)
  )
  if (!sourceUrl) {
    return null
  }

  const sourceName =
    primarySource?.sourceName ??
    text(rawSignal?.source_name) ??
    text(asRecord(rawSignal?.source)?.source_name) ??
    hostLabel(sourceUrl)
  const sourceType = normalizeSourceType(
    primarySource?.sourceType ??
      text(rawSignal?.source_type) ??
      text(asRecord(rawSignal?.source)?.source_type)
  )
  const title = newsTitle(card, rawSignal, sourceUrl)
  const summary = text(card.summary) || text(rawSignal?.summary) || text(rawSignal?.content) || title
  const tags = newsTags(card, rawSignal)
  const relatedRefs = arrayRecords(card.related_refs)
  const topicRef = relatedRefs.find((ref) => text(ref.object_type) === "topic")
  const qualityScore = scoreToPercent(asRecord(card.quality)?.score)
  const heatScore = scoreToPercent(
    asRecord(card.ranking_features)?.weighted_score ??
      asRecord(card.ranking_features)?.score ??
      asRecord(card.score)?.value
  )
  const id = stableNewsId(text(card.card_id) || signalIdFromSignal(rawSignal) || sourceUrl)

  return {
    id,
    title,
    summary,
    detailedSummary: summary,
    whyItMatters: text(card.ranking_reason) || undefined,
    url: sourceUrl,
    sourceName,
    sourceType,
    sourceUrl,
    publishedAt: text(rawSignal?.published_at) || text(card.published_at) || primarySource?.capturedAt,
    collectedAt: text(rawSignal?.collected_at) || primarySource?.capturedAt || text(card.generated_at),
    category: inferCategory(card, rawSignal, tags, title, summary),
    tags,
    heatScore,
    qualityScore,
    credibility: credibilityFromSource(primarySource, card, rawSignal),
    topicId: text(topicRef?.object_id) || undefined,
    topicName: text(topicRef?.label) || undefined,
    evidenceIds: evidenceRefs.map((ref) => ref.id),
    evidenceRefs,
    entities: entityRefs(relatedRefs),
    relatedPapers: relatedObjectRefs(relatedRefs, "paper"),
    relatedProjects: relatedObjectRefs(relatedRefs, "project"),
    relatedCommunityTopics: relatedObjectRefs(relatedRefs, "community_thread", "topic"),
    status: "analyzed",
    keyFacts: keyFactsFromNews(summary, evidenceRefs),
    agentExplanation: [text(card.ranking_reason)].filter(Boolean),
  }
}

function sourceRefsFromCard(card: JsonRecord, signal?: JsonRecord): EvidenceRef[] {
  const refs = [
    ...arrayRecords(card.evidence_refs),
    ...arrayRecords(asRecord(card.provenance)?.source_refs),
    ...arrayRecords(asRecord(card.provenance)?.evidence_refs),
  ]
  const source = asRecord(signal?.source)
  if (source || signal) {
    refs.push({
      source_name: text(signal?.source_name) || text(source?.source_name),
      source_type: text(signal?.source_type) || text(source?.source_type),
      source_url: text(signal?.source_url) || text(source?.source_url),
      url: text(signal?.url) || text(source?.url),
      collected_at: text(signal?.collected_at) || text(source?.collected_at),
      external_id: text(signal?.source_item_id) || text(signal?.signal_id) || text(source?.external_id),
      reliability: text(signal?.source_reliability) || text(source?.reliability),
    })
  }

  const deduped = new Map<string, EvidenceRef>()
  for (const ref of refs) {
    const url = cleanHttpsUrl(text(ref.url) || text(ref.source_url))
    if (!url) {
      continue
    }
    const sourceType = normalizeSourceType(text(ref.source_type))
    const item: EvidenceRef = {
      id: stableNewsId(text(ref.external_id) || url),
      title: text(ref.title) || undefined,
      url,
      sourceName: text(ref.source_name) || hostLabel(url),
      sourceType,
      capturedAt: text(ref.collected_at) || text(ref.fetched_at) || undefined,
      summary: text(ref.summary) || undefined,
      quote: text(ref.quote) || undefined,
      credibility: credibilityFromReliability(text(ref.reliability)),
      confidenceScore: scoreToPercent(text(ref.confidence) || ref.confidence),
      relationReason: text(ref.relation_reason) || "Source evidence for this AI news item.",
    }
    deduped.set(item.url ?? item.id, item)
  }
  return [...deduped.values()]
}

function isAiNewsRun(run: JsonRecord) {
  return text(run.workflow_id) === AI_NEWS_WORKFLOW_ID || text(run.profile) === "business-productized" || text(run.run_id).includes("ai_news")
}

function isAiNewsManifest(value: unknown) {
  const manifest = asRecord(value)
  const productization = asRecord(manifest?.business_productization)
  return (
    text(manifest?.workflow_id) === AI_NEWS_WORKFLOW_ID ||
    text(productization?.board_type) === "ai_news" ||
    text(manifest?.run_id).includes("ai_news")
  )
}

function generatedAtFromArtifact(value: unknown) {
  const record = asRecord(unwrapArtifactPayload(value))
  return text(record?.generated_at) || text(asRecord(record?.board_output)?.generated_at) || undefined
}

function signalIdFromCard(card: JsonRecord) {
  return text(asRecord(card.metadata)?.signal_id)
}

function signalIdFromSignal(signal?: JsonRecord) {
  return text(signal?.signal_id) || text(signal?.source_item_id) || text(asRecord(signal?.raw_payload)?.signal_id)
}

function rankedRecords(value: unknown) {
  return arrayRecords(value)
    .map((item) => asRecord(item.item) ?? item)
    .filter((item): item is JsonRecord => item !== undefined)
}

function newsTitle(card: JsonRecord, signal: JsonRecord | undefined, sourceUrl: string) {
  const signalTitle = text(signal?.title) || text(signal?.headline)
  if (signalTitle) {
    return signalTitle
  }
  const cardTitle = text(card.title)
  if (cardTitle && cardTitle.length > 3) {
    return cardTitle
  }
  return hostLabel(sourceUrl)
}

function newsTags(card: JsonRecord, signal?: JsonRecord) {
  const labels = arrayRecords(card.badges)
    .map((badge) => text(badge.label))
    .filter(Boolean)
  const signalTags = arrayStrings(signal?.tags)
  const relatedLabels = arrayRecords(card.related_refs).map((ref) => text(ref.label)).filter(Boolean)
  return uniqueCleanStrings([...signalTags, ...labels, ...relatedLabels])
    .filter((value) => value !== "ai_news")
    .slice(0, 8)
}

function inferCategory(card: JsonRecord, signal: JsonRecord | undefined, tags: string[], title: string, summary: string) {
  const focus = text(asRecord(card.metadata)?.board_focus)
  const content = `${title} ${summary} ${tags.join(" ")} ${focus}`.toLowerCase()
  if (/\b(model|gpt|gemini|claude|llama|mistral|weights?)\b/.test(content)) {
    return "model-release"
  }
  if (/\b(policy|safety|security|regulation|governance|risk)\b/.test(content)) {
    return "policy-safety"
  }
  if (/\b(funding|acquire|acquisition|merger|investment|raises?)\b/.test(content)) {
    return "funding-ma"
  }
  if (/\b(ecosystem|community|partner|integration|marketplace)\b/.test(content)) {
    return "ecosystem"
  }
  if (/\b(product|launch|release|api|codex|chatgpt|agent)\b/.test(content)) {
    return "product-update"
  }
  const signalType = text(signal?.signal_type)
  return kebab(focus || signalType || "industry")
}

function credibilityFromSource(source: EvidenceRef | undefined, card: JsonRecord, signal?: JsonRecord): CredibilityLevel {
  if (source?.credibility) {
    return source.credibility
  }
  const reliability = text(signal?.source_reliability) || text(asRecord(signal?.source)?.reliability)
  if (reliability) {
    return credibilityFromReliability(reliability)
  }
  const confidence = scoreToUnit(asRecord(card.confidence)?.value)
  if (confidence >= 0.8) {
    return "high"
  }
  if (confidence >= 0.5) {
    return "medium"
  }
  return "low"
}

function credibilityFromReliability(value: string): CredibilityLevel {
  const normalized = value.toLowerCase()
  if (normalized === "official" || normalized === "high") {
    return "high"
  }
  if (normalized === "medium" || normalized === "unknown") {
    return "medium"
  }
  return "low"
}

function entityRefs(refs: JsonRecord[]): NewsEntity[] {
  return refs
    .filter((ref) => text(ref.object_type) === "entity")
    .map((ref) => ({
      id: stableNewsId(text(ref.object_id) || text(ref.label)),
      name: text(ref.label) || text(ref.object_id),
      type: text(ref.object_type) || "entity",
    }))
    .filter((entity) => entity.name)
}

function relatedObjectRefs(refs: JsonRecord[], ...types: string[]): RelatedRef[] {
  const typeSet = new Set(types)
  return refs
    .filter((ref) => typeSet.has(text(ref.object_type)))
    .map((ref) => ({
      id: stableNewsId(text(ref.object_id) || text(ref.label)),
      title: text(ref.label) || text(ref.object_id),
      type: text(ref.object_type),
    }))
    .filter((ref) => ref.title)
}

function keyFactsFromNews(summary: string, evidenceRefs: EvidenceRef[]) {
  const firstSentence = summary.split(/(?<=[.!?])\s+/)[0]?.trim()
  if (!firstSentence) {
    return []
  }
  const confidence: "high" | "medium" = evidenceRefs[0]?.credibility === "high" ? "high" : "medium"
  return [
    {
      id: stableNewsId(firstSentence),
      text: firstSentence,
      sourceName: evidenceRefs[0]?.sourceName,
      confidence,
      evidenceId: evidenceRefs[0]?.id,
    },
  ]
}

function dedupeNewsItems(items: NewsItem[]) {
  const seen = new Set<string>()
  const result: NewsItem[] = []
  for (const item of items) {
    const key = item.url || item.id
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push(item)
  }
  return result
}

function normalizeSourceType(value: unknown): SourceType {
  const normalized = String(value || "").trim().toLowerCase().replace("-", "_")
  if (SOURCE_TYPES.has(normalized as SourceType)) {
    return normalized as SourceType
  }
  if (normalized === "blog" || normalized === "press_release") {
    return "official_blog"
  }
  if (normalized === "news") {
    return "media"
  }
  return "custom"
}

function cleanHttpsUrl(value: unknown) {
  const raw = text(value)
  if (!raw) {
    return undefined
  }
  try {
    const url = new URL(raw)
    if (url.protocol !== "https:") {
      return undefined
    }
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

function hostLabel(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return "Source"
  }
}

function scoreToPercent(value: unknown): number | undefined {
  const score = numberValue(value)
  if (score === undefined) {
    return undefined
  }
  const normalized = score <= 1 ? score * 100 : score
  return Math.max(0, Math.min(100, Math.round(normalized)))
}

function scoreToUnit(value: unknown) {
  const score = numberValue(value)
  if (score === undefined) {
    return 0
  }
  return score > 1 ? score / 100 : score
}

function stableNewsId(value: string) {
  const clean = kebab(value).slice(0, 60) || "news"
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return `${clean}-${hash.toString(16).slice(0, 8)}`
}

function kebab(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")
}

function uniqueCleanStrings(values: string[]) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const clean = value.trim()
    if (!clean || FORBIDDEN_TEXT.test(clean) || seen.has(clean)) {
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
  return Array.isArray(value) ? value.map(text).filter(Boolean) : text(value).split(/\s+/).filter(Boolean)
}

function text(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value
  }
  if (typeof value === "string" && value.trim()) {
    const number = Number(value)
    return Number.isFinite(number) ? number : undefined
  }
  return undefined
}
