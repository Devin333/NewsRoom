import { safeApiGet } from "@/lib/api/server"
import { getCommunityList } from "@/lib/community/server-data"
import { getNewsListResult } from "@/lib/news/server-data"
import { getPublishedPaperData } from "@/lib/papers/real-data"
import type { Paper } from "@/lib/papers/types"
import { getProjectList } from "@/lib/projects/data-source"
import type { CommunityTopic } from "@/types/community"
import type {
  EvidenceEdge,
  EvidenceGraphNodeDetailResponse,
  EvidenceGraphPeriod,
  EvidenceGraphQuery,
  EvidenceGraphRelatedReport,
  EvidenceGraphResponse,
  EvidenceGraphSourceState,
  EvidenceGraphTimelineItem,
  EvidenceNode,
  EvidenceNodeType,
  TopicEvidenceSummary,
  TopicEvidenceTrajectory,
} from "@/types/evidence-graph"
import type { NewsItem } from "@/types/news"
import type { ProjectItem } from "@/types/projects"

type BoardKey = "paper" | "project" | "news" | "community" | "report"

type ReportRecord = {
  report_id?: string | null
  id?: string | null
  title?: string | null
  status?: string | null
  finished_at?: string | null
  published_at?: string | null
  created_at?: string | null
  workflow_id?: string | null
  profile?: string | null
  summary?: string | null
}

type ReportListResponse = {
  reports?: ReportRecord[]
}

type LoadedSources = {
  papers: Paper[]
  projects: ProjectItem[]
  news: NewsItem[]
  community: CommunityTopic[]
  reports: ReportRecord[]
  sourceStates: EvidenceGraphSourceState[]
}

export type EvidenceGraphLoadedSources = LoadedSources

type GraphCandidate = {
  node: EvidenceNode
  board: BoardKey
  href?: string
  date?: string
  searchText: string
  relatedUrls: string[]
  relatedTitles: string[]
  sourceReliability: number
  verifiedSource: boolean
}

const DEFAULT_LIMIT = 48
const MAX_LIMIT = 100
const EDGE_LIMIT = 180
const EVIDENCE_NODE_TYPES: EvidenceNodeType[] = ["paper", "project", "news", "community_signal", "report"]
const PERIOD_DAYS: Record<Exclude<EvidenceGraphPeriod, "all">, number> = {
  daily: 1,
  weekly: 7,
  monthly: 30,
}

export async function getEvidenceGraphData(query: EvidenceGraphQuery = {}): Promise<EvidenceGraphResponse> {
  const sources = await loadEvidenceGraphSources()
  return buildEvidenceGraphResponse(sources, normalizeEvidenceGraphQuery(query))
}

export async function getEvidenceGraphNodeDetail(
  nodeId: string,
  query: EvidenceGraphQuery = {}
): Promise<EvidenceGraphNodeDetailResponse | null> {
  const normalized = normalizeEvidenceGraphQuery({ ...query, depth: 3, limit: MAX_LIMIT })
  let graph = await getEvidenceGraphData(normalized)
  let node = graph.nodes.find((item) => item.id === nodeId)

  if (!node && (normalized.topic || normalized.entity || normalized.nodeTypes?.length)) {
    graph = await getEvidenceGraphData({ depth: 3, limit: MAX_LIMIT })
    node = graph.nodes.find((item) => item.id === nodeId)
  }

  if (!node) {
    return null
  }

  const incomingEdges = graph.edges.filter((edge) => edge.targetNodeId === nodeId)
  const outgoingEdges = graph.edges.filter((edge) => edge.sourceNodeId === nodeId)
  const relatedNodeIds = new Set<string>()
  for (const edge of [...incomingEdges, ...outgoingEdges]) {
    relatedNodeIds.add(edge.sourceNodeId)
    relatedNodeIds.add(edge.targetNodeId)
  }
  relatedNodeIds.delete(nodeId)

  return {
    node,
    incomingEdges,
    outgoingEdges,
    relatedNodes: graph.nodes.filter((item) => relatedNodeIds.has(item.id)),
  }
}

export async function getEvidenceGraphTimeline(
  topicId: string,
  query: EvidenceGraphQuery = {}
): Promise<{ items: EvidenceGraphTimelineItem[] }> {
  const topic = topicFromId(topicId)
  const graph = await getEvidenceGraphData({ ...query, topic, limit: MAX_LIMIT })
  return { items: graph.timeline }
}

