import type {
  EvidenceRef,
  ProjectCategory,
  ProjectCategoryRef,
  ProjectDataState,
  ProjectDetailResult,
  ProjectItem,
  ProjectLanguage,
  ProjectListOptions,
  ProjectListParams,
  ProjectListResult,
  ProjectMetric,
  ProjectSort,
  ProjectSource,
  RelatedCommunityRef,
  RelatedNewsRef,
  RelatedPaperRef,
} from "@/types/projects"

export const PROJECT_CATEGORIES: ProjectCategory[] = [
  "agent",
  "rag",
  "inference",
  "evaluation",
  "multimodal",
  "data",
  "devtool",
]

export const PROJECT_SOURCES: ProjectSource[] = ["github", "huggingface", "paper", "manual"]

export const PROJECT_LANGUAGES: ProjectLanguage[] = ["python", "typescript", "rust", "go", "other"]

export const PROJECT_SORTS: ProjectSort[] = ["trending", "newest", "stars", "growth", "quality"]

const DEFAULT_PAGE_SIZE = 24
const MAX_PAGE_SIZE = 100
const GITHUB_REPO_HOST = "github.com"
const FORBIDDEN_KEYS = new Set(["raw_payload", "raw_html", "raw_content", "full_text", "token", "secret", "api_key"])

type ProjectSourceKind = ProjectListResult["source"]

type ProjectBuildContext = {
  source: ProjectSourceKind
  sourceRunId?: string
  generatedAt?: string
}

type ProjectMappingResult = {
  items: ProjectItem[]
  generatedAt?: string
  notices: string[]
}

type GitHubRepo = {
  owner: string
  repo: string
  fullName: string
  url: string
}

export function normalizeProjectParams(params: ProjectListParams = {}): Required<Pick<ProjectListParams, "sort" | "page" | "pageSize">> & ProjectListParams {
  const page = clampInteger(params.page, 1, Number.MAX_SAFE_INTEGER, 1)
  const pageSize = clampInteger(params.pageSize, 1, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE)
  const sort = PROJECT_SORTS.includes(params.sort as ProjectSort) ? (params.sort as ProjectSort) : "trending"
  return {
    ...params,
    sort,
    page,
    pageSize,
  }
}

export function buildProjectListResult(payload: unknown, params: ProjectListParams, context: ProjectBuildContext): ProjectListResult {
  const normalized = normalizeProjectParams(params)
  if (context.source === "none") {
    return emptyProjectList(normalized, context, "empty", ["还没有找到 project_radar 数据。"])
  }

  const mapped = mapProjectPayload(payload)
  const allItems = sortProjects(mapped.items, normalized.sort)
  const filteredItems = sortProjects(filterProjects(allItems, normalized), normalized.sort)
  const total = filteredItems.length
  const start = (normalized.page - 1) * normalized.pageSize
  const items = filteredItems.slice(start, start + normalized.pageSize)
  const dataState = resolveDataState(Boolean(payload), allItems.length, mapped.notices)

  return {
    items,
    allItems,
    metrics: buildMetrics(allItems),
    options: buildOptions(allItems),
    page: {
      page: normalized.page,
      pageSize: normalized.pageSize,
      total,
      hasNext: start + normalized.pageSize < total,
    },
    dataState,
    source: context.source,
    sourceRunId: context.sourceRunId,
    generatedAt: context.generatedAt ?? mapped.generatedAt,
    notices: mapped.notices,
  }
}

export function buildProjectDetailResult(payload: unknown, slug: string, context: Omit<ProjectBuildContext, "source"> & { source: Exclude<ProjectSourceKind, "none"> }): ProjectDetailResult | null {
  const mapped = mapProjectPayload(payload)
  const project = mapped.items.find((item) => item.slug === slug || item.id === slug)
  if (!project) {
    return null
  }
  return {
    project,
    dataState: resolveDataState(Boolean(payload), mapped.items.length, mapped.notices),
    source: context.source,
    sourceRunId: context.sourceRunId,
    generatedAt: context.generatedAt ?? mapped.generatedAt,
    notices: mapped.notices,
  }
}

