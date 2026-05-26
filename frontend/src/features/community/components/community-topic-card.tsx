import type { ReactNode } from "react"
import { ExternalLink, Flame, GitBranch, MessageSquare, RadioTower } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { CommunitySentimentBadge } from "@/features/community/components/community-sentiment-badge"
import { communitySourceLabel } from "@/lib/community/community-filters"
import { formatDateTime } from "@/lib/format"
import type { CommunityTopic } from "@/types/community"

export function CommunityTopicCard({ topic }: { topic: CommunityTopic }) {
  return (
    <Card className="transition hover:bg-secondary/25">
      <CardContent className="p-5">
        <article className="grid gap-5 md:grid-cols-[minmax(0,1fr)_9rem]">
          <div className="min-w-0">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <Link href={`/community/topics/${topic.slug}`} className="min-w-0">
                <h3 className="text-xl font-semibold leading-tight text-foreground hover:text-primary">{topic.title}</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {topic.sourceName ?? communitySourceLabel(topic.sourceType)}
                  {topic.lastActivityAt ? ` | ${formatDateTime(topic.lastActivityAt)}` : null}
                </p>
              </Link>
              <CommunitySentimentBadge sentiment={topic.sentiment} />
            </div>

            <p className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">{topic.summary}</p>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Badge tone="accent">{communitySourceLabel(topic.sourceType)}</Badge>
              {topic.tags.slice(0, 5).map((tag) => (
                <Badge key={tag} tone="neutral">
                  {tag}
                </Badge>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {topic.relatedPapers?.slice(0, 2).map((paper) => (
                <RelationBadge key={paper.id} label={paper.title} url={paper.url} />
              ))}
              {topic.relatedProjects?.slice(0, 2).map((project) => (
                <RelationBadge key={project.id} label={project.name} url={project.url} />
              ))}
              {topic.relatedNews?.slice(0, 2).map((news) => (
                <RelationBadge key={news.id} label={news.title} url={news.url} />
              ))}
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <Button asChild variant="outline" size="sm">
                <Link href={`/community/topics/${topic.slug}`}>View topic</Link>
              </Button>
              {topic.sourceUrl ? (
                <Button asChild variant="ghost" size="sm">
                  <a href={topic.sourceUrl} target="_blank" rel="noreferrer">
                    <ExternalLink className="size-4" />
                    Open source
                  </a>
                </Button>
              ) : null}
            </div>
          </div>

          <aside className="grid grid-cols-2 gap-3 border-t border-border pt-4 md:block md:space-y-4 md:border-l md:border-t-0 md:pl-5 md:pt-0">
            <Metric icon={<Flame className="size-4" />} label="Heat" value={topic.heatScore} />
            <Metric icon={<GitBranch className="size-4" />} label="Controversy" value={topic.controversyScore} />
            <Metric icon={<RadioTower className="size-4" />} label="Adoption" value={topic.adoptionScore} />
            {topic.commentCount !== undefined ? (
              <Metric icon={<MessageSquare className="size-4" />} label="Comments" value={topic.commentCount} />
            ) : null}
          </aside>
        </article>
      </CardContent>
    </Card>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value?: number }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-center gap-2 text-foreground md:justify-start">
        <span className="text-muted-foreground">{icon}</span>
        <span className="font-mono text-lg font-semibold">{value === undefined ? "n/a" : Math.round(value)}</span>
      </div>
      <p className="mt-1 text-center font-mono text-[10px] uppercase tracking-normal text-muted-foreground md:text-left">{label}</p>
    </div>
  )
}

function RelationBadge({ label, url }: { label: string; url?: string }) {
  if (url) {
    return (
      <a href={url} target="_blank" rel="noreferrer">
        <Badge tone="info">{label}</Badge>
      </a>
    )
  }
  return <Badge tone="info">{label}</Badge>
}