export function buildEvidenceGraphResponse(sources: LoadedSources, query: EvidenceGraphQuery = {}): EvidenceGraphResponse {
  const normalizedQuery = normalizeEvidenceGraphQuery(query)
  const generatedAt = new Date().toISOString()
  const allCandidates = [
    ...sources.papers.map(paperCandidate),
    ...sources.projects.map(projectCandidate),
    ...sources.news.map(newsCandidate),
    ...sources.community.map(communityCandidate),
    ...sources.reports.map(reportCandidate),
  ]

  const explicitTopic = cleanText(normalizedQuery.topic)
  const explicitEntity = cleanText(normalizedQuery.entity)
  const topicName = explicitTopic || explicitEntity || strongestTopic(allCandidates) || "Cross-board Evidence Graph"
  const periodFiltered = allCandidates.filter((candidate) => matchesPeriod(candidate, normalizedQuery.period ?? "all"))
  const typeFiltered = filterByNodeTypes(periodFiltered, normalizedQuery.nodeTypes)
  const topicFiltered = typeFiltered.filter((candidate) => matchesTopic(candidate, topicName, explicitEntity))
  const shouldUseBroadDefault = !explicitTopic && !explicitEntity && topicFiltered.length < Math.min(4, typeFiltered.length)
  const selectedCandidates = sortCandidates(shouldUseBroadDefault ? typeFiltered : topicFiltered).slice(0, normalizedQuery.limit ?? DEFAULT_LIMIT)

  const topicNode = topicEvidenceNode(topicName, selectedCandidates)
  const nodes = [topicNode, ...selectedCandidates.map((candidate) => candidate.node)]
  const sameTopicEdges = selectedCandidates.map((candidate) => topicEdge(topicNode.id, candidate, topicName))
  const supportEdges = selectedCandidates
    .filter((candidate) => (candidate.node.confidence ?? 0) >= 70)
    .slice(0, 12)
    .map((candidate) => supportEdge(candidate, topicNode.id))
  const relationEdges = (normalizedQuery.depth ?? 2) > 1 ? buildRelationEdges(selectedCandidates) : []
  const edges = dedupeEdges([...sameTopicEdges, ...supportEdges, ...relationEdges]).slice(0, EDGE_LIMIT)
  const relatedReports = buildRelatedReports(selectedCandidates, edges)
  const timeline = buildTimeline(topicNode.id, selectedCandidates, edges)
  const summary = buildSummary(topicNode, selectedCandidates, edges, timeline, generatedAt)
  const notices = sources.sourceStates.flatMap((state) => state.notices.map((notice) => `${state.board}: ${notice}`))

  topicNode.summary = summary.summary
  topicNode.score = summary.trendScore
  topicNode.confidence = summary.confidenceScore

  return {
    generatedAt,
    query: normalizedQuery,
    summary,
    nodes,
    edges,
    timeline,
    relatedReports,
    sourceStates: sources.sourceStates,
    notices,
  }
}

export function evidenceGraphQueryFromSearchParams(searchParams: URLSearchParams): EvidenceGraphQuery {
  return normalizeEvidenceGraphQuery({
    topic: searchParams.get("topic") ?? undefined,
    entity: searchParams.get("entity") ?? undefined,
    period: parsePeriod(searchParams.get("period")),
    nodeTypes: parseNodeTypes(searchParams.get("nodeTypes")),
    depth: numberParam(searchParams.get("depth")),
    limit: numberParam(searchParams.get("limit")),
  })
}

export function evidenceGraphQueryFromRecord(record?: Record<string, string | string[] | undefined>): EvidenceGraphQuery {
  return normalizeEvidenceGraphQuery({
    topic: stringParam(record?.topic),
    entity: stringParam(record?.entity),
    period: parsePeriod(stringParam(record?.period)),
    nodeTypes: parseNodeTypes(stringParam(record?.nodeTypes)),
    depth: numberParam(stringParam(record?.depth)),
    limit: numberParam(stringParam(record?.limit)),
  })
}

function normalizeEvidenceGraphQuery(query: EvidenceGraphQuery): EvidenceGraphQuery {
  return {
    topic: cleanText(query.topic),
    entity: cleanText(query.entity),
    period: query.period ?? "all",
    nodeTypes: query.nodeTypes?.filter((type, index, all) => EVIDENCE_NODE_TYPES.includes(type) && all.indexOf(type) === index),
    depth: clampInteger(query.depth, 1, 3, 2),
    limit: clampInteger(query.limit, 1, MAX_LIMIT, DEFAULT_LIMIT),
  }
}

async function loadEvidenceGraphSources(): Promise<LoadedSources> {
  const [papers, projects, news, community, reports] = await Promise.all([
    loadPapers(),
    loadProjects(),
    loadNews(),
    loadCommunity(),
    loadReports(),
  ])

  return {
    papers: papers.items,
    projects: projects.items,
    news: news.items,
    community: community.items,
    reports: reports.items,
    sourceStates: [papers.state, projects.state, news.state, community.state, reports.state],
  }
}

async function loadPapers() {
  try {
    const result = await getPublishedPaperData()
    return {
      items: result.papers,
      state: sourceState("papers", result.dataState === "ready" ? "ready" : result.dataState === "empty" ? "empty" : "degraded", result.source, result.papers.length, result.notices),
    }
  } catch (error) {
    return {
      items: [],
      state: sourceState("papers", "degraded", "unavailable", 0, [errorMessage(error)]),
    }
  }
}

async function loadProjects() {
  try {
    const result = await getProjectList({ sort: "trending", pageSize: MAX_LIMIT, limit: MAX_LIMIT })
    return {
      items: result.allItems,
      state: sourceState("projects", result.dataState === "ready" ? "ready" : result.dataState === "empty" ? "empty" : "degraded", result.source, result.allItems.length, result.notices),
    }
  } catch (error) {
    return {
      items: [],
      state: sourceState("projects", "degraded", "unavailable", 0, [errorMessage(error)]),
    }
  }
}

async function loadNews() {
  try {
    const result = await getNewsListResult({ sort: "heatScore", pageSize: MAX_LIMIT })
    return {
      items: result.allItems,
      state: sourceState("news", result.dataState === "ready" ? "ready" : result.allItems.length ? "degraded" : "empty", result.source, result.allItems.length, result.notices),
    }
  } catch (error) {
    return {
      items: [],
      state: sourceState("news", "degraded", "unavailable", 0, [errorMessage(error)]),
    }
  }
}