export function mapProjectPayload(payload: unknown): ProjectMappingResult {
  const root = unwrapPayload(payload)
  const rootRecord = recordValue(root)
  const generatedAt = firstStringFrom(rootRecord, ["generated_at", "generatedAt", "created_at", "createdAt"])
  const candidates = projectCandidates(root)
  const detailPages = detailPageCandidates(root)
  const items: ProjectItem[] = []
  const notices: string[] = []
  const seen = new Map<string, ProjectItem>()

  for (const candidate of candidates) {
    const item = mapProjectCandidate(candidate, detailPages)
    if (!item) {
      notices.push("已跳过缺少合法 GitHub 仓库地址的 project_radar 记录。")
      continue
    }
    const existing = seen.get(item.repoUrl)
    if (existing) {
      seen.set(item.repoUrl, mergeProjects(existing, item))
      continue
    }
    seen.set(item.repoUrl, item)
  }

  for (const item of seen.values()) {
    items.push(item)
  }

  if (candidates.length > 0 && items.length === 0) {
    notices.push("project_radar artifact 存在，但没有可公开展示的 GitHub 项目记录。")
  }

  return {
    items,
    generatedAt,
    notices: uniqueStrings(notices),
  }
}

export function filterProjects(items: ProjectItem[], params: ProjectListParams): ProjectItem[] {
  const q = params.q?.trim().toLowerCase()
  const category = normalizeCategory(params.category)
  const source = normalizeSource(params.source)
  const language = normalizeLanguage(params.language)

  return items.filter((item) => {
    if (q && !searchText(item).includes(q)) return false
    if (category && !item.categoryRefs.some((ref) => ref.category === category)) return false
    if (source && !projectSources(item).includes(source)) return false
    if (language && normalizeLanguage(item.language) !== language) return false
    return true
  })
}

export function sortProjects(items: ProjectItem[], sort: ProjectSort = "trending"): ProjectItem[] {
  return [...items].sort((left, right) => compareProjects(left, right, sort))
}

export function normalizeCategory(value: unknown): ProjectCategory | undefined {
  const text = stringValue(value)?.toLowerCase()
  return PROJECT_CATEGORIES.includes(text as ProjectCategory) ? (text as ProjectCategory) : undefined
}

export function normalizeSource(value: unknown): ProjectSource | undefined {
  const text = stringValue(value)?.toLowerCase()
  return PROJECT_SOURCES.includes(text as ProjectSource) ? (text as ProjectSource) : undefined
}

export function normalizeLanguage(value: unknown): ProjectLanguage | undefined {
  const text = stringValue(value)?.trim().toLowerCase()
  if (!text) return undefined
  if (text === "ts" || text === "tsx" || text === "javascript") return "typescript"
  if (text === "py") return "python"
  if (text === "rs") return "rust"
  if (PROJECT_LANGUAGES.includes(text as ProjectLanguage)) return text as ProjectLanguage
  return "other"
}

export function normalizeGitHubRepoUrl(value: unknown): GitHubRepo | null {
  const text = stringValue(value)
  if (!text) return null
  const withProtocol = text.startsWith("github.com/") ? `https://${text}` : text

  try {
    const url = new URL(withProtocol)
    if (url.protocol !== "https:" || url.hostname.toLowerCase() !== GITHUB_REPO_HOST) {
      return null
    }
    const [owner, repoPart] = url.pathname.split("/").filter(Boolean)
    if (!owner || !repoPart) return null
    const repo = repoPart.replace(/\.git$/i, "")
    if (!repo || owner === "topics" || owner === "orgs") return null
    return {
      owner,
      repo,
      fullName: `${owner}/${repo}`,
      url: `https://${GITHUB_REPO_HOST}/${owner}/${repo}`,
    }
  } catch {
    return null
  }
}

