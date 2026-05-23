import { Activity, Bot, Database, FileText, Gauge } from "lucide-react"
import Link from "next/link"
import { ScoreMeter } from "@/components/common/score-meter"
import { SourceBadge } from "@/components/common/source-badge"
import { StatusBadge } from "@/components/common/status-badge"
import { formatDateTime } from "@/lib/format"
import type { DashboardOverview } from "@/types/dashboard"

export function RightInsightPanel({ overview }: { overview: DashboardOverview }) {
  const latestRun = overview.latestRun
  const latestReport = overview.latestReport

  return (
    <aside className="space-y-4">
      <PanelCard title="智能体状态" icon={Bot}>
        {latestRun ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">{latestRun.workflowName}</span>
              <StatusBadge status={latestRun.status} />
            </div>
            <p className="text-xs text-muted-foreground">完成于 {formatDateTime(latestRun.finishedAt)}</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">暂无智能体运行。</p>
        )}
      </PanelCard>

      <PanelCard title="数据源健康" icon={Database}>
        <div className="space-y-3">
          {overview.sourceHealth.map((source) => (
            <div key={source.id} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm text-foreground">{source.name}</p>
                <p className="text-xs text-muted-foreground">{source.successRate}% 成功率</p>
              </div>
              <SourceBadge type={source.type} />
            </div>
          ))}
        </div>
      </PanelCard>

      <PanelCard title="质量门控" icon={Gauge}>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <StatusBadge status={overview.qualityGate.status} />
            <span className="text-sm text-muted-foreground">
              {overview.qualityGate.passedChecks}/{overview.qualityGate.totalChecks}
            </span>
          </div>
          <p className="text-sm leading-5 text-muted-foreground">{overview.qualityGate.summary}</p>
        </div>
      </PanelCard>

      <PanelCard title="最近运行" icon={Activity}>
        {latestRun ? (
          <Link href={`/studio/runs/${latestRun.id}`} className="block rounded-md border border-border p-3 hover:bg-secondary">
            <p className="text-sm font-medium text-foreground">{latestRun.id}</p>
            <p className="mt-1 text-xs text-muted-foreground">{Math.round((latestRun.durationSeconds ?? 0) / 60)} 分钟运行时长</p>
          </Link>
        ) : (
          <p className="text-sm text-muted-foreground">暂无运行。</p>
        )}
      </PanelCard>

      <PanelCard title="最新报告" icon={FileText}>
        {latestReport ? (
          <Link href={`/reports/${latestReport.id}`} className="block rounded-md border border-border p-3 hover:bg-secondary">
            <p className="text-sm font-medium text-foreground">{latestReport.title}</p>
            <div className="mt-3">
              <ScoreMeter label="质量" value={latestReport.qualityScore ?? 0} />
            </div>
          </Link>
        ) : (
          <p className="text-sm text-muted-foreground">暂无报告。</p>
        )}
      </PanelCard>
    </aside>
  )
}

function PanelCard({
  title,
  icon: Icon,
  children
}: {
  title: string
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="mb-4 flex items-center gap-2">
        <Icon className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      </div>
      {children}
    </section>
  )
}