async function loadCommunity() {
  try {
    const result = await getCommunityList({ sort: "trending", pageSize: MAX_LIMIT })
    return {
      items: result.allTopics,
      state: sourceState("community", result.dataState === "ready" ? "ready" : result.dataState === "empty" ? "empty" : "degraded", result.source, result.allTopics.length, result.notices),
    }
  } catch (error) {
    return {
      items: [],
      state: sourceState("community", "degraded", "unavailable", 0, [errorMessage(error)]),
    }
  }
}

async function loadReports() {
  const result = await safeApiGet<ReportListResponse>("/api/v1/reports?limit=50")
  if (!result.ok) {
    return {
      items: [],
      state: sourceState("reports", "degraded", "backend", 0, [result.errorMessage]),
    }
  }
  const reports = result.data.reports ?? []
  return {
    items: reports,
    state: sourceState("reports", reports.length ? "ready" : "empty", "backend", reports.length, reports.length ? [] : ["No reports were returned by the backend."]),
  }
}

function paperCandidate(paper: Paper): GraphCandidate {
  const taskTags = paper.taskRefs.flatMap((task) => [task.name, task.nameZh, task.slug]).filter(isString)
  const methodTags = paper.methodRefs.flatMap((method) => [method.name, method.nameZh, method.slug]).filter(isString)
  const urls = uniqueStrings([
    paper.paperUrl,
    paper.arxivUrl,
    paper.pdfUrl,
    paper.repoUrl,
    paper.projectUrl,
    ...(paper.implementations?.map((implementation) => implementation.repoUrl) ?? []),
  ])
  const tags = cleanTags([...paper.tags, ...taskTags, ...methodTags])
  const score = scoreValue(paper.newsroomHeatScore, paper.githubMomentum, paper.citationCount)
  const confidence = confidenceFromEvidence(paper.evidenceRefs?.length ?? paper.sourceRefs?.length ?? 0, 86)
  const title = paper.titleZh || paper.title

  return candidate({
    board: "paper",
    node: {
      id: nodeId("paper", paper.id),
      type: "paper",
      title,
      summary: paper.abstractSnippetZh || paper.abstractSnippet,
      url: paper.paperUrl ?? paper.arxivUrl ?? paper.pdfUrl,
      source: paper.venue ?? "Paper Radar",
      createdAt: paper.publishedAt,
      updatedAt: paper.publishedAt,
      score,
      confidence,
      tags,
      metadata: {
        href: `/papers?paper=${encodeURIComponent(paper.id)}`,
        board: "papers",
        repoUrl: paper.repoUrl,
        citationCount: paper.citationCount,
      },
    },
    href: `/papers?paper=${encodeURIComponent(paper.id)}`,
    date: paper.publishedAt,
    relatedUrls: urls,
    relatedTitles: uniqueStrings([
      ...taskTags,
      ...methodTags,
      ...(paper.implementations?.flatMap((implementation) => [implementation.name, implementation.repoUrl]) ?? []),
    ]),
    sourceReliability: 90,
    verifiedSource: true,
  })
}

function projectCandidate(project: ProjectItem): GraphCandidate {
  const categoryTags = project.categoryRefs.map((category) => category.label)
  const tags = cleanTags([...project.tags, ...project.topics, ...categoryTags, ...project.categories])
  const relatedUrls = uniqueStrings([
    project.repoUrl,
    project.homepageUrl,
    ...(project.sourceRefs?.flatMap((ref) => [ref.url, ref.sourceUrl]) ?? []),
    ...(project.relatedPapers?.map((ref) => ref.url) ?? []),
    ...(project.relatedNews?.map((ref) => ref.url) ?? []),
    ...(project.relatedCommunityTopics?.map((ref) => ref.url) ?? []),
  ])
  const evidenceCount = project.relationCounts.papers + project.relationCounts.news + project.relationCounts.community + (project.sourceRefs?.length ?? 0)
  const score = scoreValue(project.scores.trendScore, project.projectMomentum, project.starGrowth7d, project.starGrowth24h, project.stars)
  const confidence = confidenceFromEvidence(evidenceCount, 76)

  return candidate({
    board: "project",
    node: {
      id: nodeId("project", project.slug),
      type: "project",
      title: project.name,
      summary: project.whyItMatters ?? project.description,
      url: project.repoUrl,
      source: "GitHub",
      createdAt: project.firstSeenAt ?? project.createdAt,
      updatedAt: project.updatedAt ?? project.pushedAt ?? project.lastPushedAt,
      score,
      confidence,
      tags,
      metadata: {
        href: `/projects/${project.slug}`,
        board: "projects",
        fullName: project.fullName,
        repoUrl: project.repoUrl,
        stars: project.stars,
        relationCounts: project.relationCounts,
      },
    },
    href: `/projects/${project.slug}`,
    date: project.updatedAt ?? project.pushedAt ?? project.lastPushedAt ?? project.firstSeenAt ?? project.createdAt,
    relatedUrls,
    relatedTitles: uniqueStrings([
      project.fullName,
      project.owner,
      ...categoryTags,
      ...(project.relatedPapers?.map((ref) => ref.title) ?? []),
      ...(project.relatedNews?.map((ref) => ref.title) ?? []),
      ...(project.relatedCommunityTopics?.map((ref) => ref.title) ?? []),
    ]),
    sourceReliability: 82,
    verifiedSource: true,
  })
}

