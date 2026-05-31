import fs from "node:fs"
import path from "node:path"
import { safeApiGet } from "@/lib/api/server"
import { normalizePdfUrl, paperPdfUrlFromSource, sortPapers } from "@/lib/papers/format"
import { getBenchmarksForMethod, paperMethods, paperTasks } from "@/lib/papers/catalog"
import { arxivIdFromUrl, enrichPapersForPublicStream, githubRepoSlug, normalizeDoi, normalizeGithubRepoUrl } from "@/lib/papers/enrichment"
import type { MethodRef, Paper, PaperDataState, PaperListResult, PaperMethod, PaperPeriod, PaperSort, PaperTask, TaskRef } from "@/lib/papers/types"

type SourceSignal = {
  authors?: unknown
  collected_at?: unknown
  confidence?: unknown
  content?: unknown
  evidence_type?: unknown
  lineage?: Record<string, unknown>
  metadata?: Record<string, unknown>
  metrics?: Record<string, unknown>
  published_at?: unknown
  raw_content?: unknown
  raw_payload?: SourceSignal
  signal_id?: unknown
  signal_type?: unknown
  source?: {
    source_name?: unknown
    source_type?: unknown
    source_url?: unknown
    url?: unknown
  }
  source_id?: unknown
  source_item_id?: unknown
  source_name?: unknown
  source_reliability?: unknown
  source_url?: unknown
  source_urls?: unknown
  source_type?: unknown
  summary?: unknown
  tags?: unknown
  title?: unknown
  url?: unknown
}

type PaperRadarArtifact = {
  board_signals?: SourceSignal[]
  evidence_bundle?: { items?: SourceSignal[] }
  items?: SourceSignal[]
  normalized_items?: SourceSignal[]
  ranked_items?: Array<{ item?: SourceSignal; final_score?: unknown }>
  raw_signals?: SourceSignal[]
  raw_items?: SourceSignal[]
  ranked_signals?: Array<{ item?: SourceSignal; final_score?: unknown }>
}

type PaperCollectionCache = {
  source?: unknown
  query?: unknown
  collectedAt?: unknown
  count?: unknown
  papers?: unknown
}

type PapersApiResponse = {
  papers?: unknown
}

type PaperTasksApiResponse = {
  tasks?: unknown
}

type PaperMethodsApiResponse = {
  methods?: unknown
}

const ARTIFACT_FILE_NAMES = [
  "data_buffer.final.json",
  "output.json",
  "raw_items.json",
  "normalized_items.json",
  "ranked_items.json"
]
const MAX_ARTIFACT_BYTES = 8_000_000
const API_PAPER_LOAD_LIMIT = 5000
const PAPER_SOURCE_TYPES = new Set(["arxiv", "paper_index"])
const BLOCKED_SOURCE_TYPES = new Set(["official_blog", "ai_news", "rss", "blog", "press_release"])
const LOCAL_PAPER_CACHE_PATH = path.resolve(process.cwd(), "data", "papers", "arxiv-papers.json")

export type PaperRuntimeData = {
  papers: Paper[]
  source: "backend" | "cache" | "artifact" | "empty"
  dataState: PaperDataState
  notices: string[]
  collectedAt?: string
}

export type PaperListQuery = {
  q?: string
  period?: PaperPeriod
  sort?: PaperSort
  task?: string
  method?: string
  limit?: number
  offset?: number
}

export type PaperTaxonomyResult<T> = {
  items: T[]
  source: "backend" | "taxonomy"
  dataState: PaperDataState
  notices: string[]
}

export async function getPublishedPapers() {
  return (await getPublishedPaperData()).papers
}

export async function getPublishedPaperData(): Promise<PaperRuntimeData> {
  const apiPapers = await loadApiPapers()
  if (apiPapers.length) {
    return {
      papers: normalizeRuntimePapers(apiPapers),
      source: "backend",
      dataState: "ready",
      notices: []
    }
  }

  const cachedPapers = loadCachedPapers()
  if (cachedPapers.length) {
    return {
      papers: normalizeRuntimePapers(cachedPapers),
      source: "cache",
      dataState: "degraded",
      notices: ["Backend paper API is unavailable; showing tracked paper cache."]
    }
  }

  const extractedPapers = loadLatestExtractedPapers()
  if (extractedPapers.length) {
    return {
      papers: normalizeRuntimePapers(await enrichPapersForPublicStream(extractedPapers)),
      source: "artifact",
      dataState: "degraded",
      notices: ["Backend paper API and tracked cache are unavailable; showing latest Paper Radar artifacts."]
    }
  }

  return {
    papers: [],
    source: "empty",
    dataState: "empty",
    notices: ["No backend, tracked cache, or artifact papers are available."]
  }
}