function mapProjectCandidate(raw: Record<string, unknown>, detailPages: Array<Record<string, unknown>>): ProjectItem | null {
  const repo = findRepo(raw)
  if (!repo) return null

  const detail = findDetailPage(raw, detailPages)
  const metadata = recordValue(raw.metadata)
  const rankingFeatures = recordValue(raw.ranking_features) ?? recordValue(raw.rankingFeatures)
  const score = recordValue(raw.score)
  const quality = recordValue(raw.quality)
  const sourceRefs = mapEvidenceRefs([
    ...arrayValue(raw.sourceRefs),
    ...arrayValue(raw.source_refs),
    ...arrayValue(raw.evidence_refs),
    ...arrayValue(recordValue(raw.provenance)?.source_refs),
    ...arrayValue(recordValue(raw.provenance)?.evidence_refs),
  ])
  const categories = categoryRefs(raw)
  const tags = uniqueStrings([
    ...stringArray(raw.tags),
    ...badgeLabels(raw.badges),
    ...categories.map((category) => category.label),
    ...objectRefLabels(raw.related_refs),
    ...objectRefLabels(raw.relation_refs),
  ]).filter((tag) => !["project_radar", "paper_radar", "ai_news", "community_pulse"].includes(tag.toLowerCase()))

  const firstSeenAt = firstStringFrom(raw, ["firstSeenAt", "first_seen_at", "published_at", "publishedAt", "generated_at", "generatedAt"])
  const project: ProjectItem = {
    id: firstStringFrom(raw, ["id", "project_id", "projectId", "card_id", "cardId", "repo_id"]) ?? repo.url,
    slug: slugify(`${repo.owner}-${repo.repo}`),
    name: projectName(raw, repo),
    description: descriptionText(raw, detail) ?? repo.fullName,
    repoUrl: repo.url,
    homepageUrl: normalizeHttpsUrl(firstStringFrom(raw, ["homepageUrl", "homepage_url", "homepage", "website"])),
    owner: firstStringFrom(raw, ["owner", "repo_owner", "repoOwner"]) ?? repo.owner,
    language: firstStringFrom(raw, ["language", "primary_language", "primaryLanguage"]),
    license: licenseText(raw),
    stars: firstNumberFrom(raw, ["stars", "stargazers_count", "stargazerCount", "githubStars"]) ?? metricNumber(raw.metrics, "stars"),
    forks: firstNumberFrom(raw, ["forks", "forks_count", "forkCount"]) ?? metricNumber(raw.metrics, "forks"),
    watchers: firstNumberFrom(raw, ["watchers", "watchers_count", "subscribers_count"]) ?? metricNumber(raw.metrics, "watchers"),
    starGrowth24h: firstNumberFrom(raw, ["starGrowth24h", "star_growth_24h", "stars_24h", "growth24h"]),
    starGrowth7d: firstNumberFrom(raw, ["starGrowth7d", "star_growth_7d", "stars_7d", "growth7d"]),
    projectMomentum:
      firstNumberFrom(raw, ["projectMomentum", "project_momentum", "momentum", "trend_score"]) ??
      numberValue(rankingFeatures?.activity) ??
      numberValue(score?.value),
    qualityScore:
      firstNumberFrom(raw, ["qualityScore", "quality_score"]) ??
      numberValue(quality?.score) ??
      numberValue(rankingFeatures?.weighted_score) ??
      numberValue(score?.value),
    categoryRefs: categories,
    tags,
    lastPushedAt: firstStringFrom(raw, ["lastPushedAt", "last_pushed_at", "pushed_at", "updated_at", "updatedAt"]),
    firstSeenAt,
    sourceRefs,
    relatedPapers: relatedPaperRefs(raw),
    relatedNews: relatedNewsRefs(raw, sourceRefs),
    relatedCommunityTopics: relatedCommunityRefs(raw),
    problemSolved: firstStringFrom(raw, ["problemSolved", "problem_solved", "problem", "use_case"]) ?? sectionContent(detail, "problem"),
    whyItMatters:
      firstStringFrom(raw, ["whyItMatters", "why_it_matters", "impact", "ranking_reason"]) ??
      firstStringFrom(metadata, ["why_it_matters"]) ??
      sectionContent(detail, "why"),
    sources: projectSourcesFromRefs(repo, raw, sourceRefs),
  }

  return stripUndefined(project)
}

function projectCandidates(payload: unknown): Array<Record<string, unknown>> {
  const root = unwrapPayload(payload)
  const arrays: unknown[] = []
  if (Array.isArray(root)) arrays.push(root)
  const record = recordValue(root)
  if (record) {
    for (const key of ["projects", "items", "radar_items", "radarItems", "cards"]) {
      arrays.push(record[key])
    }
    const boardOutput = recordValue(record.board_output) ?? recordValue(record.boardOutput)
    if (boardOutput) {
      for (const key of ["projects", "items", "radar_items", "radarItems", "cards"]) {
        arrays.push(boardOutput[key])
      }
    }
    const content = recordValue(record.content)
    if (content && content !== record) {
      arrays.push(...projectCandidates(content))
    }
  }
  return arrays.flatMap((value) => arrayValue(value).map(recordValue).filter(isRecord))
}

