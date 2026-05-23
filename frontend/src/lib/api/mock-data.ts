import type { AgentRun } from "@/types/agent"
import type { DashboardOverview } from "@/types/dashboard"
import type { QualityGateSummary } from "@/types/quality"
import type { SourceHealth } from "@/types/source"
import { evidences, newsItems, reports, techItems, topics } from "@/lib/mock-data"
import type { NewsItem } from "@/types/news"

export const mockNewsItems = newsItems
export const mockNews = newsItems
export const mockTopics = topics
export const mockReports = reports
export const mockEvidence = evidences

export const mockAgentRuns: AgentRun[] = [
  {
    id: "run-20260523-reader-brief",
    agentName: "WriterAgent",
    workflowName: "daily-reader-intelligence-brief",
    profile: "reader-portal",
    status: "success",
    startedAt: "2026-05-23T08:12:00+08:00",
    finishedAt: "2026-05-23T08:31:00+08:00",
    durationMs: 1_140_000,
    durationSeconds: 1140,
    inputCount: 146,
    outputCount: 58,
    artifactCount: 7,
    qualityScore: 91,
    errorCount: 0,
    steps: [
      { id: "collect", label: "采集来源", status: "success" },
      { id: "cluster", label: "聚类主题", status: "success" },
      { id: "score", label: "质量评分", status: "success" },
      { id: "report", label: "生成简报", status: "success" }
    ]
  }
]

export const mockSources: SourceHealth[] = [
  {
    id: "source-official-ai",
    name: "官方 AI 博客",
    type: "official_blog",
    status: "healthy",
    successRate: 99,
    lastCheckedAt: "2026-05-23T08:20:00+08:00"
  },
  {
    id: "source-github-trending",
    name: "GitHub Trending",
    type: "github",
    status: "healthy",
    successRate: 96,
    lastCheckedAt: "2026-05-23T08:18:00+08:00"
  },
  {
    id: "source-hn-ai",
    name: "Hacker News AI",
    type: "hackernews",
    status: "degraded",
    successRate: 82,
    lastCheckedAt: "2026-05-23T08:10:00+08:00"
  }
]

export const mockQualityResult: QualityGateSummary = {
  status: "passed",
  passedChecks: 11,
  totalChecks: 12,
  summary: "引用覆盖和来源新鲜度已通过。一个社区来源条目标记为待复核。"
}

export const mockDashboardOverview: DashboardOverview = {
  metrics: {
    newsCollectedToday: 146,
    deduplicatedItems: 58,
    topicsUpdatedToday: 12,
    reportsGeneratedToday: 3,
    sourceSuccessRate: 94,
    avgQualityScore: 82
  },
  metricDeltas: {
    newsCollectedToday: "+18%",
    deduplicatedItems: "-7 个重复簇",
    topicsUpdatedToday: "+4",
    reportsGeneratedToday: "+1",
    sourceSuccessRate: "+2%",
    avgQualityScore: "+5"
  },
  brief: {
    title: "运行时证据正在成为新的 Agent 平台界面",
    summary:
      "今天最强的信号是：Agent 框架正在把 trace、策略和质量证据变成原生运行时对象。编码 Agent 基准和开放权重工具使用发布也强化了同一方向：团队需要可以检查、门控和改进的系统。",
    keyFindings: [
      "Agent 运行时发布正在让策略决策和步骤结果持久化。",
      "编码 Agent 基准现在强调仓库级修复和验证。",
      "开放模型发布正在竞争工具使用一致性，而不只是原始基准分数。"
    ],
    mainTrend: "控制与可观测性正在从应用胶水层进入框架运行时契约。",
    riskNote: "社区对治理逻辑应该位于何处仍有噪声，因此低可信来源需要复核。",
    updatedAt: "2026-05-23T08:42:00+08:00",
    reportId: reports[0]?.id
  },
  topStories: [...newsItems].sort((a, b) => b.heatScore - a.heatScore).slice(0, 5),
  trendingTopics: topics.slice(0, 5),
  latestRun: mockAgentRuns[0],
  latestReport: reports[0],
  sourceHealth: mockSources,
  qualityGate: mockQualityResult,
  techRadar: {
    paper: techItems.find((item) => item.type === "paper")?.name ?? "生产 RAG 系统的记忆生命周期评估",
    repo: techItems.find((item) => item.type === "repo")?.name ?? "面向 Agent 的可审计浏览器自动化工具",
    framework: techItems.find((item) => item.type === "framework")?.name ?? "策略感知工作流检查点"
  }
}

export const mockDashboard = mockDashboardOverview

export function getEvidenceForNews(news: NewsItem) {
  const ids = new Set(news.evidenceIds ?? [])
  return evidences.filter((item) => ids.has(item.id))
}

export function resolveMockPath(path: string): unknown {
  const normalizedPath = path.split("?")[0]
  if (normalizedPath === "/dashboard") return mockDashboardOverview
  if (normalizedPath === "/news") return { items: newsItems, total: newsItems.length, page: 1, pageSize: 20, hasNext: false }
  if (normalizedPath.startsWith("/news/")) return { data: newsItems.find((item) => item.id === normalizedPath.split("/").pop()) }
  if (normalizedPath === "/topics") return { items: topics, total: topics.length, page: 1, pageSize: 20, hasNext: false }
  if (normalizedPath.startsWith("/topics/")) return { data: topics.find((item) => item.id === normalizedPath.split("/").pop()) ?? topics[0] }
  if (normalizedPath === "/reports") return { items: reports, total: reports.length, page: 1, pageSize: 20, hasNext: false }
  if (normalizedPath.startsWith("/reports/")) return { data: reports.find((item) => item.id === normalizedPath.split("/").pop()) ?? reports[0] }
  if (normalizedPath === "/studio/runs") return { items: mockAgentRuns, total: mockAgentRuns.length, page: 1, pageSize: 20, hasNext: false }
  if (normalizedPath.startsWith("/studio/runs/")) return { data: mockAgentRuns.find((item) => item.id === normalizedPath.split("/").pop()) ?? mockAgentRuns[0] }
  if (normalizedPath === "/studio/sources") return { items: mockSources, total: mockSources.length, page: 1, pageSize: 20, hasNext: false }
  if (normalizedPath === "/studio/quality") return mockQualityResult
  return {}
}