export async function getPaperListResult(query: PaperListQuery = {}): Promise<PaperListResult> {
  const data = await getPublishedPaperData()
  const period = parsePaperPeriod(query.period)
  const sort = parsePaperSort(query.sort)
  const limit = positiveInteger(query.limit, 1000)
  const offset = Math.max(0, positiveInteger(query.offset, 0))
  const filtered = filterPapers(data.papers, {
    q: query.q,
    period,
    task: query.task,
    method: query.method
  })
  const sorted = sortPapers(filtered, sort)
  const papers = sorted.slice(offset, offset + limit)

  return {
    source: data.source,
    query: query.q ?? "",
    period,
    sort,
    task: query.task,
    method: query.method,
    collectedAt: data.collectedAt ?? new Date().toISOString(),
    paper_count: papers.length,
    total_count: sorted.length,
    source_count: uniqueStrings(data.papers.map((paper) => paper.venue ?? paper.sourceRefs?.[0]?.sourceName ?? "papers")).length,
    limit,
    offset,
    has_next: offset + papers.length < sorted.length,
    dataState: data.dataState,
    notices: data.notices,
    papers
  }
}

export async function getPaperById(paperId: string): Promise<Paper | null> {
  const result = await safeApiGet<{ paper?: unknown }>(`/api/v1/papers/${encodeURIComponent(paperId)}`)
  if (result.ok && isPaper(result.data?.paper)) {
    return normalizeRuntimePaper(result.data.paper)
  }
  if (result.ok && isPaper(result.data)) {
    return normalizeRuntimePaper(result.data)
  }

  const data = await getPublishedPaperData()
  return data.papers.find((paper) => paper.id === paperId || paper.slug === paperId) ?? null
}

export async function getPaperTasksResult(): Promise<PaperTaxonomyResult<PaperTask>> {
  const [apiTasks, paperData] = await Promise.all([loadApiPaperTasks(), getPublishedPaperData()])
  const source = apiTasks.length ? "backend" : "taxonomy"
  const tasks = deriveTasks(apiTasks.length ? apiTasks : paperTasks, paperData.papers)
  return {
    items: tasks,
    source,
    dataState: taxonomyDataState(apiTasks.length > 0, paperData.dataState),
    notices: apiTasks.length
      ? paperData.notices
      : ["Paper task API is unavailable; showing taxonomy with real paper-derived counts.", ...paperData.notices]
  }
}

export async function getPaperMethodsResult(): Promise<PaperTaxonomyResult<PaperMethod>> {
  const [apiMethods, apiTasks, paperData] = await Promise.all([loadApiPaperMethods(), loadApiPaperTasks(), getPublishedPaperData()])
  const source = apiMethods.length ? "backend" : "taxonomy"
  const tasks = deriveTasks(apiTasks.length ? apiTasks : paperTasks, paperData.papers)
  const methods = deriveMethods(apiMethods.length ? apiMethods : paperMethods, tasks, paperData.papers)
  return {
    items: methods,
    source,
    dataState: taxonomyDataState(apiMethods.length > 0, paperData.dataState),
    notices: apiMethods.length
      ? paperData.notices
      : ["Paper method API is unavailable; showing taxonomy with real paper-derived counts.", ...paperData.notices]
  }
}

export async function loadApiPapers(): Promise<Paper[]> {
  const result = await safeApiGet<PapersApiResponse>(`/api/v1/papers?limit=${API_PAPER_LOAD_LIMIT}`)
  if (!result.ok) {
    return []
  }

  const rawPapers = Array.isArray(result.data?.papers) ? result.data.papers : []
  return rawPapers.filter(isAuthoritativePaper)
}