function newsCandidate(item: NewsItem): GraphCandidate {
  const entityNames = item.entities?.map((entity) => entity.name) ?? []
  const relatedTitles = [
    ...(item.relatedPapers?.map((ref) => ref.title) ?? []),
    ...(item.relatedProjects?.map((ref) => ref.title) ?? []),
    ...(item.relatedCommunityTopics?.map((ref) => ref.title) ?? []),
    ...entityNames,
  ]
  const relatedUrls = uniqueStrings([
    item.url,
    item.sourceUrl,
    ...(item.evidenceRefs?.map((ref) => ref.url) ?? []),
    ...(item.relatedPapers?.map((ref) => ref.url) ?? []),
    ...(item.relatedProjects?.map((ref) => ref.url) ?? []),
    ...(item.relatedCommunityTopics?.map((ref) => ref.url) ?? []),
  ])
  const tags = cleanTags([item.category, item.topicName, item.topicId, ...item.tags, ...entityNames])
  const confidence = Math.max(
    credibilityScore(item.credibility),
    averageNumbers(item.evidenceRefs?.map((ref) => ref.confidenceScore).filter(isNumber) ?? []) ?? 0
  )

  return candidate({
    board: "news",
    node: {
      id: nodeId("news", item.id),
      type: "news",
      title: item.title,
      summary: item.whyItMatters ?? item.summary,
      url: item.url ?? item.sourceUrl,
      source: item.sourceName,
      createdAt: item.publishedAt ?? item.collectedAt,
      updatedAt: item.collectedAt ?? item.publishedAt,
      score: scoreValue(item.heatScore, item.qualityScore),
      confidence,
      tags,
      metadata: {
        href: `/news/${item.id}`,
        board: "news",
        sourceType: item.sourceType,
        status: item.status,
        evidenceIds: item.evidenceIds,
      },
    },
    href: `/news/${item.id}`,
    date: item.publishedAt ?? item.collectedAt,
    relatedUrls,
    relatedTitles,
    sourceReliability: sourceReliability(item.sourceType, item.sourceName),
    verifiedSource: isVerifiedSource(item.sourceType, item.sourceName),
  })
}

function communityCandidate(topic: CommunityTopic): GraphCandidate {
  const entityNames = topic.entities?.map((entity) => entity.name) ?? []
  const relatedTitles = [
    ...(topic.relatedPapers?.map((ref) => ref.title) ?? []),
    ...(topic.relatedProjects?.map((ref) => ref.name) ?? []),
    ...(topic.relatedNews?.map((ref) => ref.title) ?? []),
    ...entityNames,
  ]
  const relatedUrls = uniqueStrings([
    topic.sourceUrl,
    ...(topic.evidenceRefs?.map((ref) => ref.url) ?? []),
    ...(topic.relatedPapers?.map((ref) => ref.url) ?? []),
    ...(topic.relatedProjects?.map((ref) => ref.url) ?? []),
    ...(topic.relatedNews?.map((ref) => ref.url) ?? []),
  ])
  const confidence = confidenceFromEvidence(topic.evidenceRefs?.length ?? 0, topic.sentiment === "unknown" ? 55 : 68)

  return candidate({
    board: "community",
    node: {
      id: nodeId("community_signal", topic.slug),
      type: "community_signal",
      title: topic.title,
      summary: topic.summary,
      url: topic.sourceUrl,
      source: topic.sourceName ?? topic.sourceType,
      createdAt: topic.publishedAt,
      updatedAt: topic.lastActivityAt ?? topic.publishedAt,
      score: scoreValue(topic.heatScore, topic.adoptionScore, topic.controversyScore),
      confidence,
      tags: cleanTags([...topic.tags, ...entityNames, topic.sentiment]),
      metadata: {
        href: `/community/topics/${topic.slug}`,
        board: "community",
        sourceType: topic.sourceType,
        sentiment: topic.sentiment,
        commentCount: topic.commentCount,
      },
    },
    href: `/community/topics/${topic.slug}`,
    date: topic.lastActivityAt ?? topic.publishedAt,
    relatedUrls,
    relatedTitles,
    sourceReliability: sourceReliability(topic.sourceType, topic.sourceName),
    verifiedSource: topic.sourceType === "github_discussion" || topic.sourceType === "hackernews",
  })
}

function reportCandidate(report: ReportRecord): GraphCandidate {
  const id = report.report_id ?? report.id ?? stableHash(report.title ?? "report")
  const date = report.published_at ?? report.finished_at ?? report.created_at ?? undefined
  const title = cleanText(report.title) || id
  const status = cleanText(report.status)

  return candidate({
    board: "report",
    node: {
      id: nodeId("report", id),
      type: "report",
      title,
      summary: report.summary ?? undefined,
      source: "NewsRoom",
      createdAt: date,
      updatedAt: date,
      score: isPublishedStatus(status) ? 90 : 65,
      confidence: isPublishedStatus(status) ? 88 : 70,
      tags: cleanTags([report.workflow_id, report.profile, status]),
      metadata: {
        href: `/reports/${encodeURIComponent(id)}`,
        board: "reports",
        status,
        workflowId: report.workflow_id,
        profile: report.profile,
      },
    },
    href: `/reports/${encodeURIComponent(id)}`,
    date,
    relatedUrls: [],
    relatedTitles: [report.workflow_id, report.profile].filter(isString),
    sourceReliability: 84,
    verifiedSource: true,
  })
}

function candidate(input: Omit<GraphCandidate, "searchText">): GraphCandidate {
  const metadataText = Object.values(input.node.metadata ?? {})
    .filter((value) => typeof value === "string" || typeof value === "number")
    .join(" ")
  return {
    ...input,
    searchText: normalizeText(
      [
        input.node.title,
        input.node.summary,
        input.node.source,
        ...(input.node.tags ?? []),
        ...input.relatedTitles,
        ...input.relatedUrls,
        metadataText,
      ].join(" ")
    ),
    relatedUrls: input.relatedUrls.map(normalizeUrlish).filter(isString),
  }
}

