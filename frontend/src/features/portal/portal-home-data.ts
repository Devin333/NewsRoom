import { getCommunityList } from "@/lib/community/server-data"
import { getNewsListResult } from "@/lib/news/server-data"
import { getPublishedPapers } from "@/lib/papers/real-data"
import { paperMethods, paperTasks } from "@/lib/papers/catalog"
import { getProjectList } from "@/lib/projects/data-source"
import { safeApiGet } from "@/lib/api/server"

export type PortalModuleStatus = "ready" | "empty" | "degraded"

export type PortalMetric = {
  label: string
  value: string | number
}

export type PortalHighlight = {
  title: string
  href?: string
  meta?: string
}

export type PortalModuleSummary = {
  id: "news" | "projects" | "papers" | "community" | "evidence" | "reports"
  title: string
  href: string
  eyebrow: string
  description: string
  status: PortalModuleStatus
  sourceLabel: string
  metrics: PortalMetric[]
  highlights: PortalHighlight[]
  notices: string[]
}

export type PortalHomeData = {
  generatedAt: string
  modules: PortalModuleSummary[]
  totalSignals: number
  readyModules: number
}

export type EvidenceGraphSection = {
  title: string
  href: string
  count: number
  status: PortalModuleStatus
  items: PortalHighlight[]
}

export type EvidenceGraphData = {
  generatedAt: string
  topicName: string
  summary: string
  sections: EvidenceGraphSection[]
  timeline: PortalHighlight[]
  notices: string[]
}

type ReportListResponse = {
  reports?: Array<{
    report_id?: string | null
    id?: string | null
    title?: string | null
    status?: string | null
    finished_at?: string | null
    published_at?: string | null
    created_at?: string | null
    workflow_id?: string | null
    profile?: string | null
  }>
}

export async function getPortalHomeData(): Promise<PortalHomeData> {
  const [news, projects, papers, community, reports] = await Promise.all([
    newsModule(),
    projectsModule(),
    papersModule(),
    communityModule(),
    reportsModule()
  ])
  const evidence = evidenceModule([news, projects, papers, community, reports])
  const modules = [news, projects, papers, community, evidence, reports]

  return {
    generatedAt: new Date().toISOString(),
    modules,
    totalSignals: modules.reduce((total, module) => total + primaryCount(module), 0),
    readyModules: modules.filter((module) => module.status === "ready").length
  }
}

export async function getEvidenceGraphData(): Promise<EvidenceGraphData> {
  const data = await getPortalHomeData()
  const byId = new Map(data.modules.map((module) => [module.id, module]))
  const sections: EvidenceGraphSection[] = [
    graphSection("Papers", "/papers", byId.get("papers")),
    graphSection("Projects", "/tech/repos", byId.get("projects")),
    graphSection("News", "/news", byId.get("news")),
    graphSection("Community", "/community", byId.get("community"))
  ]
  const total = sections.reduce((count, section) => count + section.count, 0)

  return {
    generatedAt: data.generatedAt,
    topicName: "Cross-board Evidence Graph",
    summary: total
      ? `Evidence is stitched from ${total} available public signals across papers, projects, news, and community discussion.`
      : "No cross-board evidence is available from the current data sources.",
    sections,
    timeline: buildTimeline(sections),
    notices: data.modules.flatMap((module) => module.notices.map((notice) => `${module.title}: ${notice}`))
  }
}

async function newsModule(): Promise<PortalModuleSummary> {
  try {
    const result = await getNewsListResult({ sort: "heatScore", pageSize: 6 })
    const items = result.allItems
    return {
      id: "news",
      title: "AI News",
      href: "/news",
      eyebrow: "Today",
      description: "Official updates, product changes, funding, policy, and ecosystem signals.",
      status: items.length ? stateFrom(result.dataState === "ready") : "empty",
      sourceLabel: result.source,
      metrics: [
        { label: "Items", value: items.length },
        { label: "Sources", value: result.options.sourceTypes.length },
        { label: "Topics", value: unique(items.map((item) => item.topicName ?? item.topicId)).length }
      ],
      highlights: items.slice(0, 3).map((item) => ({
        title: item.title,
        href: `/news/${item.id}`,
        meta: item.sourceName
      })),
      notices: result.notices
    }
  } catch (error) {
    return unavailableModule("news", "AI News", "/news", "Today", "News data is currently unavailable.", error)
  }
}

async function projectsModule(): Promise<PortalModuleSummary> {
  try {
    const result = await getProjectList({ sort: "trending", pageSize: 6 })
    const items = result.allItems
    return {
      id: "projects",
      title: "Project Radar",
      href: "/tech/repos",
      eyebrow: "Open Source",
      description: "GitHub projects, engineering practice, repository momentum, and adoption signals.",
      status: items.length ? stateFrom(result.dataState === "ready") : "empty",
      sourceLabel: result.source,
      metrics: [
        { label: "Projects", value: items.length },
        { label: "Categories", value: result.options.categories.length },
        { label: "Languages", value: result.options.languages.length }
      ],
      highlights: items.slice(0, 3).map((item) => ({
        title: item.name,
        href: `/projects/${item.slug}`,
        meta: item.repoUrl
      })),
      notices: result.notices
    }
  } catch (error) {
    return unavailableModule("projects", "Project Radar", "/tech/repos", "Open Source", "Project data is currently unavailable.", error)
  }
}