export async function loadApiPaperTasks(): Promise<PaperTask[]> {
  const result = await safeApiGet<PaperTasksApiResponse>("/api/v1/papers/tasks")
  if (!result.ok || !Array.isArray(result.data?.tasks)) {
    return []
  }
  return result.data.tasks.filter(isPaperTask)
}

export async function loadApiPaperMethods(): Promise<PaperMethod[]> {
  const result = await safeApiGet<PaperMethodsApiResponse>("/api/v1/papers/methods")
  if (!result.ok || !Array.isArray(result.data?.methods)) {
    return []
  }
  return result.data.methods.filter(isPaperMethod)
}

function normalizeRuntimePapers(papers: Paper[]) {
  return papers.filter((paper) => paper.isPublished !== false).map(normalizeRuntimePaper)
}

function normalizeRuntimePaper(paper: Paper): Paper {
  const repoUrl = normalizeGithubRepoUrl(paper.repoUrl)
  const implementations = paper.implementations?.length
    ? paper.implementations
    : repoUrl
      ? [
          {
            id: `${paper.id}-repo`,
            name: githubRepoSlug(repoUrl) ?? "GitHub repository",
            repoUrl,
            provider: "GitHub",
            githubStars: paper.githubStars
          }
        ]
      : []

  return {
    ...paper,
    repoUrl,
    implementations
  }
}

function taxonomyDataState(hasApiTaxonomy: boolean, paperDataState: PaperDataState): PaperDataState {
  if (!hasApiTaxonomy) {
    return paperDataState === "empty" ? "empty" : "degraded"
  }
  return paperDataState
}

function filterPapers(
  papers: Paper[],
  query: { q?: string; period: PaperPeriod; task?: string; method?: string }
) {
  const search = lower(query.q ?? "")
  const periodStart = periodStartDate(query.period)

  return papers.filter((paper) => {
    if (periodStart && new Date(paper.publishedAt).getTime() < periodStart.getTime()) {
      return false
    }
    if (query.task && !matchesRef(query.task, paper.taskRefs)) {
      return false
    }
    if (query.method && !matchesRef(query.method, paper.methodRefs)) {
      return false
    }
    if (!search) {
      return true
    }

    const haystack = [
      paper.title,
      paper.titleZh,
      paper.abstractSnippet,
      paper.abstractSnippetZh,
      paper.authors.join(" "),
      paper.tags.join(" "),
      paper.taskRefs.map((task) => `${task.slug} ${task.name} ${task.nameZh ?? ""} ${task.group ?? ""}`).join(" "),
      paper.methodRefs.map((method) => `${method.slug} ${method.name} ${method.nameZh ?? ""} ${method.area ?? ""}`).join(" ")
    ].join(" ")

    return lower(haystack).includes(search)
  })
}

function deriveTasks(tasks: PaperTask[], papers: Paper[]): PaperTask[] {
  return tasks.map((task) => {
    const relatedPapers = papersForTask(papers, task.slug)
    const methodCount = uniqueStrings(relatedPapers.flatMap((paper) => paper.methodRefs.map((method) => method.slug))).length
    const benchmarkCount = countBenchmarksFromPapers(relatedPapers)
    const implementationCount = relatedPapers.filter(hasImplementationSignal).length
    return {
      ...task,
      paperCount: relatedPapers.length,
      methodCount,
      benchmarkCount,
      latestPaperIds: sortPapers(relatedPapers, "newest").slice(0, 5).map((paper) => paper.id),
      implementationCount
    }
  })
}

function deriveMethods(methods: PaperMethod[], tasks: PaperTask[], papers: Paper[]): PaperMethod[] {
  const taskBySlug = new Map(tasks.map((task) => [task.slug, task]))

  return methods.map((method) => {
    const relatedPapers = papersForMethod(papers, method.slug)
    const relatedTaskSlugs = uniqueStrings(relatedPapers.flatMap((paper) => paper.taskRefs.map((task) => task.slug)))
    const relatedTasks = relatedTaskSlugs.map((slug) => taskBySlug.get(slug)).filter(isPaperTask)
    const implementationCount = relatedPapers.filter(hasImplementationSignal).length
    return {
      ...method,
      paperCount: relatedPapers.length,
      taskCount: relatedTaskSlugs.length,
      implementationCount,
      relatedTasks: relatedTasks.length ? relatedTasks : method.relatedTasks,
      commonBenchmarks: method.commonBenchmarks?.length ? method.commonBenchmarks : getBenchmarksForMethod(method.slug),
      representativePaperIds: sortPapers(relatedPapers, "trending").slice(0, 5).map((paper) => paper.id),
      relatedProjectIds: relatedPapers.flatMap((paper) => paper.implementations?.map((item) => item.id) ?? [])
    }
  })
}