function topicEvidenceNode(topicName: string, candidates: GraphCandidate[]): EvidenceNode {
  const tags = cleanTags(candidates.flatMap((candidate) => candidate.node.tags ?? [])).slice(0, 12)
  const dates = candidates.flatMap((candidate) => [candidate.node.createdAt, candidate.node.updatedAt]).filter(isString)
  return {
    id: nodeId("topic", topicName),
    type: "topic",
    title: topicName,
    summary: "",
    createdAt: minDate(dates),
    updatedAt: maxDate(dates),
    tags,
    metadata: {
      board: "topics",
      href: `/topics?view=evidence-graph&topic=${encodeURIComponent(topicName)}`,
    },
  }
}

function topicEdge(topicNodeId: string, candidate: GraphCandidate, topicName: string): EvidenceEdge {
  return edge({
    sourceNodeId: topicNodeId,
    targetNodeId: candidate.node.id,
    type: "same_topic",
    confidence: unitConfidence(candidate.node.confidence),
    evidenceText: `与主题「${topicName}」在标题、标签、实体或关联引用中匹配。`,
    createdAt: candidate.date,
    metadata: { board: candidate.board },
  })
}

function supportEdge(candidate: GraphCandidate, topicNodeId: string): EvidenceEdge {
  return edge({
    sourceNodeId: candidate.node.id,
    targetNodeId: topicNodeId,
    type: "supports",
    confidence: unitConfidence(candidate.node.confidence),
    evidenceText: `${boardLabel(candidate.board)} 为该主题提供可追溯证据。`,
    createdAt: candidate.date,
    metadata: { board: candidate.board },
  })
}

function buildRelationEdges(candidates: GraphCandidate[]): EvidenceEdge[] {
  const byBoard = new Map<BoardKey, GraphCandidate[]>()
  for (const candidate of candidates) {
    byBoard.set(candidate.board, [...(byBoard.get(candidate.board) ?? []), candidate])
  }

  const edges: EvidenceEdge[] = []
  for (const paper of byBoard.get("paper") ?? []) {
    for (const project of byBoard.get("project") ?? []) {
      const confidence = relationConfidence(paper, project)
      if (confidence >= 0.58) {
        edges.push(
          edge({
            sourceNodeId: project.node.id,
            targetNodeId: paper.node.id,
            type: "implements",
            confidence,
            evidenceText: "项目仓库、实现引用或标题实体与论文实现信号匹配。",
            createdAt: project.date ?? paper.date,
            metadata: { relation: "project_implements_paper" },
          })
        )
      }
    }
  }

  for (const news of byBoard.get("news") ?? []) {
    for (const target of candidates.filter((candidate) => candidate.board !== "news" && candidate.board !== "report")) {
      const confidence = relationConfidence(news, target)
      if (confidence >= 0.52) {
        edges.push(
          edge({
            sourceNodeId: news.node.id,
            targetNodeId: target.node.id,
            type: "mentions",
            confidence,
            evidenceText: "新闻条目的关联引用、实体或来源 URL 指向该证据节点。",
            createdAt: news.date,
            metadata: { relation: "news_mentions_evidence" },
          })
        )
      }
    }
  }

  for (const community of byBoard.get("community") ?? []) {
    for (const target of candidates.filter((candidate) => candidate.board !== "community" && candidate.board !== "report")) {
      const confidence = relationConfidence(community, target)
      if (confidence >= 0.5) {
        edges.push(
          edge({
            sourceNodeId: community.node.id,
            targetNodeId: target.node.id,
            type: "discusses",
            confidence,
            evidenceText: "社区讨论的关联对象、标签或实体与该证据节点匹配。",
            createdAt: community.date,
            metadata: { relation: "community_discusses_evidence" },
          })
        )
      }
    }
  }

  for (const report of byBoard.get("report") ?? []) {
    for (const target of candidates.filter((candidate) => candidate.board !== "report").slice(0, 12)) {
      const confidence = relationConfidence(report, target)
      if (confidence >= 0.48) {
        edges.push(
          edge({
            sourceNodeId: target.node.id,
            targetNodeId: report.node.id,
            type: "reported_by",
            confidence,
            evidenceText: "报告元数据与该主题证据链存在可解释匹配。",
            createdAt: report.date ?? target.date,
            metadata: { relation: "evidence_reported_by_report" },
          })
        )
      }
    }
  }

  return edges
}

