import { BarChart3, FileText, Gauge, Layers3, MessageSquareText, Newspaper } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { DashboardMetric, DashboardOverview } from "@/types/dashboard"

const metricIcons = {
  signals: Gauge,
  news: Newspaper,
  projects: Layers3,
  papers: FileText,
  community: MessageSquareText,
  high_confidence: BarChart3
}

export function MetricsStrip({ overview }: { overview: DashboardOverview }) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {overview.metrics.map((metric) => {
        const Icon = metricIcons[metric.id as keyof typeof metricIcons] ?? BarChart3
        return (
          <Card key={metric.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-xs font-medium uppercase text-muted-foreground">{metric.label}</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">{formatMetricValue(metric)}</p>
              </div>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary text-accent">
                <Icon className="h-4 w-4" />
              </span>
            </div>
            <div className="mt-3 flex min-h-6 items-center justify-between gap-2 text-xs text-muted-foreground">
              <span className="line-clamp-2">{metric.description}</span>
              {metric.delta ? (
                <Badge variant={metric.delta.startsWith("-") ? "warning" : "success"}>{metric.delta}</Badge>
              ) : null}
            </div>
          </Card>
        )
      })}
    </section>
  )
}

function formatMetricValue(metric: DashboardMetric) {
  if (typeof metric.value === "string") {
    return metric.value
  }
  return new Intl.NumberFormat("en-US").format(metric.value)
}
