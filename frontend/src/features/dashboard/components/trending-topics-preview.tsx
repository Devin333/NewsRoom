import { ArrowDown, ArrowRight, ArrowUp, Minus } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { TrendingTopic } from "@/types/dashboard"

const trendIcon = {
  rising: ArrowUp,
  stable: Minus,
  falling: ArrowDown
}

const trendVariant = {
  rising: "success",
  stable: "muted",
  falling: "warning"
} as const

const trendLabels: Record<TrendingTopic["trend"], string> = {
  rising: "升温",
  stable: "稳定",
  falling: "回落"
}

const boardLabels: Record<TrendingTopic["boards"][number], string> = {
  cross_board: "跨板块",
  news: "AI 新闻",
  paper: "论文",
  project: "项目",
  community: "社区"
}

export function TrendingTopicsPreview({ topics }: { topics: TrendingTopic[] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">趋势主题</h2>
        <Link href="/topics" className="text-sm text-accent hover:text-foreground">
          浏览主题
        </Link>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {topics.slice(0, 6).map((topic) => {
          const TrendIcon = trendIcon[topic.trend]
          const content = (
            <Card className="h-full p-4 transition hover:border-accent/50 hover:bg-secondary/35">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-foreground">{topic.name}</h3>
                  <p className="mt-2 line-clamp-2 text-sm leading-5 text-muted-foreground">{topic.summary}</p>
                </div>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Badge variant={trendVariant[topic.trend]} className="gap-1">
                  <TrendIcon className="h-3 w-3" />
                  {trendLabels[topic.trend]}
                </Badge>
                {topic.heatScore !== undefined ? <Badge variant="accent">热度 {topic.heatScore}</Badge> : null}
                {topic.signalCount !== undefined ? <Badge variant="default">{topic.signalCount} 个信号</Badge> : null}
                {topic.boards.slice(0, 3).map((board) => (
                  <Badge key={board} variant="muted">
                    {boardLabels[board] ?? board}
                  </Badge>
                ))}
              </div>
            </Card>
          )
          return topic.href ? (
            <Link key={topic.id} href={topic.href} className="block">
              {content}
            </Link>
          ) : (
            <div key={topic.id}>{content}</div>
          )
        })}
      </div>
    </section>
  )
}