function buildSummary(
  topicNode: EvidenceNode,
  candidates: GraphCandidate[],
  edges: EvidenceEdge[],
  timeline: EvidenceGraphTimelineItem[],
  generatedAt: string
): TopicEvidenceSummary {
  const evidenceNodes = candidates.map((candidate) => candidate.node)
  const paperCount = evidenceNodes.filter((node) => node.type === "paper").length
  const projectCount = evidenceNodes.filter((node) => node.type === "project").length
  const newsCount = evidenceNodes.filter((node) => node.type === "news").length
  const communitySignalCount = evidenceNodes.filter((node) => node.type === "community_signal").length
  const boardCount = new Set(candidates.filter((candidate) => candidate.board !== "report").map((candidate) => candidate.board)).size
  const dates = evidenceNodes.flatMap((node) => [node.createdAt, node.updatedAt]).filter(isString)
  const confidenceAverage = averageNumbers(evidenceNodes.map((node) => node.confidence).filter(isNumber)) ?? 0
  const sourceDiversityScore = Math.min(uniqueStrings(evidenceNodes.map((node) => node.source)).length / 8, 1) * 100
  const nodeCountScore = Math.min(evidenceNodes.length / 24, 1) * 100
  const recencyScore = averageNumbers(evidenceNodes.map((node) => recencyScoreFor(node.updatedAt ?? node.createdAt)).filter(isNumber)) ?? 0
  const crossBoardCoverage = Math.min(boardCount / 4, 1) * 100
  const evidenceScore = weightedScore([
    [sourceDiversityScore, 0.3],
    [nodeCountScore, 0.2],
    [confidenceAverage, 0.2],
    [recencyScore, 0.15],
    [crossBoardCoverage, 0.15],
  ])
  const trendScore = weightedScore([
    [boardVelocity(candidates, "news"), 0.25],
    [boardVelocity(candidates, "paper"), 0.2],
    [boardVelocity(candidates, "project"), 0.25],
    [boardVelocity(candidates, "community"), 0.2],
    [candidates.some((candidate) => candidate.board === "report") ? 100 : 0, 0.1],
  ])
  const verifiedSourceRatio = candidates.length ? (candidates.filter((candidate) => candidate.verifiedSource).length / candidates.length) * 100 : 0
  const crossSourceAgreement = crossBoardCoverage
  const sourceReliability = averageNumbers(candidates.map((candidate) => candidate.sourceReliability)) ?? 0
  const contradictionPenalty = edges.filter((edgeItem) => edgeItem.type === "contradicts").length ? 100 : controversyPenalty(candidates)
  const confidenceScore = clampScore(
    verifiedSourceRatio * 0.35 + crossSourceAgreement * 0.25 + sourceReliability * 0.25 + contradictionPenalty * -0.15
  )
  const trajectory = trajectoryFromScores(trendScore, evidenceScore, confidenceScore)
  const keyEvidenceNodeIds = sortCandidates(candidates).slice(0, 8).map((candidate) => candidate.node.id)
  const summary = evidenceNodes.length
    ? `「${topicNode.title}」已连接 ${paperCount} 篇论文、${projectCount} 个项目、${newsCount} 条新闻和 ${communitySignalCount} 个社区信号，证据链显示该主题处于${trajectoryLabel(trajectory)}状态。`
    : `当前真实数据源暂未返回「${topicNode.title}」的跨板块证据。`

  return {
    topicId: topicNode.id,
    topicName: topicNode.title,
    summary,
    trendScore,
    evidenceScore,
    confidenceScore,
    paperCount,
    projectCount,
    newsCount,
    communitySignalCount,
    firstSeenAt: minDate(dates) ?? generatedAt,
    lastUpdatedAt: maxDate(dates) ?? generatedAt,
    trajectory,
    keyEvidenceNodeIds,
  }
}

function buildTimeline(topicId: string, candidates: GraphCandidate[], edges: EvidenceEdge[]): EvidenceGraphTimelineItem[] {
  const edgeCounts = new Map<string, number>()
  for (const edgeItem of edges) {
    edgeCounts.set(edgeItem.sourceNodeId, (edgeCounts.get(edgeItem.sourceNodeId) ?? 0) + 1)
    edgeCounts.set(edgeItem.targetNodeId, (edgeCounts.get(edgeItem.targetNodeId) ?? 0) + 1)
  }

  return candidates
    .filter((candidate) => candidate.date)
    .sort((left, right) => dateValue(left.date) - dateValue(right.date))
    .slice(-16)
    .map((candidate) => ({
      id: `timeline-${stableHash(candidate.node.id)}`,
      topicId,
      occurredAt: candidate.date ?? "",
      title: `${boardLabel(candidate.board)}：${candidate.node.title}`,
      summary: candidate.node.summary ?? candidate.node.title,
      sourceCount: Math.max(1, edgeCounts.get(candidate.node.id) ?? 0),
      nodeIds: [candidate.node.id],
      importance: importanceFor(candidate.node),
      board: candidate.board,
      href: candidate.href,
    }))
}

function buildRelatedReports(candidates: GraphCandidate[], edges: EvidenceEdge[]): EvidenceGraphRelatedReport[] {
  const edgeLookup = new Map<string, Set<string>>()
  for (const edgeItem of edges) {
    const set = edgeLookup.get(edgeItem.targetNodeId) ?? new Set<string>()
    set.add(edgeItem.sourceNodeId)
    edgeLookup.set(edgeItem.targetNodeId, set)
  }

  return candidates
    .filter((candidate) => candidate.board === "report")
    .map((candidate) => ({
      id: candidate.node.id,
      title: candidate.node.title,
      href: candidate.href ?? "/reports",
      status: textValue(candidate.node.metadata?.status),
      createdAt: candidate.node.createdAt,
      summary: candidate.node.summary,
      evidenceNodeIds: [...(edgeLookup.get(candidate.node.id) ?? new Set<string>())],
    }))
}

function relationConfidence(source: GraphCandidate, target: GraphCandidate): number {
  const urlOverlap = overlapCount(source.relatedUrls, target.relatedUrls)
  if (urlOverlap > 0) {
    return 0.9
  }

  const titleOverlap = tokenOverlap(source.relatedTitles.join(" "), `${target.node.title} ${target.relatedTitles.join(" ")}`)
  const searchOverlap = tokenOverlap(source.searchText, target.searchText)
  const score = Math.max(titleOverlap, searchOverlap * 0.8)
  return Math.min(0.88, Math.max(0, score))
}