async function papersModule(): Promise<PortalModuleSummary> {
  try {
    const papers = await getPublishedPapers()
    return {
      id: "papers",
      title: "Paper Radar",
      href: "/papers",
      eyebrow: "Research",
      description: "Trending papers, research tasks, methods, repositories, and implementation evidence.",
      status: papers.length ? "ready" : "empty",
      sourceLabel: papers.length ? "papers" : "empty",
      metrics: [
        { label: "Papers", value: papers.length },
        { label: "Tasks", value: paperTasks.length },
        { label: "Methods", value: paperMethods.length }
      ],
      highlights: papers.slice(0, 3).map((paper) => ({
        title: paper.title,
        href: `/papers?paper=${encodeURIComponent(paper.id)}`,
        meta: paper.venue
      })),
      notices: papers.length ? [] : ["No published papers are available."]
    }
  } catch (error) {
    return unavailableModule("papers", "Paper Radar", "/papers", "Research", "Paper data is currently unavailable.", error)
  }
}

async function communityModule(): Promise<PortalModuleSummary> {
  try {
    const result = await getCommunityList({ sort: "trending", pageSize: 6 })
    const topics = result.allTopics
    return {
      id: "community",
      title: "Community Pulse",
      href: "/community",
      eyebrow: "Community",
      description: "Developer discussion, sentiment, controversy, propagation paths, and adoption feedback.",
      status: topics.length ? stateFrom(result.dataState === "ready") : "empty",
      sourceLabel: result.source,
      metrics: [
        { label: "Topics", value: topics.length },
        { label: "Sources", value: result.metrics.activeSources },
        { label: "Mixed", value: result.metrics.mixedCount }
      ],
      highlights: topics.slice(0, 3).map((topic) => ({
        title: topic.title,
        href: `/community/topics/${topic.slug}`,
        meta: topic.sourceName ?? topic.sourceType
      })),
      notices: result.notices
    }
  } catch (error) {
    return unavailableModule("community", "Community Pulse", "/community", "Community", "Community data is currently unavailable.", error)
  }
}

async function reportsModule(): Promise<PortalModuleSummary> {
  const result = await safeApiGet<ReportListResponse>("/api/v1/reports?limit=50")
  if (!result.ok) {
    return unavailableModule("reports", "Reports / Briefings", "/reports", "Reports", "Reports are currently unavailable.", result.errorMessage)
  }

  const reports = result.data.reports ?? []
  return {
    id: "reports",
    title: "Reports / Briefings",
    href: "/reports",
    eyebrow: "Briefings",
    description: "Daily, weekly, and deep-dive intelligence outputs generated from collected evidence.",
    status: reports.length ? "ready" : "empty",
    sourceLabel: "backend",
    metrics: [
      { label: "Reports", value: reports.length },
      { label: "Published", value: reports.filter((report) => isPublishedStatus(report.status)).length },
      { label: "Workflows", value: unique(reports.map((report) => report.workflow_id ?? report.profile)).length }
    ],
    highlights: reports.slice(0, 3).map((report) => ({
      title: report.title ?? report.report_id ?? report.id ?? "Untitled report",
      href: `/reports/${encodeURIComponent(report.report_id ?? report.id ?? "")}`,
      meta: report.status ?? "generated"
    })),
    notices: reports.length ? [] : ["No reports were returned by the backend."]
  }
}

function evidenceModule(modules: PortalModuleSummary[]): PortalModuleSummary {
  const count = modules.reduce((total, module) => total + primaryCount(module), 0)
  const degraded = modules.some((module) => module.status === "degraded")
  const empty = modules.every((module) => module.status === "empty")
  return {
    id: "evidence",
    title: "Cross-board Evidence Graph",
    href: "/topics?view=evidence-graph",
    eyebrow: "Evidence",
    description: "把 Paper、Project、Community、AI News 串成证据链和技术演进链。",
    status: empty ? "empty" : degraded ? "degraded" : "ready",
    sourceLabel: "derived",
    metrics: [
      { label: "Signals", value: count },
      { label: "Boards", value: modules.filter((module) => module.status !== "empty").length },
      { label: "Ready", value: modules.filter((module) => module.status === "ready").length }
    ],
    highlights: modules
      .filter((module) => module.id !== "reports")
      .slice(0, 4)
      .map((module) => ({
        title: module.title,
        href: module.href,
        meta: `${primaryCount(module)} signals`
      })),
    notices: degraded ? ["One or more evidence sources are degraded."] : []
  }
}

function unavailableModule(
  id: PortalModuleSummary["id"],
  title: string,
  href: string,
  eyebrow: string,
  description: string,
  error: unknown
): PortalModuleSummary {
  return {
    id,
    title,
    href,
    eyebrow,
    description,
    status: "degraded",
    sourceLabel: "unavailable",
    metrics: [
      { label: "Items", value: 0 },
      { label: "State", value: "degraded" },
      { label: "Source", value: "offline" }
    ],
    highlights: [],
    notices: [error instanceof Error ? error.message : String(error)]
  }
}

function graphSection(title: string, href: string, module: PortalModuleSummary | undefined): EvidenceGraphSection {
  return {
    title,
    href,
    count: module ? primaryCount(module) : 0,
    status: module?.status ?? "empty",
    items: module?.highlights ?? []
  }
}

function buildTimeline(sections: EvidenceGraphSection[]): PortalHighlight[] {
  return sections
    .filter((section) => section.count > 0)
    .map((section) => ({
      title: `${section.title} evidence available`,
      href: section.href,
      meta: `${section.count} signals`
    }))
}

function primaryCount(module: PortalModuleSummary) {
  const firstMetric = module.metrics[0]?.value
  return typeof firstMetric === "number" ? firstMetric : Number(firstMetric) || 0
}

function stateFrom(ready: boolean): PortalModuleStatus {
  return ready ? "ready" : "degraded"
}

function unique(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter(Boolean)))
}

function isPublishedStatus(status: string | null | undefined) {
  return ["final", "published", "publish", "pass", "passed", "succeeded", "success"].includes((status ?? "").toLowerCase())
}