function papersForTask(papers: Paper[], slug: string) {
  return papers.filter((paper) => paper.taskRefs.some((task) => task.slug === slug))
}

function papersForMethod(papers: Paper[], slug: string) {
  return papers.filter((paper) => paper.methodRefs.some((method) => method.slug === slug))
}

function hasImplementationSignal(paper: Paper) {
  return Boolean(normalizeGithubRepoUrl(paper.repoUrl) || paper.implementations?.length)
}

function countBenchmarksFromPapers(papers: Paper[]) {
  return uniqueStrings(papers.flatMap((paper) => (paper.benchmarks ?? []).map((benchmark) => benchmark.id || benchmark.name))).length
}

function matchesRef(value: string, refs: Array<TaskRef | MethodRef>) {
  const normalized = lower(value)
  return refs.some((ref) => lower(ref.slug) === normalized || lower(ref.name) === normalized || lower(ref.nameZh ?? "") === normalized)
}

function periodStartDate(period: PaperPeriod) {
  const days = period === "daily" ? 1 : period === "weekly" ? 7 : period === "monthly" ? 30 : 0
  if (!days) {
    return null
  }
  const start = new Date()
  start.setDate(start.getDate() - days)
  return start
}

function parsePaperPeriod(value: PaperPeriod | undefined): PaperPeriod {
  return value === "daily" || value === "weekly" || value === "monthly" || value === "all" ? value : "all"
}

function parsePaperSort(value: PaperSort | undefined): PaperSort {
  return value === "newest" || value === "most_cited" || value === "trending" ? value : "trending"
}

function positiveInteger(value: number | undefined, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : fallback
}

function isAuthoritativePaper(value: unknown): value is Paper {
  if (!isRecord(value)) {
    return false
  }
  return Boolean(
    text(value.id) &&
      text(value.slug) &&
      text(value.title) &&
      text(value.abstractSnippet) &&
      Array.isArray(value.authors) &&
      text(value.publishedAt) &&
      value.isPublished !== undefined
  )
}

function isPaperTask(value: unknown): value is PaperTask {
  return (
    isRecord(value) &&
    text(value.id) !== "" &&
    text(value.slug) !== "" &&
    text(value.name) !== "" &&
    text(value.description) !== "" &&
    typeof value.paperCount === "number" &&
    Array.isArray(value.sisterTasks) &&
    Array.isArray(value.commonMethods)
  )
}

function isPaperMethod(value: unknown): value is PaperMethod {
  return (
    isRecord(value) &&
    text(value.id) !== "" &&
    text(value.slug) !== "" &&
    text(value.name) !== "" &&
    text(value.description) !== "" &&
    typeof value.paperCount === "number" &&
    typeof value.taskCount === "number" &&
    Array.isArray(value.relatedTasks) &&
    Array.isArray(value.relatedMethods)
  )
}

export function loadCachedPapers(): Paper[] {
  const cache = readPaperCollectionCache(LOCAL_PAPER_CACHE_PATH)
  const rawPapers = Array.isArray(cache?.papers) ? cache.papers : []
  return rawPapers.map(cachedPaperToPaper).filter(isPaper)
}

function readPaperCollectionCache(filePath: string): PaperCollectionCache | null {
  if (!fs.existsSync(filePath)) {
    return null
  }

  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as PaperCollectionCache
  } catch {
    return null
  }
}

