import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PageHeader } from "@/components/layout/page-header"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { ScoreMeter } from "@/components/common/score-meter"
import { SourceBadge } from "@/components/common/source-badge"
import { StatusBadge } from "@/components/common/status-badge"
import { mockDashboard } from "@/lib/api/mock-data"

export function DashboardPageContent() {
  const dashboard = mockDashboard
  const metrics = [
    ["采集", dashboard.metrics.newsCollectedToday, dashboard.metricDeltas?.newsCollectedToday],
    ["去重", dashboard.metrics.deduplicatedItems, "就绪"],
    ["主题", dashboard.metrics.topicsUpdatedToday, "已更新"],
    ["报告", dashboard.metrics.reportsGeneratedToday, "已生成"],
    ["数据源", `${dashboard.metrics.sourceSuccessRate}%`, "成功率"],
    ["质量", dashboard.metrics.avgQualityScore, dashboard.metricDeltas?.avgQualityScore]
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="NewsRoom 情报后台"
        title="仪表盘"
        description="面向 AI 技术情报、证据质量、数据源健康和智能体运行的 mock 优先总览。"
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {metrics.map(([label, value, note]) => (
          <Card key={label}>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-2 text-2xl font-semibold">{value}</p>
              <p className="mt-1 text-xs text-accent">{note}</p>
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <Card>
          <CardHeader>
            <CardTitle>{dashboard.brief.title}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm leading-6 text-muted-foreground">{dashboard.brief.summary}</p>
            <div className="grid gap-3 md:grid-cols-3">
              {dashboard.brief.keyFindings.map((finding) => (
                <div key={finding} className="rounded-md border border-border bg-secondary/60 p-3 text-sm">
                  {finding}
                </div>
              ))}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {dashboard.topStories.map((story) => (
                <div key={story.id} className="rounded-lg border border-border bg-background/60 p-4">
                  <div className="mb-3 flex flex-wrap gap-2">
                    <SourceBadge type={story.sourceType} />
                    <HeatScoreBadge score={story.heatScore} />
                    <QualityBadge score={story.qualityScore} />
                  </div>
                  <h2 className="text-base font-semibold">{story.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{story.summary}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>最近智能体运行</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {dashboard.latestRun ? (
                <>
                  <div className="flex items-center justify-between gap-3">
                    <p className="truncate text-sm font-medium">{dashboard.latestRun.workflowName}</p>
                    <StatusBadge status={dashboard.latestRun.status} />
                  </div>
                  {(dashboard.latestRun.steps ?? []).map((step) => (
                    <div key={step.id} className="flex items-center justify-between gap-3 rounded-md bg-secondary/60 px-3 py-2 text-sm">
                      <span>{step.label}</span>
                      <StatusBadge status={step.status} />
                    </div>
                  ))}
                </>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>质量门控</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <StatusBadge status={dashboard.qualityGate.status} />
              <ScoreMeter value={dashboard.qualityGate.passedChecks} max={dashboard.qualityGate.totalChecks} label="通过检查" />
              <p className="text-sm leading-6 text-muted-foreground">{dashboard.qualityGate.summary}</p>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  )
}
