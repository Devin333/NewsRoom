import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { titleCase } from "@/lib/format"
import type { MemoryHit } from "@/types/agent"

export function MemoryHitList({ hits }: { hits: MemoryHit[] }) {
  if (!hits.length) return <EmptyState title="暂无记忆命中" description="这次运行的记忆召回没有返回上下文。" />

  return (
    <div className="space-y-3">
      {hits.map((hit) => (
        <article key={hit.id} className="rounded-md border border-border bg-secondary/35 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              <Badge tone="accent">{titleCase(hit.memoryType)}</Badge>
              <Badge tone="neutral">{hit.memoryId}</Badge>
            </div>
            <span className="text-xs text-muted-foreground">{hit.score}% 匹配</span>
          </div>
          <p className="mt-3 text-sm leading-6 text-foreground">{hit.summary}</p>
          {hit.relatedTopicName ? <p className="mt-2 text-xs text-muted-foreground">主题：{hit.relatedTopicName}</p> : null}
        </article>
      ))}
    </div>
  )
}