function cachedPaperToPaper(value: unknown): Paper | null {
  if (!isRecord(value)) {
    return null
  }

  const title = text(value.title)
  const abstractSnippet = stripHtml(text(value.abstractSnippet) || text(value.summary))
  const id = text(value.id)
  const paperUrl = text(value.paperUrl)
  const arxivUrl = text(value.arxivUrl) || paperUrl
  const pdfUrl = normalizePdfUrl(text(value.pdfUrl)) ?? paperPdfUrlFromSource(arxivUrl)

  if (!id || !title || !abstractSnippet || !paperUrl) {
    return null
  }

  const tags = cachedTags(value.tags)
  const taskRefs = inferTasks(title, `${abstractSnippet} ${tags.join(" ")}`, "arxiv")
  const methodRefs = inferMethods(title, `${abstractSnippet} ${tags.join(" ")}`)
  const repoUrl = normalizeGithubRepoUrl(text(value.repoUrl))

  return {
    id,
    slug: text(value.slug) || slugify(title) || id,
    title,
    abstractSnippet,
    authors: cachedAuthors(value.authors),
    publishedAt: text(value.publishedAt) || new Date().toISOString(),
    venue: text(value.venue) || "arXiv",
    citationDoi: normalizeDoi(text(value.citationDoi)),
    tags,
    taskRefs,
    methodRefs,
    paperUrl,
    arxivUrl,
    pdfUrl,
    repoUrl,
    sourceRefs: [
      {
        sourceId: text(value.sourceId) || id,
        sourceName: text(value.sourceName) || text(value.venue) || "arXiv",
        sourceType: text(value.sourceType) || "arxiv",
        url: paperUrl,
        title
      }
    ],
    githubStars: numberValue(value.githubStars),
    citationCount: numberValue(value.citationCount),
    isPublished: value.isPublished !== false
  }
}

function loadLatestExtractedPapers(): Paper[] {
  const artifacts = candidateArtifacts()
  for (const artifactPath of artifacts) {
    const artifact = readArtifact(artifactPath)
    if (!artifact) {
      continue
    }

    const signals = dedupeSignals(extractSignals(artifact).filter(isPaperSignal))
    const papers = signals.map((signal, index) => signalToPaper(signal, index)).filter(isPaper)
    if (papers.length) {
      return papers
    }
  }

  return []
}

function candidateArtifacts() {
  const runsDir = path.resolve(process.cwd(), "..", ".newsroom", "runs")
  if (!fs.existsSync(runsDir)) {
    return []
  }

  return fs.readdirSync(runsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .flatMap((entry) => {
      const runDir = path.join(runsDir, entry.name)
      return ARTIFACT_FILE_NAMES.map((fileName) => path.join(runDir, fileName))
    })
    .filter((filePath) => {
      if (!fs.existsSync(filePath)) {
        return false
      }
      const stat = fs.statSync(filePath)
      return stat.isFile() && stat.size > 2 && stat.size <= MAX_ARTIFACT_BYTES
    })
    .sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs)
}

function readArtifact(filePath: string): PaperRadarArtifact | SourceSignal[] | null {
  if (!fs.existsSync(filePath)) {
    return null
  }

  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as PaperRadarArtifact | SourceSignal[]
  } catch {
    return null
  }
}

function extractSignals(artifact: PaperRadarArtifact | SourceSignal[]): SourceSignal[] {
  if (Array.isArray(artifact)) {
    return arraySignals(artifact)
  }

  return [
    ...arraySignals(artifact.board_signals),
    ...arraySignals(artifact.raw_signals),
    ...arraySignals(artifact.raw_items),
    ...arraySignals(artifact.normalized_items),
    ...arraySignals(artifact.items),
    ...arraySignals(artifact.evidence_bundle?.items),
    ...rankedSignals(artifact.ranked_signals),
    ...rankedSignals(artifact.ranked_items)
  ]
}

