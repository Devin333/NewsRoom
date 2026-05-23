import Link from "next/link";
import { HeatScoreBadge, QualityBadge, TrendBadge } from "@/components/common/badges";
import { formatDate } from "@/lib/format";
import type { Topic } from "@/types/topic";

export function TopicCard({ topic, dense = false }: { topic: Topic; dense?: boolean }) {
  return (
    <Link href={`/topics/${topic.id}`} className="block rounded-md border border-border bg-card p-4 shadow-sm transition hover:border-primary/50 hover:bg-secondary/35">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">{topic.name}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{topic.category ?? "未分类"}</p>
        </div>
        <TrendBadge trend={topic.trend} />
      </div>
      {!dense ? <p className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">{topic.summary}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <HeatScoreBadge score={topic.heatScore} />
        <QualityBadge score={topic.qualityScore ?? 0} />
        <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">{topic.itemCount} 条新闻</span>
        <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">{topic.sourceCount} 个来源</span>
      </div>
      <div className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <span>首次出现 {formatDate(topic.firstSeenAt)}</span>
        <span>更新于 {formatDate(topic.lastSeenAt)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {(topic.entities ?? []).slice(0, 4).map((entity) => (
          <span key={entity} className="rounded-md border border-border bg-secondary/60 px-2 py-1 text-xs text-muted-foreground">
            {entity}
          </span>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {(topic.tags ?? []).map((tag) => (
          <span key={tag} className="text-xs text-primary">
            #{tag}
          </span>
        ))}
      </div>
    </Link>
  );
}
