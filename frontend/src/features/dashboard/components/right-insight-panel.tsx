import { Bot, Database, Gauge, NotebookText } from "lucide-react"
import type { ComponentType, ReactNode } from "react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { DashboardOverview, RightInsight } from "@/types/dashboard"

const insightIcons = [Database, Gauge, Bot, NotebookText]

export function RightInsightPanel({ overview }: { overview: DashboardOverview }) {
  return (
    <aside className="space-y-4">
      <PanelCard
        title="质量状态"
        icon={Gauge}
        badge={<Badge variant={qualityVariant(overview.quality.status)}>{qualityLabel(overview.quality.status)}</Badge>}
      >
        <p className="text-sm leading-5 text-muted-foreground">{overview.quality.summary}</p>
        {overview.quality.score !== undefined ? (
          <p className="mt-3 text-sm font-medium text-foreground">得分 {overview.quality.score}</p>
        ) : null}
      </PanelCard>

      {overview.rightInsights.map((insight, index) => {
        const Icon = insightIcons[index % insightIcons.length]
        return (
          <PanelCard key={insight.id} title={insightTitle(insight)} icon={Icon} badge={<Badge variant={toneVariant(insight)}>{insight.value ?? toneLabel(insight.tone)}</Badge>}>
            <p className="text-sm leading-5 text-muted-foreground">{insightSummary(insight)}</p>
            {insight.items?.length ? (
              <ul className="mt-3 space-y-2">
                {insight.items.map((item) => (
                  <li key={item} className="text-xs leading-5 text-muted-foreground">
                    {item}
                  </li>
                ))}
              </ul>
            ) : null}
          </PanelCard>
        )
      })}
    </aside>
  )
}

function PanelCard({
  title,
  icon: Icon,
  badge,
  children
}: {
  title: string
  icon: ComponentType<{ className?: string }>
  badge?: ReactNode
  children: ReactNode
}) {
  return (
    <Card className="p-4">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-accent" />
          <h2 className="truncate text-sm font-semibold text-foreground">{title}</h2>
        </div>
        {badge}
      </div>
      {children}
    </Card>
  )
}

function qualityVariant(status: DashboardOverview["quality"]["status"]) {
  if (status === "passed") return "success"
  if (status === "failed") return "danger"
  if (status === "review") return "warning"
  return "muted"
}

function qualityLabel(status: DashboardOverview["quality"]["status"]) {
  if (status === "passed") return "通过"
  if (status === "failed") return "未通过"
  if (status === "review") return "需复核"
  return "未知"
}

function insightTitle(insight: RightInsight) {
  const titles: Record<string, string> = {
    freshness: "数据新鲜度",
    quality: "质量状态",
    source: "数据来源",
    "agent-notes": "Agent notes",
    fallback: "Fallback 状态",
    "fallback-mode": "Fallback 状态"
  }
  return titles[insight.id] ?? insight.title
}

function insightSummary(insight: RightInsight) {
  if (insight.id === "freshness" && insight.updatedAt) {
    return `生成于 ${insight.updatedAt}`
  }
  if (insight.id === "agent-notes" && !insight.items?.length) {
    return "暂无额外来源提醒。"
  }
  if (insight.summary === "Showing local fallback") {
    return "Showing local fallback"
  }
  if (insight.summary.startsWith("Generated at ")) {
    return `生成于 ${insight.summary.replace("Generated at ", "")}`
  }
  if (insight.summary === "No generated timestamp is available.") {
    return "暂无生成时间。"
  }
  if (insight.summary === "Cross-board intelligence output") {
    return "Cross-board intelligence 产物"
  }
  if (insight.summary === "No notable source warnings.") {
    return "暂无额外来源提醒。"
  }
  return insight.summary
}

function toneLabel(tone: RightInsight["tone"]) {
  if (tone === "success") return "正常"
  if (tone === "warning") return "注意"
  if (tone === "danger") return "风险"
  if (tone === "accent") return "重点"
  if (tone === "info") return "信息"
  return "状态"
}

function toneVariant(insight: RightInsight) {
  if (insight.tone === "success") return "success"
  if (insight.tone === "warning") return "warning"
  if (insight.tone === "danger") return "danger"
  if (insight.tone === "accent") return "accent"
  if (insight.tone === "info") return "info"
  return "muted"
}