function isPaperSignal(signal: SourceSignal) {
  const raw = isObject(signal.raw_payload) ? signal.raw_payload : signal
  const sourceType = lower(text(signal.source_type) || text(raw.source_type) || text(signal.source?.source_type))
  const sourceName = lower(text(signal.source_name) || text(raw.source_name) || text(signal.source?.source_name))
  const signalType = lower(text(signal.signal_type) || text(raw.signal_type))
  const sourceId = lower(text(signal.source_id) || text(raw.source_id))
  const evidenceType = lower(text(signal.evidence_type) || text(raw.evidence_type))
  const metadataSignalKind = lower(text(signal.metadata?.signal_kind) || text(raw.metadata?.signal_kind))
  const metadataSourceKind = lower(text(signal.metadata?.source_kind) || text(raw.metadata?.source_kind))
  const lineage = isRecord(signal.lineage) ? signal.lineage : {}
  const sourceUrl = lower([
    text(signal.url),
    text(raw.url),
    text(signal.source_url),
    text(raw.source_url),
    text(signal.source?.url),
    text(signal.source?.source_url),
    text(raw.source?.url),
    text(raw.source?.source_url),
    text(lineage.canonical_url),
    text(lineage.raw_url)
  ].join(" "))

  if (BLOCKED_SOURCE_TYPES.has(sourceType) || signalType === "ai_news") {
    return false
  }
  if (sourceName.includes("openai news") || sourceUrl.includes("openai.com/news") || sourceUrl.includes("openai.com/index")) {
    return false
  }
  if (signalType === "paper" || evidenceType === "paper" || metadataSignalKind === "paper") {
    return true
  }
  if (PAPER_SOURCE_TYPES.has(sourceType) || metadataSourceKind === "paper" || metadataSourceKind === "arxiv") {
    return true
  }
  if (sourceId.includes("arxiv") || sourceUrl.includes("arxiv.org")) {
    return true
  }

  return false
}

function signalToPaper(signal: SourceSignal, index: number): Paper | null {
  const raw = isObject(signal.raw_payload) ? signal.raw_payload : signal
  const title = text(signal.title) || text(raw.title)
  const summary = stripHtml(text(signal.summary) || text(signal.content) || text(raw.summary) || text(raw.raw_content))
  const lineage = isRecord(signal.lineage) ? signal.lineage : {}
  const urls = candidateUrls(signal, raw, lineage)
  const url = urls[0] ?? ""

  if (!title || !summary) {
    return null
  }

  const sourceType = text(signal.source_type) || text(raw.source_type) || text(signal.source?.source_type)
  const sourceName = text(signal.source_name) || text(raw.source_name) || text(signal.source?.source_name)
  const publishedAt = text(signal.published_at) || text(raw.published_at) || text(signal.collected_at) || new Date().toISOString()
  const taskRefs = inferTasks(title, summary, sourceType)
  const methodRefs = inferMethods(title, summary)
  const pdfUrl = realPdfUrl(signal, raw, urls)
  const repoUrl = realRepoUrl(signal, raw, urls)
  const citationDoi = realCitationDoi(signal, raw, urls)

  return {
    id: text(signal.signal_id) || text(raw.source_item_id) || `real-paper-${index + 1}`,
    slug: slugify(title) || `real-paper-${index + 1}`,
    title,
    abstractSnippet: summary,
    authors: authors(raw.authors ?? signal.authors, sourceName),
    publishedAt,
    venue: sourceLabel(sourceName, sourceType),
    citationDoi,
    tags: tags(raw.tags ?? signal.tags, sourceType),
    taskRefs,
    methodRefs,
    paperUrl: url,
    arxivUrl: sourceType === "arxiv" || url.includes("arxiv.org") ? url : undefined,
    pdfUrl,
    repoUrl,
    sourceRefs: [
      {
        sourceId: text(signal.source_id) || text(raw.source_id),
        sourceName,
        sourceType,
        url,
        title
      }
    ],
    evidenceRefs: [
      {
        evidenceId: text(signal.signal_id) || text(raw.signal_id),
        sourceName,
        sourceType,
        url,
        title,
        summary
      }
    ],
    isPublished: true
  }
}

function dedupeSignals(signals: SourceSignal[]) {
  const seen = new Set<string>()
  const result: SourceSignal[] = []

  for (const signal of signals) {
    const raw = isObject(signal.raw_payload) ? signal.raw_payload : signal
    const key = text(signal.url) || text(raw.url) || text(signal.title) || text(raw.title)
    if (!key || seen.has(key)) {
      continue
    }
    seen.add(key)
    result.push(signal)
  }

  return result
}

