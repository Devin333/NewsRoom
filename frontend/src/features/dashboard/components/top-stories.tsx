import { ArrowRight } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import type { TopStory } from "@/types/dashboard"

const boardLabels: Record<TopStory["board"], string> = {
  news: "AI 新闻",
  paper: "论文雷达",
  project: "项目雷达",
  community: "社区脉搏"
}

export function TopStories({ stories }: { stories: TopStory[] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">跨板块重点线索</h2>
        <Button asChild variant="ghost" size="sm">
          <Link href="/news">
            查看新闻
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
      <div className="grid gap-3">
        {stories.map((story) => (
          <Card key={story.id} className="p-4 transition hover:border-accent/50 hover:bg-secondary/35">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="accent">{boardLabels[story.board]}</Badge>
                  {story.score !== undefined ? <Badge variant="muted">热度 {story.score}</Badge> : null}
                  {story.confidence !== undefined ? <Badge variant="success">置信度 {story.confidence}%</Badge> : null}
                  {story.publishedAt ? <Badge variant="muted">{formatDate(story.publishedAt)}</Badge> : null}
                </div>
                <h3 className="mt-3 text-base font-semibold leading-6 text-foreground">{story.title}</h3>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">{story.summary}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {story.sourceName ? <span className="truncate">来源：{story.sourceName}</span> : null}
                  {story.reason ? <span className="line-clamp-1">推荐原因：{story.reason}</span> : null}
                </div>
                {story.tags?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {story.tags.slice(0, 4).map((tag) => (
                      <Badge key={tag} variant="default">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
              <Button asChild variant="outline" size="sm" className="shrink-0">
                <Link href={story.href} aria-label={`打开 ${story.title}`}>
                  继续阅读
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </section>
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric"
  }).format(date)
}