function detailPageCandidates(payload: unknown): Array<Record<string, unknown>> {
  const root = unwrapPayload(payload)
  const record = recordValue(root)
  if (!record) return []
  const boardOutput = recordValue(record.board_output) ?? recordValue(record.boardOutput)
  return [
    ...arrayValue(record.detail_pages),
    ...arrayValue(record.detailPages),
    ...arrayValue(boardOutput?.detail_pages),
    ...arrayValue(boardOutput?.detailPages),
  ].map(recordValue).filter(isRecord)
}

function findRepo(raw: Record<string, unknown>): GitHubRepo | null {
  for (const value of repoUrlCandidates(raw)) {
    const repo = normalizeGitHubRepoUrl(value)
    if (repo) return repo
  }
  for (const fullName of repoFullNameCandidates(raw)) {
    const repo = repoFromFullName(fullName)
    if (repo) return repo
  }
  const owner = firstStringFrom(raw, ["owner", "repo_owner", "repoOwner"])
  const repoName = firstStringFrom(raw, ["repo", "repo_name", "repoName"])
  if (owner && repoName) {
    return repoFromFullName(`${owner}/${repoName}`)
  }
  return null
}

function repoUrlCandidates(value: unknown, depth = 0): unknown[] {
  if (depth > 3) return []
  const record = recordValue(value)
  if (!record) return []
  const result: unknown[] = []
  for (const [key, item] of Object.entries(record)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) continue
    if (["repoUrl", "repo_url", "html_url", "github_url", "githubUrl", "source_url", "sourceUrl", "url"].includes(key)) {
      result.push(item)
    }
    if (["repo", "repository", "github", "metadata", "provenance"].includes(key)) {
      result.push(...repoUrlCandidates(item, depth + 1))
    }
  }
  return result
}

function repoFullNameCandidates(value: unknown, depth = 0): string[] {
  if (depth > 3) return []
  const record = recordValue(value)
  if (!record) return []
  const result: string[] = []
  for (const [key, item] of Object.entries(record)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) continue
    if (["repo_full_name", "repoFullName", "full_name", "fullName"].includes(key)) {
      const text = stringValue(item)
      if (text) result.push(text)
    }
    if (["repo", "repository", "github", "metadata"].includes(key)) {
      result.push(...repoFullNameCandidates(item, depth + 1))
    }
  }
  return result
}

function repoFromFullName(value: unknown): GitHubRepo | null {
  const text = stringValue(value)
  if (!text) return null
  const [owner, repo] = text.split("/").filter(Boolean)
  if (!owner || !repo) return null
  return normalizeGitHubRepoUrl(`https://github.com/${owner}/${repo.replace(/\.git$/i, "")}`)
}

function findDetailPage(raw: Record<string, unknown>, pages: Array<Record<string, unknown>>): Record<string, unknown> | undefined {
  const objectRef = recordValue(raw.primary_object_ref) ?? recordValue(raw.primaryObjectRef)
  const objectId = stringValue(objectRef?.object_id) ?? stringValue(objectRef?.objectId)
  const signalId = stringValue(recordValue(raw.metadata)?.signal_id) ?? stringValue(recordValue(raw.metadata)?.signalId)
  const title = stringValue(raw.title)?.toLowerCase()

  return pages.find((page) => {
    const pageRef = recordValue(page.primary_object_ref) ?? recordValue(page.primaryObjectRef)
    return (
      (objectId && (stringValue(pageRef?.object_id) === objectId || stringValue(pageRef?.objectId) === objectId)) ||
      (signalId && stringValue(recordValue(page.metadata)?.signal_id) === signalId) ||
      (title && stringValue(page.title)?.toLowerCase() === title)
    )
  })
}

function projectName(raw: Record<string, unknown>, repo: GitHubRepo): string {
  const value = firstStringFrom(raw, ["name", "project_name", "projectName", "title"])
  if (!value || value.toLowerCase() === repo.owner.toLowerCase()) {
    return repo.repo
  }
  return value
}

function descriptionText(raw: Record<string, unknown>, detail?: Record<string, unknown>): string | undefined {
  return (
    firstStringFrom(raw, ["description", "summary", "detailed_summary", "subtitle"]) ??
    firstStringFrom(detail, ["summary"]) ??
    sectionContent(detail, "summary")
  )
}