function inferTasks(title: string, summary: string, sourceType: string) {
  const content = `${title} ${summary}`.toLowerCase()
  const candidates: TaskRef[] = []

  pushIf(candidates, "coding", "coding-agents")
  pushIf(candidates, "code", "coding-agents")
  pushIf(candidates, "agent", "agents")
  pushIf(candidates, "reason", "reasoning")
  pushIf(candidates, "education", "language-modeling")
  pushIf(candidates, "geometry", "reasoning")
  pushIf(candidates, "review", "coding-agents")
  pushIf(candidates, "model", "language-modeling")

  if (sourceType === "arxiv") {
    pushIf(candidates, "paper", "language-modeling")
  }

  return candidates.length ? uniqueRefs(candidates) : [requiredTask("agents")]

  function pushIf(target: TaskRef[], needle: string, slug: string) {
    if (content.includes(needle)) {
      target.push(requiredTask(slug))
    }
  }
}

function inferMethods(title: string, summary: string) {
  const content = `${title} ${summary}`.toLowerCase()
  const candidates: MethodRef[] = []

  pushIf(candidates, "rag", "rag")
  pushIf(candidates, "retrieval", "rag")
  pushIf(candidates, "agent", "agent")
  pushIf(candidates, "codex", "tool-use")
  pushIf(candidates, "coding", "tool-use")
  pushIf(candidates, "review", "tool-use")
  pushIf(candidates, "model", "large-language-model")
  pushIf(candidates, "geometry", "chain-of-thought")

  return candidates.length ? uniqueRefs(candidates) : [requiredMethod("large-language-model")]

  function pushIf(target: MethodRef[], needle: string, slug: string) {
    if (content.includes(needle)) {
      target.push(requiredMethod(slug))
    }
  }
}

function requiredTask(slug: string) {
  return paperTasks.find((task) => task.slug === slug) ?? paperTasks[0]
}

function requiredMethod(slug: string) {
  return paperMethods.find((method) => method.slug === slug) ?? paperMethods[0]
}

function uniqueRefs<T extends { slug: string }>(refs: T[]) {
  return refs.filter((ref, index, all) => all.findIndex((candidate) => candidate.slug === ref.slug) === index)
}

function text(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function realPdfUrl(signal: SourceSignal, raw: SourceSignal, urls: string[]) {
  const metadata = isRecord(signal.metadata) ? signal.metadata : {}
  const rawMetadata = isRecord(raw.metadata) ? raw.metadata : {}

  const explicitPdfUrl =
    text((signal as Record<string, unknown>).pdfUrl) ||
    text((signal as Record<string, unknown>).pdf_url) ||
    text((raw as Record<string, unknown>).pdfUrl) ||
    text((raw as Record<string, unknown>).pdf_url) ||
    text(metadata.pdfUrl) ||
    text(metadata.pdf_url) ||
    text(rawMetadata.pdfUrl) ||
    text(rawMetadata.pdf_url)

  return normalizePdfUrl(explicitPdfUrl) ?? urls.map((url) => paperPdfUrlFromSource(url)).find(Boolean)
}

function realRepoUrl(signal: SourceSignal, raw: SourceSignal, urls: string[]) {
  const metadata = isRecord(signal.metadata) ? signal.metadata : {}
  const rawMetadata = isRecord(raw.metadata) ? raw.metadata : {}

  const candidates = uniqueStrings([
    text((signal as Record<string, unknown>).repoUrl),
    text((signal as Record<string, unknown>).repo_url),
    text((signal as Record<string, unknown>).githubUrl),
    text((signal as Record<string, unknown>).github_url),
    text((signal as Record<string, unknown>).codeUrl),
    text((signal as Record<string, unknown>).code_url),
    text((raw as Record<string, unknown>).repoUrl),
    text((raw as Record<string, unknown>).repo_url),
    text((raw as Record<string, unknown>).githubUrl),
    text((raw as Record<string, unknown>).github_url),
    text((raw as Record<string, unknown>).codeUrl),
    text((raw as Record<string, unknown>).code_url),
    text(metadata.repository_url),
    text(metadata.repo_url),
    text(metadata.github_url),
    text(metadata.code_url),
    text(metadata.repository),
    text(rawMetadata.repository_url),
    text(rawMetadata.repo_url),
    text(rawMetadata.github_url),
    text(rawMetadata.code_url),
    text(rawMetadata.repository),
    ...urls
  ].filter(Boolean))

  return candidates.map((value) => normalizeGithubRepoUrl(value)).find(Boolean)
}

function realCitationDoi(signal: SourceSignal, raw: SourceSignal, urls: string[]) {
  const metadata = isRecord(signal.metadata) ? signal.metadata : {}
  const rawMetadata = isRecord(raw.metadata) ? raw.metadata : {}

  const explicitDoi = uniqueStrings([
    text((signal as Record<string, unknown>).doi),
    text((signal as Record<string, unknown>).citationDoi),
    text((signal as Record<string, unknown>).citation_doi),
    text((raw as Record<string, unknown>).doi),
    text((raw as Record<string, unknown>).citationDoi),
    text((raw as Record<string, unknown>).citation_doi),
    text(metadata.doi),
    text(metadata.citationDoi),
    text(metadata.citation_doi),
    text(rawMetadata.doi),
    text(rawMetadata.citationDoi),
    text(rawMetadata.citation_doi)
  ].filter(Boolean)).map((value) => normalizeDoi(value)).find(Boolean)

  if (explicitDoi) {
    return explicitDoi
  }

  const arxivId = uniqueStrings([
    text(metadata.arxiv_id),
    text(rawMetadata.arxiv_id),
    text((signal as Record<string, unknown>).arxivId),
    text((raw as Record<string, unknown>).arxivId),
    ...urls.map((url) => arxivIdFromUrl(url) ?? "")
  ].filter(Boolean)).map((value) => value.replace(/v\d+$/i, "")).find(Boolean)

  return arxivId ? `10.48550/arxiv.${arxivId}` : undefined
}

function candidateUrls(signal: SourceSignal, raw: SourceSignal, lineage: Record<string, unknown>) {
  return uniqueStrings([
    text(signal.url),
    text(raw.url),
    text(signal.source_url),
    text(raw.source_url),
    text(signal.source?.url),
    text(signal.source?.source_url),
    text(raw.source?.url),
    text(raw.source?.source_url),
    text(lineage.canonical_url),
    text(lineage.raw_url),
    ...urlArray(signal.source_urls),
    ...urlArray(raw.source_urls)
  ].filter(Boolean))
}

function urlArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : []
}

