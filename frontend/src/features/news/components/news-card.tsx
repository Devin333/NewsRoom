import { ExternalLink } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { SourceBadge } from "@/components/common/source-badge"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { NewsItem } from "@/types/news"

export function NewsCard({ news, compact = false }: { news: NewsItem; compact?: boolean }) {
  return (
    <article
      className={cn(
        "group grid gap-5 border-b border-[#d7dfd8] py-6 transition hover:bg-white/55 md:grid-cols-[minmax(0,1fr)_9rem] dark:border-border dark:hover:bg-secondary/20",
        compact && "py-4"
      )}
    >
      <div className="min-w-0">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <Link href={`/news/${news.id}`} className="block min-w-0">
            <h3 className={cn("font-semibold leading-tight text-[#334155] group-hover:text-emerald-700 dark:text-foreground", compact ? "text-lg" : "text-xl")}>
              {news.title}
            </h3>
            <p className="mt-2 text-xs text-[#334155]/55 dark:text-muted-foreground">
              {news.sourceName} · Published {formatDateTime(news.publishedAt)}
              {news.topicName ? ` · ${news.topicName}` : ""}
            </p>
            <p className={cn("mt-3 line-clamp-3 text-sm leading-6 text-[#334155]/68 dark:text-muted-foreground", compact && "line-clamp-2")}>
              {news.summary}
            </p>
          </Link>
          <a
            href={news.sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[#dbe3dc] bg-white text-[#334155]/60 hover:bg-[#f7f9f6] hover:text-[#334155] dark:border-border dark:bg-card dark:text-muted-foreground"
            aria-label="Open original source"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge tone="accent">{news.category}</Badge>
          <SourceBadge name={news.sourceName} type={news.sourceType} />
          <CredibilityBadge value={news.credibility} />
          <RelationBadge label="papers" value={news.relatedPapers?.length ?? 0} />
          <RelationBadge label="projects" value={news.relatedProjects?.length ?? 0} />
          <RelationBadge label="community" value={news.relatedCommunityTopics?.length ?? 0} />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {news.tags.slice(0, compact ? 4 : 8).map((tag) => (
            <span key={tag} className="rounded-sm bg-[#ccfbf1] px-2 py-1 font-mono text-[11px] text-teal-800 dark:bg-teal-400/15 dark:text-teal-200">
              {tag}
            </span>
          ))}
        </div>
      </div>

      <aside className="hidden border-l border-[#d7dfd8] pl-5 md:block dark:border-border">
        <div className="space-y-4 pt-2 text-center">
          <Metric value={news.heatScore} label="heat" />
          <Metric value={news.qualityScore} label="quality" />
          {typeof news.heatScore === "number" ? <HeatScoreBadge value={news.heatScore} /> : <Badge tone="neutral">Heat N/A</Badge>}
          {typeof news.qualityScore === "number" ? <QualityBadge value={news.qualityScore} /> : <Badge tone="neutral">Quality N/A</Badge>}
        </div>
      </aside>
    </article>
  )
}

function RelationBadge({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-sm border border-[#dbe3dc] bg-white px-2 py-1 font-mono text-[11px] text-[#334155]/60 dark:border-border dark:bg-card dark:text-muted-foreground">
      {value} {label}
    </span>
  )
}

function Metric({ value, label }: { value?: number; label: string }) {
  return (
    <div>
      <p className="font-mono text-lg font-semibold text-[#334155] dark:text-foreground">{typeof value === "number" ? value : "N/A"}</p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-normal text-[#334155]/55 dark:text-muted-foreground">{label}</p>
    </div>
  )
}
