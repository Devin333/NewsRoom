import { ExternalTextLink, MaturityBadge, TechTypeBadge } from "@/components/common/badges";
import { cn } from "@/lib/format";
import type { TechItem } from "@/types/tech";

export function TechItemCard({ item, compact = false }: { item: TechItem; compact?: boolean }) {
  return (
    <article className={cn("rounded-lg border border-border bg-card p-4", compact && "bg-background/50")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{item.name}</h3>
          {item.problem && !compact ? <p className="mt-1 text-xs text-muted-foreground">问题：{item.problem}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <TechTypeBadge type={item.type} />
          <MaturityBadge maturity={item.maturity} />
        </div>
      </div>
      <p className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">{item.summary}</p>
      {!compact ? (
        <div className="mt-3 grid gap-2 text-xs text-muted-foreground">
          {item.agentEvaluation ? <p>智能体评估：{item.agentEvaluation}</p> : null}
          {item.referenceValue ? <p>引用价值：{item.referenceValue}</p> : null}
        </div>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-1">
        {item.tags.map((tag) => (
          <span key={tag} className="rounded bg-secondary px-2 py-1 text-xs text-muted-foreground">
            #{tag}
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {item.relatedTopicNames?.map((topic) => (
            <span key={topic} className="text-xs text-primary">
              {topic}
            </span>
          ))}
        </div>
        <ExternalTextLink href={item.sourceUrl}>来源</ExternalTextLink>
      </div>
    </article>
  );
}
