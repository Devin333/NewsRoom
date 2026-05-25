import { BarChart3, FileText, Lightbulb, ListChecks } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { StudioBoardOutputViewModel } from "@/types/board"

const qualityVariant = {
  ready: "success",
  partial: "warning",
  fallback: "muted"
} as const

export function BoardOutputPanel({ output }: { output: StudioBoardOutputViewModel }) {
  return (
    <section className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <MetricTile label="Cards" value={output.stats.cardCount} />
        <MetricTile label="Insights" value={output.stats.insightCount} />
        <MetricTile label="Relations" value={output.stats.relationCount} />
        <MetricTile label="Quality" value={output.quality.score ?? output.quality.status} />
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Quality summary</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{output.quality.label}</p>
          </div>
          <Badge variant={qualityVariant[output.quality.status]}>{output.quality.source}</Badge>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {output.quality.checks.map((check) => (
              <Badge key={check} variant="muted">
                {check}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.9fr)]">
        <Card>
          <CardHeader className="flex-row items-center gap-3">
            <ListChecks className="size-5 text-accent" />
            <CardTitle>Cards</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {output.cards.length ? (
              output.cards.map((card) => (
                <article key={card.id} className="rounded-md border border-border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-foreground">{card.title}</h3>
                      {card.subtitle ? <p className="mt-1 text-xs text-muted-foreground">{card.subtitle}</p> : null}
                    </div>
                    {card.score !== undefined ? <Badge variant="accent">score {card.score}</Badge> : null}
                  </div>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{card.summary}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {card.badges.slice(0, 5).map((badge) => (
                      <Badge key={`${card.id}-${badge.label}-${badge.value ?? ""}`} variant="muted">
                        {badge.label}
                        {badge.value ? ` ${badge.value}` : ""}
                      </Badge>
                    ))}
                  </div>
                  {card.rankingReason ? (
                    <p className="mt-3 text-xs leading-5 text-muted-foreground">{card.rankingReason}</p>
                  ) : null}
                </article>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No board cards returned for this output.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center gap-3">
            <Lightbulb className="size-5 text-accent" />
            <CardTitle>Insights</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {output.insights.length ? (
              output.insights.map((insight) => (
                <article key={insight.id} className="rounded-md border border-border p-4">
                  <h3 className="text-sm font-semibold text-foreground">{insight.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{insight.summary}</p>
                  {insight.insightType ? (
                    <Badge className="mt-3" variant="muted">
                      {insight.insightType}
                    </Badge>
                  ) : null}
                </article>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No board insights returned for this output.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center gap-3">
            <FileText className="size-5 text-accent" />
            <CardTitle>Detail pages</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {output.detailPages.map((page) => (
              <div key={page.id} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium text-foreground">{page.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{page.summary}</p>
                <p className="mt-2 text-xs text-muted-foreground">{page.sectionCount} sections</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center gap-3">
            <BarChart3 className="size-5 text-accent" />
            <CardTitle>Sections</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {output.sections.map((section) => (
              <div key={section.title} className="rounded-md border border-border p-3">
                <p className="text-sm font-medium text-foreground">{section.title}</p>
                {section.content ? <p className="mt-1 text-sm text-muted-foreground">{section.content}</p> : null}
                <p className="mt-2 text-xs text-muted-foreground">
                  {section.cardCount} cards, {section.insightCount} insights, {section.metricCount} metrics
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

function MetricTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <p className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
    </div>
  )
}
