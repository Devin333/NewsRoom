import { BarChart3, FileText, Gauge, Layers3, Rss, ShieldCheck } from "lucide-react"
import { formatNumber, formatPercent, formatScore } from "@/lib/format"
import type { DashboardOverview } from "@/types/dashboard"

const metricConfig = [
  {
    key: "newsCollectedToday",
    label: "新闻采集",
    description: "今日采集",
    icon: Rss,
    format: formatNumber
  },
  {
    key: "deduplicatedItems",
    label: "已去重",
    description: "聚类后",
    icon: ShieldCheck,
    format: formatNumber
  },
  {
    key: "topicsUpdatedToday",
    label: "主题更新",
    description: "主题图谱变化",
    icon: Layers3,
    format: formatNumber
  },
  {
    key: "reportsGeneratedToday",
    label: "报告",
    description: "今日生成",
    icon: FileText,
    format: formatNumber
  },
  {
    key: "sourceSuccessRate",
    label: "来源成功率",
    description: "抓取成功率",
    icon: Gauge,
    format: formatPercent
  },
  {
    key: "avgQualityScore",
    label: "平均质量",
    description: "已分析新闻",
    icon: BarChart3,
    format: formatScore
  }
] as const

export function MetricsStrip({ overview }: { overview: DashboardOverview }) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {metricConfig.map((metric) => {
        const Icon = metric.icon
        const value = overview.metrics[metric.key]
        const delta = overview.metricDeltas?.[metric.key]
        return (
          <div key={metric.key} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">{metric.label}</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">{metric.format(value)}</p>
              </div>
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-accent">
                <Icon className="h-4 w-4" />
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{metric.description}</span>
              {delta ? <span className="text-success">{delta}</span> : null}
            </div>
          </div>
        )
      })}
    </section>
  )
}