function licenseText(raw: Record<string, unknown>): string | undefined {
  const direct = firstStringFrom(raw, ["license"])
  if (direct) return direct
  const license = recordValue(raw.license)
  return firstStringFrom(license, ["name", "spdx_id", "spdxId", "key"])
}

function categoryRefs(raw: Record<string, unknown>): ProjectCategoryRef[] {
  const refs = arrayValue(raw.categoryRefs).concat(arrayValue(raw.category_refs))
  const categories: ProjectCategoryRef[] = []

  for (const ref of refs.map(recordValue).filter(isRecord)) {
    const category = normalizeCategory(ref.category ?? ref.value ?? ref.id)
    if (!category) continue
    const confidence = numberValue(ref.confidence)
    categories.push(
      stripUndefined({
        category,
        label: stringValue(ref.label) ?? categoryLabel(category),
        confidence,
      })
    )
  }

  for (const value of [raw.category, raw.type, ...stringArray(raw.categories), ...stringArray(raw.tags), ...badgeLabels(raw.badges)]) {
    const inferred = inferCategory(stringValue(value))
    if (inferred && !categories.some((ref) => ref.category === inferred)) {
      categories.push({ category: inferred, label: categoryLabel(inferred) })
    }
  }
  return categories
}

function inferCategory(value: string | undefined): ProjectCategory | undefined {
  const text = value?.toLowerCase()
  if (!text) return undefined
  if (text.includes("agent") || text.includes("coding")) return "agent"
  if (text.includes("rag") || text.includes("retrieval")) return "rag"
  if (text.includes("infer") || text.includes("serving") || text.includes("runtime")) return "inference"
  if (text.includes("eval") || text.includes("benchmark")) return "evaluation"
  if (text.includes("multi") || text.includes("vision") || text.includes("audio")) return "multimodal"
  if (text.includes("data") || text.includes("dataset")) return "data"
  if (text.includes("dev") || text.includes("tool") || text.includes("framework")) return "devtool"
  return normalizeCategory(text)
}

function mapEvidenceRefs(values: unknown[]): EvidenceRef[] {
  return values
    .map(recordValue)
    .filter(isRecord)
    .map((ref) =>
      stripUndefined({
        id: firstStringFrom(ref, ["id", "evidence_id", "external_id", "source_id"]),
        title: firstStringFrom(ref, ["title", "label"]),
        sourceName: firstStringFrom(ref, ["sourceName", "source_name"]),
        sourceType: firstStringFrom(ref, ["sourceType", "source_type"]),
        sourceUrl: firstStringFrom(ref, ["sourceUrl", "source_url"]),
        url: firstStringFrom(ref, ["url"]),
        collectedAt: firstStringFrom(ref, ["collectedAt", "collected_at", "capturedAt", "captured_at"]),
        publishedAt: firstStringFrom(ref, ["publishedAt", "published_at"]),
        reliability: firstStringFrom(ref, ["reliability"]),
        summary: firstStringFrom(ref, ["summary"]),
      })
    )
}

function relatedPaperRefs(raw: Record<string, unknown>): RelatedPaperRef[] {
  return mapRelatedRefs([...arrayValue(raw.relatedPapers), ...arrayValue(raw.related_papers), ...objectRefsByType(raw.related_refs, "paper")])
}

function relatedNewsRefs(raw: Record<string, unknown>, sourceRefs: EvidenceRef[]): RelatedNewsRef[] {
  const explicit = mapRelatedRefs([...arrayValue(raw.relatedNews), ...arrayValue(raw.related_news), ...objectRefsByType(raw.related_refs, "news")])
  const evidenceNews = sourceRefs
    .filter((ref) => ref.url || ref.sourceUrl)
    .map((ref) =>
      stripUndefined({
        id: ref.id,
        title: ref.title ?? ref.sourceName ?? ref.url ?? ref.sourceUrl ?? "Evidence",
        url: ref.url ?? ref.sourceUrl,
        sourceName: ref.sourceName,
        publishedAt: ref.publishedAt,
      })
    )
  return uniqueBy([...explicit, ...evidenceNews], (ref) => ref.url ?? ref.id ?? ref.title)
}

