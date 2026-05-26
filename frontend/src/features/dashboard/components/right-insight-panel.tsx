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
        title="Quality status"
        icon={Gauge}
        badge={<Badge variant={qualityVariant(overview.quality.status)}>{overview.quality.status}</Badge>}
      >
        <p className="text-sm leading-5 text-muted-foreground">{overview.quality.summary}</p>
        {overview.quality.score !== undefined ? (
          <p className="mt-3 text-sm font-medium text-foreground">Score {overview.quality.score}</p>
        ) : null}
      </PanelCard>

      {overview.rightInsights.map((insight, index) => {
        const Icon = insightIcons[index % insightIcons.length]
        return (
          <PanelCard key={insight.id} title={insight.title} icon={Icon} badge={<Badge variant={toneVariant(insight)}>{insight.value ?? insight.tone ?? "info"}</Badge>}>
            <p className="text-sm leading-5 text-muted-foreground">{insight.summary}</p>
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

function toneVariant(insight: RightInsight) {
  if (insight.tone === "success") return "success"
  if (insight.tone === "warning") return "warning"
  if (insight.tone === "danger") return "danger"
  if (insight.tone === "accent") return "accent"
  if (insight.tone === "info") return "info"
  return "muted"
}