function matchesTopic(candidate: GraphCandidate, topicName: string, entityName?: string): boolean {
  const topic = normalizeText(topicName)
  const entity = normalizeText(entityName ?? "")
  if (!topic && !entity) {
    return true
  }
  return [topic, entity].filter(Boolean).some((needle) => candidate.searchText.includes(needle) || tokenOverlap(candidate.searchText, needle) >= 0.5)
}

function matchesPeriod(candidate: GraphCandidate, period: EvidenceGraphPeriod): boolean {
  if (period === "all") {
    return true
  }
  const value = candidate.date ?? candidate.node.updatedAt ?? candidate.node.createdAt
  const time = dateValue(value)
  if (!Number.isFinite(time)) {
    return false
  }
  return Date.now() - time <= PERIOD_DAYS[period] * 24 * 60 * 60 * 1000
}

function filterByNodeTypes(candidates: GraphCandidate[], nodeTypes?: EvidenceNodeType[]) {
  if (!nodeTypes?.length) {
    return candidates
  }
  const allowed = new Set(nodeTypes)
  return candidates.filter((candidate) => allowed.has(candidate.node.type))
}

function strongestTopic(candidates: GraphCandidate[]) {
  const counts = new Map<string, number>()
  for (const candidate of candidates) {
    for (const tag of candidate.node.tags ?? []) {
      const clean = cleanText(tag)
      if (!clean || clean.length < 3 || isGenericTag(clean)) {
        continue
      }
      counts.set(clean, (counts.get(clean) ?? 0) + (candidate.node.score ?? 50))
    }
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0]?.[0]
}

function sortCandidates(candidates: GraphCandidate[]) {
  return [...candidates].sort((left, right) => {
    return (
      compareNumber(right.node.score, left.node.score) ||
      compareNumber(right.node.confidence, left.node.confidence) ||
      compareNumber(dateValue(right.date), dateValue(left.date))
    )
  })
}

function edge(input: Omit<EvidenceEdge, "id">): EvidenceEdge {
  return {
    ...input,
    id: `edge-${stableHash(`${input.sourceNodeId}:${input.type}:${input.targetNodeId}:${input.evidenceText ?? ""}`)}`,
  }
}

