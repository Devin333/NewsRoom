import type { AgentRun } from "@/types/agent"
import type { DashboardOverview, TopStory, TrendingTopic } from "@/types/dashboard"
import type { NewsItem } from "@/types/news"
import type { QualityGateSummary } from "@/types/quality"
import type { SourceHealth } from "@/types/source"
import { evidences, newsItems, reports, techItems, topics } from "@/lib/mock-data"

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
  summary: "引用覆盖和来源新鲜度已通过，一个社区来源被标记为待复核。"
}

const fallbackStories: TopStory[] = [...newsItems]
  .sort((left, right) => (right.heatScore ?? 0) - (left.heatScore ?? 0))
  .slice(0, 5)
  .map((item) => ({
    id: item.id,
    title: item.title,
    summary: item.summary,
    board: "news",
    objectId: item.id,
    href: `/news/${encodeURIComponent(item.id)}`,
    score: item.heatScore,
    confidence: item.qualityScore,
    publishedAt: item.publishedAt,
    sourceName: item.sourceName,
    tags: item.tags
  }))

const fallbackTopics: TrendingTopic[] = topics.slice(0, 5).map((topic) => ({
  id: topic.id,
  name: topic.name,
  summary: topic.summary,
  trend: topic.trend,
  heatScore: topic.heatScore,
  signalCount: topic.itemCount,
  boards: ["cross_board"],
  href: `/topics/${encodeURIComponent(topic.id)}`
}))

export const mockDashboardOverview: DashboardOverview = {
  generatedAt: "2026-05-23T08:42:00+08:00",
  dataState: "fallback",
  metrics: [
    { id: "signals", label: "今日信号", value: 146, description: "已采集 AI 信号", delta: "+18%" },
    { id: "news", label: "重要新闻", value: 58, description: "已排序去重新闻", delta: "-7 重复" },
    { id: "projects", label: "热门项目", value: 12, description: "项目雷达条目", delta: "+4" },
    { id: "papers", label: "热门论文", value: 9, description: "论文雷达条目" },
    { id: "community", label: "社区讨论", value: 21, description: "社区脉搏话题" },
    { id: "high_confidence", label: "高置信洞察", value: 82, description: "平均质量评分", delta: "+5" }
  ],
  brief: {
    title: "运行时证据正在成为新的 Agent 平台界面",
    summary:
      "当前 fallback 信号显示，Agent 框架正在把 trace、策略和质量证据变成原生运行时对象。",
    keyFindings: [
      "Agent 运行时发布正在让策略决策和步骤结果可检查。",
      "编码 Agent 基准越来越强调仓库级修复和验证。",
      "开放模型发布正在竞争工具使用一致性，而不只是原始基准分数。"
    ],
    coreJudgments: [
      "控制与可观测性正在从应用胶水层进入框架运行时契约。",
      "团队应优先关注能暴露证据、复核门控和可重复阅读路径的系统。"
    ],
    readingPath: fallbackStories.slice(0, 4).map((story) => ({
      id: story.id,
      label: story.title,
      href: story.href,
      description: story.summary,
      board: story.board
    })),
    agentNotes: ["Showing local fallback"],
    mainTrend: "Agent 运行时控制与可观测性",
    riskNote: "社区治理信号仍需复核，暂不应直接视为高置信判断。",
    updatedAt: "2026-05-23T08:42:00+08:00",
    reportId: reports[0]?.id
  },
  topStories: fallbackStories,
  trendingTopics: fallbackTopics,
  techRadar: [
    {
      id: "fallback-paper",
      name: techItems.find((item) => item.type === "paper")?.name ?? "生产 RAG 记忆生命周期评估",
      summary: "Fallback 论文雷达条目。",
      category: "paper",
      href: "/papers"
    },
    {
      id: "fallback-project",
      name: techItems.find((item) => item.type === "repo")?.name ?? "面向 Agent 的可审计浏览器自动化",
      summary: "Fallback 项目雷达条目。",
      category: "project",
      href: "/projects"
    },
    {
      id: "fallback-framework",
      name: techItems.find((item) => item.type === "framework")?.name ?? "策略感知工作流检查点",
      summary: "Fallback 框架雷达条目。",
      category: "framework"
    }
  ],
  rightInsights: [
    {
      id: "fallback-mode",
      title: "Fallback 状态",
      summary: "Showing local fallback",
      tone: "warning"
    },
    {
      id: "quality",
      title: "质量门控",
      summary: mockQualityResult.summary,
      tone: "success",
      value: `${mockQualityResult.passedChecks}/${mockQualityResult.totalChecks}`
    }
  ],
  quality: {
    status: "passed",
    score: 82,
    summary: mockQualityResult.summary,
    generatedAt: "2026-05-23T08:42:00+08:00"
  },
  notices: ["Showing local fallback"]
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
