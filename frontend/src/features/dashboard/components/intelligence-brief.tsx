import { ArrowRight, AlertTriangle, CheckCircle2 } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { formatDateTime } from "@/lib/format"
import type { DashboardOverview } from "@/types/dashboard"

export function IntelligenceBrief({ brief }: { brief: DashboardOverview["brief"] }) {
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <Badge tone="accent">今日情报简报</Badge>
          <h2 className="mt-3 text-xl font-semibold text-foreground">{brief.title}</h2>
        </div>
        <p className="text-xs text-muted-foreground">更新于 {formatDateTime(brief.updatedAt)}</p>
      </div>

      <p className="mt-4 line-clamp-5 text-sm leading-6 text-muted-foreground">{brief.summary}</p>

      <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_0.9fr]">
        <div>
          <h3 className="text-sm font-semibold text-foreground">关键发现</h3>
          <ul className="mt-3 space-y-2">
            {brief.keyFindings.map((finding) => (
              <li key={finding} className="flex gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                <span>{finding}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-3">
          <div className="rounded-md border border-border bg-secondary/50 p-3">
            <p className="text-xs uppercase text-muted-foreground">主要趋势</p>
            <p className="mt-1 text-sm text-foreground">{brief.mainTrend}</p>
          </div>
          {brief.riskNote ? (
            <div className="rounded-md border border-warning/30 bg-warning/10 p-3">
              <div className="flex gap-2 text-sm text-warning">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{brief.riskNote}</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-5">
        {brief.reportId ? (
          <Link
            href={`/reports/${brief.reportId}`}
            className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary"
          >
            打开最新报告
            <ArrowRight className="h-4 w-4" />
          </Link>
        ) : (
          <span className="text-sm text-muted-foreground">尚未关联报告。</span>
        )}
      </div>
    </section>
  )
}