function dedupeEdges(edges: EvidenceEdge[]) {
  const seen = new Set<string>()
  return edges.filter((edgeItem) => {
    const key = `${edgeItem.sourceNodeId}:${edgeItem.type}:${edgeItem.targetNodeId}`
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

function sourceState(
  board: EvidenceGraphSourceState["board"],
  state: EvidenceGraphSourceState["state"],
  source: string,
  count: number,
  notices: string[]
): EvidenceGraphSourceState {
  return { board, state, source, count, notices }
}

function boardVelocity(candidates: GraphCandidate[], board: BoardKey) {
  const items = candidates.filter((candidate) => candidate.board === board)
  if (!items.length) {
    return 0
  }
  const countScore = Math.min(items.length / 8, 1) * 60
  const freshness = averageNumbers(items.map((candidate) => recencyScoreFor(candidate.date)).filter(isNumber)) ?? 0
  return clampScore(countScore + freshness * 0.4)
}

function recencyScoreFor(value?: string): number | undefined {
  const time = dateValue(value)
  if (!Number.isFinite(time)) {
    return undefined
  }
  const days = Math.max(0, (Date.now() - time) / (24 * 60 * 60 * 1000))
  if (days <= 7) return 100
  if (days <= 30) return 75
  if (days <= 90) return 50
  if (days <= 365) return 30
  return 10
}

function controversyPenalty(candidates: GraphCandidate[]) {
  const controversial = candidates.filter((candidate) => {
    const sentiment = textValue(candidate.node.metadata?.sentiment)
    return sentiment === "negative" || sentiment === "mixed" || (candidate.node.tags ?? []).some((tag) => normalizeText(tag).includes("controvers"))
  }).length
  return candidates.length ? (controversial / candidates.length) * 100 : 0
}

function trajectoryFromScores(trend: number, evidence: number, confidence: number): TopicEvidenceTrajectory {
  if (confidence < 40 && trend > 55) return "noisy"
  if (trend >= 70 && evidence >= 45) return "rising"
  if (trend <= 25 && evidence >= 45) return "declining"
  if (evidence >= 35 && confidence >= 55) return "stable"
  return "uncertain"
}

function trajectoryLabel(value: TopicEvidenceTrajectory) {
  const labels: Record<TopicEvidenceTrajectory, string> = {
    rising: "升温",
    stable: "稳定",
    declining: "退潮",
    noisy: "噪声偏高",
    uncertain: "不确定",
  }
  return labels[value]
}

function importanceFor(node: EvidenceNode): EvidenceGraphTimelineItem["importance"] {
  if ((node.score ?? 0) >= 75 || (node.confidence ?? 0) >= 85) return "high"
  if ((node.score ?? 0) >= 45 || (node.confidence ?? 0) >= 65) return "medium"
  return "low"
}

function boardLabel(board: BoardKey) {
  const labels: Record<BoardKey, string> = {
    paper: "论文信号",
    project: "项目信号",
    news: "新闻报道",
    community: "社区讨论",
    report: "报告引用",
  }
  return labels[board]
}

function nodeId(type: EvidenceNodeType, value: string) {
  return `${type}:${slugify(value) || stableHash(value)}`
}

function topicFromId(topicId: string) {
  return topicId.replace(/^topic:/, "").replace(/-/g, " ")
}

function parseNodeTypes(value?: string | null): EvidenceNodeType[] | undefined {
  if (!value) {
    return undefined
  }
  const types = value.split(",").map((item) => item.trim()).filter(Boolean) as EvidenceNodeType[]
  return types.filter((type) => EVIDENCE_NODE_TYPES.includes(type))
}

function parsePeriod(value?: string | null): EvidenceGraphPeriod | undefined {
  return value === "daily" || value === "weekly" || value === "monthly" || value === "all" ? value : undefined
}

function numberParam(value?: string | null) {
  if (!value) {
    return undefined
  }
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

function stringParam(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value
}

function clampInteger(value: unknown, min: number, max: number, fallback: number) {
  const number = typeof value === "number" ? value : Number(value)
  if (!Number.isInteger(number)) {
    return fallback
  }
  return Math.min(max, Math.max(min, number))
}

function cleanText(value: unknown) {
  return typeof value === "string" ? value.trim() : ""
}

function textValue(value: unknown) {
  return typeof value === "string" || typeof value === "number" ? String(value).trim() : undefined
}

function normalizeText(value: string) {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

function normalizeUrlish(value: string) {
  const clean = cleanText(value)
  if (!clean) {
    return undefined
  }
  try {
    const url = new URL(clean.startsWith("github.com/") ? `https://${clean}` : clean)
    return `${url.hostname.replace(/^www\./, "")}${url.pathname.replace(/\/$/, "")}`.toLowerCase()
  } catch {
    return normalizeText(clean)
  }
}

function tokenOverlap(left: string, right: string) {
  const leftTokens = tokenSet(left)
  const rightTokens = tokenSet(right)
  if (!leftTokens.size || !rightTokens.size) {
    return 0
  }
  let overlap = 0
  for (const token of rightTokens) {
    if (leftTokens.has(token)) {
      overlap += 1
    }
  }
  return overlap / Math.min(leftTokens.size, rightTokens.size)
}

function tokenSet(value: string) {
  return new Set(normalizeText(value).split(" ").filter((token) => token.length >= 3 && !GENERIC_TOKENS.has(token)))
}

function overlapCount(left: string[], right: string[]) {
  const rightSet = new Set(right)
  return left.filter((value) => rightSet.has(value)).length
}

const GENERIC_TOKENS = new Set(["the", "and", "for", "with", "from", "this", "that", "news", "paper", "project", "community"])

function isGenericTag(value: string) {
  return GENERIC_TOKENS.has(normalizeText(value)) || ["ready", "unknown", "custom", "manual", "github", "arxiv"].includes(normalizeText(value))
}

function cleanTags(values: Array<string | undefined | null>) {
  return uniqueStrings(values.map((value) => cleanText(value)).filter((value) => value && !isGenericTag(value))).slice(0, 16)
}

function sourceReliability(sourceType?: string, sourceName?: string) {
  const normalized = normalizeText(`${sourceType ?? ""} ${sourceName ?? ""}`)
  if (normalized.includes("official") || normalized.includes("arxiv") || normalized.includes("openreview")) return 92
  if (normalized.includes("github")) return 82
  if (normalized.includes("hackernews") || normalized.includes("reddit")) return 66
  if (normalized.includes("media") || normalized.includes("rss") || normalized.includes("atom")) return 72
  return 60
}

function isVerifiedSource(sourceType?: string, sourceName?: string) {
  const reliability = sourceReliability(sourceType, sourceName)
  return reliability >= 80
}

function credibilityScore(value?: string) {
  if (value === "high") return 88
  if (value === "medium") return 68
  if (value === "low") return 45
  return 60
}

function confidenceFromEvidence(evidenceCount: number, base: number) {
  return clampScore(base + Math.min(evidenceCount, 6) * 3)
}

function scoreValue(...values: Array<number | undefined>) {
  const first = values.find(isNumber)
  if (first === undefined) {
    return undefined
  }
  return clampScore(first > 100 ? Math.log10(first + 1) * 20 : first)
}

function unitConfidence(value?: number) {
  return clampScore(value ?? 60) / 100
}

function weightedScore(parts: Array<[number, number]>) {
  return clampScore(parts.reduce((sum, [value, weight]) => sum + value * weight, 0))
}

function clampScore(value: number) {
  return Math.round(Math.max(0, Math.min(100, value)))
}

function averageNumbers(values: number[]) {
  const numbers = values.filter(isNumber)
  if (!numbers.length) {
    return undefined
  }
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length
}

function minDate(values: string[]) {
  return values.sort((left, right) => dateValue(left) - dateValue(right))[0]
}

function maxDate(values: string[]) {
  return values.sort((left, right) => dateValue(right) - dateValue(left))[0]
}

function dateValue(value?: string) {
  if (!value) {
    return Number.NEGATIVE_INFINITY
  }
  const time = Date.parse(value)
  return Number.isFinite(time) ? time : Number.NEGATIVE_INFINITY
}

function compareNumber(left: number | undefined, right: number | undefined) {
  return (left ?? Number.NEGATIVE_INFINITY) - (right ?? Number.NEGATIVE_INFINITY)
}

function uniqueStrings(values: Array<string | undefined | null>) {
  return [...new Set(values.filter(isString).map((value) => value.trim()).filter(Boolean))]
}

function slugify(value: string) {
  return normalizeText(value).replace(/\s+/g, "-").slice(0, 80)
}

function stableHash(value: string) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash.toString(16)
}

function isNumber(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isString(value: string | undefined | null): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function isPublishedStatus(status?: string) {
  return ["final", "published", "publish", "pass", "passed", "succeeded", "success"].includes((status ?? "").toLowerCase())
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
