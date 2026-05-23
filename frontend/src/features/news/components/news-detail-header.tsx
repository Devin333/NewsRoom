import { ExternalLink } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { StatusBadge } from "@/components/common/status-badge"
import { formatDateTime } from "@/lib/format"
import type { NewsItem } from "@/types/news"

export function NewsDetailHeader({ news }: { news: NewsItem }) {
  return (
    <header className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <SourceBadge name={news.sourceName} type={news.sourceType} />
            <Badge tone="neutral">{news.category}</Badge>
            <StatusBadge status={news.status ?? "analyzed"} />
          </div>
          <h1 className="mt-4 max-w-5xl text-2xl font-semibold tracking-normal text-foreground sm:text-3xl">{news.title}</h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted-foreground">{news.summary}</p>
        </div>
        <a
          href={news.sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex shrink-0 items-center gap-2 rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary"
        >
          打开来源
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <HeatScoreBadge value={news.heatScore} />
        <QualityBadge value={news.qualityScore} />
        <CredibilityBadge value={news.credibility} />
        <span className="text-xs text-muted-foreground">发布于 {formatDateTime(news.publishedAt)}</span>
        <span className="text-xs text-muted-foreground">采集于 {formatDateTime(news.collectedAt)}</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {news.tags.map((tag) => (
          <span key={tag} className="rounded-md bg-secondary px-2 py-1 text-xs text-muted-foreground">
            {tag}
          </span>
        ))}
      </div>

      {news.topicId && news.topicName ? (
        <div className="mt-4 text-sm text-muted-foreground">
          相关主题{" "}
          <Link href={`/topics/${news.topicId}`} className="text-accent hover:text-foreground">
            {news.topicName}
          </Link>
        </div>
      ) : null}
    </header>
  )
}
