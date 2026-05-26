import { ExternalLink } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { StatusBadge } from "@/components/common/status-badge"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { NewsItem } from "@/types/news"

export function NewsCard({ news, compact = false }: { news: NewsItem; compact?: boolean }) {
  return (
    <article
      className={cn(
        "group grid gap-5 border-b border-border py-6 transition hover:bg-secondary/25 md:grid-cols-[minmax(0,1fr)_8rem]",
        compact && "py-4"
      )}
    >
      <div className="min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <Link href={`/news/${news.id}`} className="block">
            <h3 className={cn("font-serif font-semibold leading-tight text-foreground group-hover:text-primary", compact ? "text-lg" : "text-xl")}>
              {news.title}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {news.sourceName} · 发布于 {formatDateTime(news.publishedAt)}
              {news.topicName ? ` · ${news.topicName}` : ""}
            </p>
            <p className={cn("mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground", compact && "line-clamp-2")}>{news.summary}</p>
          </Link>
          <a
            href={news.sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
            aria-label="打开原始来源"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge tone="accent">{news.category}</Badge>
          <SourceBadge name={news.sourceName} type={news.sourceType} />
          <CredibilityBadge value={news.credibility} />
          <StatusBadge status={news.status ?? "analyzed"} />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {news.tags.map((tag) => (
            <span key={tag} className="rounded-sm bg-[#ccfbf1] px-2 py-1 font-mono text-[11px] text-teal-800 dark:bg-teal-400/15 dark:text-teal-200">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <aside className="hidden border-l border-border pl-5 md:block">
        <div className="space-y-5 pt-2 text-center">
          <Metric value={news.heatScore} label="热度" />
          <Metric value={news.qualityScore} label="质量" />
          {typeof news.heatScore === "number" ? <HeatScoreBadge value={news.heatScore} /> : <Badge tone="neutral">热度 N/A</Badge>}
          {typeof news.qualityScore === "number" ? <QualityBadge value={news.qualityScore} /> : <Badge tone="neutral">质量 N/A</Badge>}
        </div>
      </aside>
    </article>
  )
}

function Metric({ value, label }: { value?: number; label: string }) {
  return (
    <div>
      <p className="font-mono text-lg font-semibold text-foreground">{typeof value === "number" ? value : "N/A"}</p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-normal text-muted-foreground">{label}</p>
    </div>
  )
}