function authors(value: unknown, sourceName: string) {
  if (Array.isArray(value)) {
    const names = value.map((item) => text(item)).filter(Boolean)
    if (names.length) {
      return names
    }
  }
  return [sourceName || "NewsRoom Extracted Source"]
}

function cachedAuthors(value: unknown) {
  if (Array.isArray(value)) {
    const names = value.map((item) => text(item)).filter(Boolean)
    if (names.length) {
      return names
    }
  }
  return ["arXiv"]
}

function tags(value: unknown, sourceType: string) {
  const values = Array.isArray(value)
    ? value.map((item) => text(item)).filter(Boolean)
    : text(value).split(/\s+/).filter(Boolean)

  return uniqueStrings([sourceType, ...values].filter(Boolean)).slice(0, 4)
}

function cachedTags(value: unknown) {
  const values = Array.isArray(value)
    ? value.map((item) => text(item)).filter(Boolean)
    : text(value).split(/\s+/).filter(Boolean)

  return uniqueStrings(values).slice(0, 4)
}

function sourceLabel(sourceName: string, sourceType: string) {
  if (sourceName) {
    return sourceName
  }
  if (sourceType === "arxiv") {
    return "arXiv"
  }
  return sourceType || "Extracted"
}

function stripHtml(value: string) {
  return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 80)
}

function uniqueStrings(values: string[]) {
  return values.filter((value, index, all) => all.indexOf(value) === index)
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}

function arraySignals(value: unknown): SourceSignal[] {
  return Array.isArray(value) ? value.filter(isObject) : []
}

function rankedSignals(value: unknown): SourceSignal[] {
  if (!Array.isArray(value)) {
    return []
  }

  return value.map((entry) => (isRecord(entry) ? entry.item : null)).filter(isObject)
}

function lower(value: string) {
  return value.toLowerCase()
}

function isObject(value: unknown): value is SourceSignal {
  return Boolean(value && typeof value === "object")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object")
}

function isPaper(value: unknown): value is Paper {
  return isRecord(value) && Boolean(text(value.id) && text(value.slug) && text(value.title) && text(value.abstractSnippet))
}
