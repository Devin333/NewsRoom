import { ArrowDown, ArrowRight, ArrowUp, Minus } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import type { Topic } from "@/types/topic"

const trendIcon = {
  rising: ArrowUp,
  stable: Minus,
  falling: ArrowDown
}

export function TrendingTopicsPreview({ topics }: { topics: Topic[] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">趋势主题</h2>
        <Link href="/topics" className="text-sm text-accent hover:text-foreground">
          浏览主题
        </Link>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {topics.slice(0, 5).map((topic) => {
          const TrendIcon = trendIcon[topic.trend]
          return (
            <Link
              key={topic.id}
              href={`/topics/${topic.id}`}
              className="rounded-lg border border-border bg-card p-4 transition hover:border-accent/50 hover:bg-secondary/35"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-foreground">{topic.name}</h3>
                  <p className="mt-2 line-clamp-2 text-sm leading-5 text-muted-foreground">{topic.summary}</p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Badge tone={topic.trend === "rising" ? "success" : topic.trend === "falling" ? "danger" : "neutral"} className="gap-1">
                  <TrendIcon className="h-3 w-3" />
                  {topic.trend === "rising" ? "上升" : topic.trend === "falling" ? "下降" : "稳定"}
                </Badge>
                <HeatScoreBadge value={topic.heatScore} />
                <Badge tone="neutral">{topic.itemCount} 条目</Badge>
                <Badge tone="neutral">{topic.sourceCount} 来源</Badge>
              </div>
            </Link>
          )
        })}
      </div>
    </section>
  )
}