function relatedCommunityRefs(raw: Record<string, unknown>): RelatedCommunityRef[] {
  return mapRelatedRefs([
    ...arrayValue(raw.relatedCommunityTopics),
    ...arrayValue(raw.related_community_topics),
    ...arrayValue(raw.related_discussions),
    ...objectRefsByType(raw.related_refs, "community"),
    ...objectRefsByType(raw.related_refs, "discussion"),
  ])
}

type RelatedRef = {
  id?: string
  title: string
  url?: string
  summary?: string
  sourceName?: string
  publishedAt?: string
}

function mapRelatedRefs(values: unknown[]): RelatedRef[] {
  return values
    .map(recordValue)
    .filter(isRecord)
    .map((ref) =>
      stripUndefined({
        id: firstStringFrom(ref, ["id", "object_id", "objectId"]),
        title: firstStringFrom(ref, ["title", "label", "name"]) ?? "Related item",
        url: firstStringFrom(ref, ["url", "source_url", "sourceUrl"]),
        summary: firstStringFrom(ref, ["summary"]),
        sourceName: firstStringFrom(ref, ["sourceName", "source_name"]),
        publishedAt: firstStringFrom(ref, ["publishedAt", "published_at"]),
      })
    )
}

function objectRefsByType(value: unknown, type: string): unknown[] {
  return arrayValue(value).filter((item) => {
    const ref = recordValue(item)
    const objectType = stringValue(ref?.object_type ?? ref?.objectType)?.toLowerCase()
    return Boolean(objectType?.includes(type))
  })
}

