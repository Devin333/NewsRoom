import { communitySourceLabel, communityTopicLabel } from "@/lib/community/community-filters"
import type { CommunityFilterOptions, CommunityListParams, CommunitySourceType, CommunityTopicKey } from "@/types/community"

export function CommunitySourceList({
  options,
  filters,
  onChange
}: {
  options: CommunityFilterOptions
  filters: CommunityListParams
  onChange: (patch: Partial<CommunityListParams>) => void
}) {
  return (
    <aside className="hidden space-y-8 xl:block">
      <SourceBlock
        title="来源"
        items={options.sources}
        active={filters.source}
        label={(value) => communitySourceLabel(value)}
        onSelect={(source) => onChange({ source: filters.source === source ? undefined : source })}
      />
      <SourceBlock
        title="话题"
        items={options.topics}
        active={filters.topic}
        label={(value) => communityTopicLabel(value)}
        onSelect={(topic) => onChange({ topic: filters.topic === topic ? undefined : topic })}
      />
    </aside>
  )
}

function SourceBlock<T extends CommunitySourceType | CommunityTopicKey>({
  title,
  items,
  active,
  label,
  onSelect
}: {
  title: string
  items: Array<{ count: number } & Record<string, T | number | string>>
  active?: T
  label: (value: T) => string
  onSelect: (value: T) => void
}) {
  return (
    <section className="space-y-3">
      <h2 className="font-mono text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">{title}</h2>
      <div className="space-y-2">
        {items.map((item) => {
          const value = ("sourceType" in item ? item.sourceType : item.topic) as T
          return (
            <button
              key={value}
              type="button"
              onClick={() => onSelect(value)}
              className={
                active === value
                  ? "flex w-full items-baseline justify-between gap-3 text-left text-sm font-medium text-foreground"
                  : "flex w-full items-baseline justify-between gap-3 text-left text-sm text-muted-foreground hover:text-foreground"
              }
            >
              <span className="truncate">{label(value)}</span>
              <span className="font-mono text-[11px]">{item.count}</span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
