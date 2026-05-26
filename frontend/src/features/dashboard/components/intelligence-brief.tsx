import { AlertTriangle, ArrowRight, Bot, CheckCircle2, Route } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { DashboardOverview } from "@/types/dashboard"

export function IntelligenceBrief({ brief }: { brief: DashboardOverview["brief"] }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <Badge variant="accent">今日情报简报</Badge>
            <h2 className="mt-3 text-xl font-semibold text-foreground">{brief.title}</h2>
          </div>
          <p className="text-xs text-muted-foreground">{brief.updatedAt ? `更新于 ${formatDateTime(brief.updatedAt)}` : "暂无时间戳"}</p>
        </div>

        <p className="mt-4 text-xs font-semibold uppercase text-muted-foreground">今日摘要</p>
        <p className="mt-2 line-clamp-5 text-sm leading-6 text-muted-foreground">{brief.summary}</p>

        <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_0.9fr]">
          <div>
            <h3 className="text-sm font-semibold text-foreground">关键发现</h3>
            <ul className="mt-3 space-y-2">
              {brief.keyFindings.length ? (
                brief.keyFindings.map((finding) => (
                  <li key={finding} className="flex gap-2 text-sm text-muted-foreground">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                    <span>{finding}</span>
                  </li>
                ))
              ) : (
                <li className="text-sm text-muted-foreground">暂无关键发现。</li>
              )}
            </ul>
          </div>

          <div className="space-y-3">
            <div className="rounded-md border border-border bg-secondary/50 p-3">
              <p className="text-xs uppercase text-muted-foreground">核心判断</p>
              <div className="mt-2 space-y-2">
                {(brief.coreJudgments.length ? brief.coreJudgments : [brief.mainTrend ?? "等待跨板块判断。"]).map((judgment) => (
                  <p key={judgment} className="text-sm leading-5 text-foreground">
                    {judgment}
                  </p>
                ))}
              </div>
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
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Route className="h-4 w-4 text-accent" />
            推荐阅读路径
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {brief.readingPath.length ? (
              brief.readingPath.map((item) => (
                <Button key={item.id} asChild variant="outline" size="sm">
                  <Link href={item.href}>
                    {item.label}
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              ))
            ) : (
              <span className="text-sm text-muted-foreground">暂无推荐阅读路径。</span>
            )}
          </div>
        </div>

        <div className="mt-5 rounded-md border border-border bg-secondary/30 p-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Bot className="h-4 w-4 text-accent" />
            Agent notes
          </h3>
          <div className="mt-2 space-y-1 text-sm leading-6 text-muted-foreground">
            {brief.agentNotes.length ? (
              brief.agentNotes.slice(0, 4).map((note) => <p key={note}>{note}</p>)
            ) : (
              <p>暂无 Agent 备注。</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function formatDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