function projectSourcesFromRefs(repo: GitHubRepo, raw: Record<string, unknown>, refs: EvidenceRef[]): ProjectSource[] {
  const sources = new Set<ProjectSource>(["github"])
  const text = [
    repo.url,
    firstStringFrom(raw, ["source", "source_type", "sourceType"]),
    ...refs.flatMap((ref) => [ref.sourceType, ref.url, ref.sourceUrl, ref.sourceName]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()

  if (text.includes("huggingface") || text.includes("hugging face")) sources.add("huggingface")
  if (text.includes("arxiv") || text.includes("paper") || text.includes("openreview")) sources.add("paper")
  if (text.includes("manual")) sources.add("manual")
  return [...sources]
}

function projectSources(item: ProjectItem): ProjectSource[] {
  const sources = new Set<ProjectSource>(item.sources?.length ? item.sources : ["github"])
  for (const ref of item.sourceRefs ?? []) {
    const text = `${ref.sourceType ?? ""} ${ref.sourceName ?? ""} ${ref.url ?? ""} ${ref.sourceUrl ?? ""}`.toLowerCase()
    if (text.includes("huggingface")) sources.add("huggingface")
    if (text.includes("arxiv") || text.includes("paper") || text.includes("openreview")) sources.add("paper")
    if (text.includes("manual")) sources.add("manual")
  }
  return [...sources]
}

function searchText(item: ProjectItem): string {
  return [
    item.name,
    item.description,
    item.owner,
    item.language,
    item.license,
    item.repoUrl,
    item.problemSolved,
    item.whyItMatters,
    ...item.tags,
    ...item.categoryRefs.map((ref) => ref.label),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
}

function compareProjects(left: ProjectItem, right: ProjectItem, sort: ProjectSort): number {
  if (sort === "newest") return compareDate(right.firstSeenAt ?? right.lastPushedAt, left.firstSeenAt ?? left.lastPushedAt)
  if (sort === "stars") return compareNumber(right.stars, left.stars)
  if (sort === "growth") return compareNumber(right.starGrowth7d ?? right.starGrowth24h, left.starGrowth7d ?? left.starGrowth24h)
  if (sort === "quality") return compareNumber(right.qualityScore, left.qualityScore)
  return (
    compareNumber(right.projectMomentum, left.projectMomentum) ||
    compareNumber(right.starGrowth7d ?? right.starGrowth24h, left.starGrowth7d ?? left.starGrowth24h) ||
    compareNumber(right.qualityScore, left.qualityScore) ||
    compareNumber(right.stars, left.stars)
  )
}

function buildMetrics(items: ProjectItem[]): ProjectMetric[] {
  const withStars = items.filter((item) => item.stars !== undefined)
  const growth = items.reduce((sum, item) => sum + (item.starGrowth7d ?? item.starGrowth24h ?? 0), 0)
  const averageQuality = average(items.map((item) => item.qualityScore).filter(isNumber))
  return [
    { label: "项目", value: items.length },
    { label: "有星标数据", value: withStars.length },
    { label: "7日增长", value: growth },
    { label: "质量均值", value: averageQuality === undefined ? "-" : formatScore(averageQuality) },
  ]
}

function buildOptions(items: ProjectItem[]): ProjectListOptions {
  return {
    categories: PROJECT_CATEGORIES.map((category) => ({
      value: category,
      label: categoryLabel(category),
      count: items.filter((item) => item.categoryRefs.some((ref) => ref.category === category)).length,
    })).filter((option) => option.count > 0),
    sources: PROJECT_SOURCES.map((source) => ({
      value: source,
      label: sourceLabel(source),
      count: items.filter((item) => projectSources(item).includes(source)).length,
    })).filter((option) => option.count > 0),
    languages: PROJECT_LANGUAGES.map((language) => ({
      value: language,
      label: languageLabel(language),
      count: items.filter((item) => normalizeLanguage(item.language) === language).length,
    })).filter((option) => option.count > 0),
  }
}

function emptyProjectList(
  params: Required<Pick<ProjectListParams, "sort" | "page" | "pageSize">> & ProjectListParams,
  context: ProjectBuildContext,
  dataState: ProjectDataState,
  notices: string[]
): ProjectListResult {
  return {
    items: [],
    allItems: [],
    metrics: buildMetrics([]),
    options: { categories: [], sources: [], languages: [] },
    page: { page: params.page, pageSize: params.pageSize, total: 0, hasNext: false },
    dataState,
    source: context.source,
    sourceRunId: context.sourceRunId,
    generatedAt: context.generatedAt,
    notices,
  }
}

function resolveDataState(hasPayload: boolean, itemCount: number, notices: string[]): ProjectDataState {
  if (!hasPayload) return "empty"
  if (itemCount === 0) return "partial"
  return notices.length ? "partial" : "ready"
}

function categoryLabel(category: ProjectCategory): string {
  const labels: Record<ProjectCategory, string> = {
    agent: "Agent",
    rag: "RAG",
    inference: "推理",
    evaluation: "评测",
    multimodal: "多模态",
    data: "数据",
    devtool: "开发工具",
  }
  return labels[category]
}

function sourceLabel(source: ProjectSource): string {
  const labels: Record<ProjectSource, string> = {
    github: "GitHub",
    huggingface: "Hugging Face",
    paper: "论文",
    manual: "人工",
  }
  return labels[source]
}

function languageLabel(language: ProjectLanguage): string {
  const labels: Record<ProjectLanguage, string> = {
    python: "Python",
    typescript: "TypeScript",
    rust: "Rust",
    go: "Go",
    other: "Other",
  }
  return labels[language]
}

function sectionContent(detail: Record<string, unknown> | undefined, hint: string): string | undefined {
  const sections = arrayValue(detail?.sections).map(recordValue).filter(isRecord)
  const match = sections.find((section) => {
    const title = `${stringValue(section.title) ?? ""} ${stringValue(section.section_type) ?? ""}`.toLowerCase()
    return title.includes(hint)
  })
  return firstStringFrom(match, ["content", "summary"])
}

function metricNumber(value: unknown, label: string): number | undefined {
  const metrics = arrayValue(value).map(recordValue).filter(isRecord)
  const metric = metrics.find((item) => stringValue(item.label)?.toLowerCase().includes(label.toLowerCase()))
  return numberValue(metric?.value)
}

function badgeLabels(value: unknown): string[] {
  return arrayValue(value)
    .map(recordValue)
    .filter(isRecord)
    .map((badge) => stringValue(badge.label))
    .filter(isString)
}

function objectRefLabels(value: unknown): string[] {
  return arrayValue(value)
    .map(recordValue)
    .filter(isRecord)
    .map((ref) => stringValue(ref.label))
    .filter(isString)
}

function stringArray(value: unknown): string[] {
  return arrayValue(value).map(stringValue).filter(isString)
}

function firstStringFrom(record: Record<string, unknown> | undefined, keys: string[]): string | undefined {
  if (!record) return undefined
  for (const key of keys) {
    const value = stringValue(record[key])
    if (value) return value
  }
  return undefined
}

function firstNumberFrom(record: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = numberValue(record[key])
    if (value !== undefined) return value
  }
  return undefined
}

function normalizeHttpsUrl(value: unknown): string | undefined {
  const text = stringValue(value)
  if (!text) return undefined
  try {
    const url = new URL(text)
    if (url.protocol !== "https:") return undefined
    return url.toString()
  } catch {
    return undefined
  }
}

function unwrapPayload(payload: unknown): unknown {
  const record = recordValue(payload)
  if (!record) return payload
  const content = recordValue(record.content)
  return content ?? payload
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function recordValue(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined
}

function isRecord(value: Record<string, unknown> | undefined): value is Record<string, unknown> {
  return Boolean(value)
}

function stringValue(value: unknown): string | undefined {
  if (typeof value !== "string" && typeof value !== "number") return undefined
  const text = String(value).trim()
  return text ? text : undefined
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const number = Number(value)
    return Number.isFinite(number) ? number : undefined
  }
  return undefined
}

function isString(value: string | undefined): value is string {
  return Boolean(value)
}

function isNumber(value: number | undefined): value is number {
  return value !== undefined && Number.isFinite(value)
}

function compareNumber(left: number | undefined, right: number | undefined): number {
  return (left ?? Number.NEGATIVE_INFINITY) - (right ?? Number.NEGATIVE_INFINITY)
}

function compareDate(left: string | undefined, right: string | undefined): number {
  const leftTime = left ? Date.parse(left) : Number.NEGATIVE_INFINITY
  const rightTime = right ? Date.parse(right) : Number.NEGATIVE_INFINITY
  return (Number.isFinite(leftTime) ? leftTime : Number.NEGATIVE_INFINITY) - (Number.isFinite(rightTime) ? rightTime : Number.NEGATIVE_INFINITY)
}

function average(values: number[]): number | undefined {
  if (!values.length) return undefined
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function formatScore(value: number): string {
  return value <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(1)
}

function clampInteger(value: unknown, min: number, max: number, fallback: number): number {
  const number = typeof value === "number" ? value : Number(value)
  if (!Number.isInteger(number)) return fallback
  return Math.min(max, Math.max(min, number))
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  return [...new Set(values.filter(isString).map((value) => value.trim()).filter(Boolean))]
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

function mergeProjects(left: ProjectItem, right: ProjectItem): ProjectItem {
  return stripUndefined({
    ...left,
    description: left.description.length >= right.description.length ? left.description : right.description,
    stars: maxDefined(left.stars, right.stars),
    forks: maxDefined(left.forks, right.forks),
    watchers: maxDefined(left.watchers, right.watchers),
    starGrowth24h: maxDefined(left.starGrowth24h, right.starGrowth24h),
    starGrowth7d: maxDefined(left.starGrowth7d, right.starGrowth7d),
    projectMomentum: maxDefined(left.projectMomentum, right.projectMomentum),
    qualityScore: maxDefined(left.qualityScore, right.qualityScore),
    categoryRefs: uniqueBy([...left.categoryRefs, ...right.categoryRefs], (ref) => ref.category),
    tags: uniqueStrings([...left.tags, ...right.tags]),
    sourceRefs: uniqueBy([...(left.sourceRefs ?? []), ...(right.sourceRefs ?? [])], (ref) => ref.url ?? ref.sourceUrl ?? ref.id ?? ""),
    relatedPapers: uniqueBy([...(left.relatedPapers ?? []), ...(right.relatedPapers ?? [])], (ref) => ref.url ?? ref.id ?? ref.title),
    relatedNews: uniqueBy([...(left.relatedNews ?? []), ...(right.relatedNews ?? [])], (ref) => ref.url ?? ref.id ?? ref.title),
    relatedCommunityTopics: uniqueBy([...(left.relatedCommunityTopics ?? []), ...(right.relatedCommunityTopics ?? [])], (ref) => ref.url ?? ref.id ?? ref.title),
    sources: uniqueBy([...(left.sources ?? []), ...(right.sources ?? [])], (source) => source),
  })
}

function maxDefined(left: number | undefined, right: number | undefined): number | undefined {
  if (left === undefined) return right
  if (right === undefined) return left
  return Math.max(left, right)
}

function stripUndefined<T extends Record<string, unknown>>(value: T): T {
  const cleaned: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined) {
      cleaned[key] = item
    }
  }
  return cleaned as T
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
}
