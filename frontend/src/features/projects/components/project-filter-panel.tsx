import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { ProjectFilterOption, ProjectListOptions, ProjectListParams } from "@/types/projects"

export function ProjectFilterPanel({
  filters,
  options,
  onChange,
}: {
  filters: ProjectListParams
  options: ProjectListOptions
  onChange: (patch: Partial<ProjectListParams>) => void
}) {
  return (
    <aside className="space-y-6">
      <FilterGroup
        title="分类"
        activeValue={filters.category}
        options={options.categories}
        onSelect={(category) => onChange({ category: category as ProjectListParams["category"], page: 1 })}
        onClear={() => onChange({ category: undefined, page: 1 })}
      />
      <FilterGroup
        title="来源"
        activeValue={filters.source}
        options={options.sources}
        onSelect={(source) => onChange({ source: source as ProjectListParams["source"], page: 1 })}
        onClear={() => onChange({ source: undefined, page: 1 })}
      />
      <FilterGroup
        title="语言"
        activeValue={filters.language}
        options={options.languages}
        onSelect={(language) => onChange({ language: language as ProjectListParams["language"], page: 1 })}
        onClear={() => onChange({ language: undefined, page: 1 })}
      />
    </aside>
  )
}

function FilterGroup({
  title,
  activeValue,
  options,
  onSelect,
  onClear,
}: {
  title: string
  activeValue?: string
  options: ProjectFilterOption[]
  onSelect: (value: string) => void
  onClear: () => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-mono text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">{title}</h2>
        {activeValue ? (
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2" onClick={onClear}>
            清除
          </Button>
        ) : null}
      </div>
      {options.length ? (
        <div className="space-y-2">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onSelect(option.value)}
              className={
                activeValue === option.value
                  ? "flex w-full items-center justify-between gap-2 rounded-md bg-foreground px-3 py-2 text-left text-sm text-background"
                  : "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
              }
            >
              <span className="truncate">{option.label}</span>
              <Badge variant={activeValue === option.value ? "muted" : "default"}>{option.count}</Badge>
            </button>
          ))}
        </div>
      ) : (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-xs leading-5 text-muted-foreground">暂无可用选项</p>
      )}
    </section>
  )
}
