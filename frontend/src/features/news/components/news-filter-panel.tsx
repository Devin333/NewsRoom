import type { NewsFilterOptions, NewsFilters } from "@/types/news"

export function NewsFilterPanel({
  filters,
  options,
  onChange,
}: {
  filters: NewsFilters
  options: NewsFilterOptions
  onChange: (patch: Partial<NewsFilters>) => void
}) {
  return (
    <aside className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-foreground">筛选</h2>
        <button
          type="button"
          onClick={() =>
            onChange({
              dateRange: undefined,
              category: undefined,
              sourceType: undefined,
              topic: undefined,
              credibility: undefined,
              qualityStatus: undefined,
              topicStatus: "all",
              reportStatus: "all",
            })
          }
          className="text-xs text-accent hover:text-foreground"
        >
          重置
        </button>
      </div>

      <div className="mt-4 space-y-5">
        <SelectBlock
          label="日期"
          value={filters.dateRange ?? ""}
          onChange={(value) => onChange({ dateRange: value ? (value as NewsFilters["dateRange"]) : undefined })}
          options={[
            ["", "任意时间"],
            ["today", "今天"],
            ["week", "本周"],
            ["month", "本月"],
          ]}
        />

        <TextBlock
          label="主题"
          value={filters.topic ?? ""}
          placeholder="agents、models、safety..."
          onChange={(topic) => onChange({ topic: topic || undefined })}
        />

        <CheckboxBlock
          label="分类"
          values={options.categories}
          selected={filters.category ?? []}
          onToggle={(category) => onChange({ category: toggle(filters.category, category) })}
        />

        <CheckboxBlock
          label="来源"
          values={options.sourceTypes}
          selected={filters.sourceType ?? []}
          onToggle={(sourceType) => onChange({ sourceType: toggle(filters.sourceType, sourceType) })}
          formatValue={sourceTypeLabelValue}
        />

        <CheckboxBlock
          label="可信度"
          values={options.credibility}
          selected={filters.credibility ?? []}
          onToggle={(credibility) => onChange({ credibility: toggle(filters.credibility, credibility) })}
          formatValue={credibilityLabelValue}
        />

        <CheckboxBlock
          label="质量"
          values={options.qualityStatuses}
          selected={filters.qualityStatus ?? []}
          onToggle={(qualityStatus) => onChange({ qualityStatus: toggle(filters.qualityStatus, qualityStatus) })}
          formatValue={qualityLabelValue}
        />

        <SelectBlock
          label="主题状态"
          value={filters.topicStatus ?? "all"}
          onChange={(value) => onChange({ topicStatus: value as NewsFilters["topicStatus"] })}
          options={[
            ["all", "全部"],
            ["clustered", "已聚类"],
            ["unclustered", "未聚类"],
          ]}
        />

        <SelectBlock
          label="报告状态"
          value={filters.reportStatus ?? "all"}
          onChange={(value) => onChange({ reportStatus: value as NewsFilters["reportStatus"] })}
          options={[
            ["all", "全部"],
            ["included", "已纳入"],
            ["not_included", "未纳入"],
          ]}
        />
      </div>
    </aside>
  )
}

function CheckboxBlock<T extends string>({
  label,
  values,
  selected,
  onToggle,
  formatValue = labelValue,
}: {
  label: string
  values: T[]
  selected: T[]
  onToggle: (value: T) => void
  formatValue?: (value: T) => string
}) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">{label}</p>
      <div className="space-y-2">
        {values.map((value) => (
          <label key={value} className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={selected.includes(value)}
              onChange={() => onToggle(value)}
              className="h-4 w-4 rounded border-border bg-background accent-[hsl(var(--accent))]"
            />
            <span>{formatValue(value)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function SelectBlock({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium uppercase text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none"
      >
        {options.map(([optionValue, labelText]) => (
          <option key={optionValue} value={optionValue}>
            {labelText}
          </option>
        ))}
      </select>
    </label>
  )
}

function TextBlock({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium uppercase text-muted-foreground">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none placeholder:text-muted-foreground"
      />
    </label>
  )
}

function toggle<T extends string>(values: T[] | undefined, value: T) {
  const set = new Set(values ?? [])
  if (set.has(value)) {
    set.delete(value)
  } else {
    set.add(value)
  }
  return [...set]
}

function labelValue(value: string) {
  return categoryLabelValue(value)
}

function credibilityLabelValue(value: string) {
  const labels: Record<string, string> = {
    high: "高",
    medium: "中",
    low: "低",
  }
  return labels[value] ?? value
}

function qualityLabelValue(value: string) {
  const labels: Record<string, string> = {
    passed: "通过",
    review: "复核",
    failed: "失败",
  }
  return labels[value] ?? value
}

function sourceTypeLabelValue(value: string) {
  const labels: Record<string, string> = {
    official_blog: "官方博客",
    rss: "RSS",
    atom: "Atom",
    github: "GitHub",
    hackernews: "Hacker News",
    reddit: "Reddit",
    arxiv: "arXiv",
    lobsters: "Lobsters",
    stackoverflow: "Stack Overflow",
    devto: "dev.to",
    medium: "Medium",
    html: "HTML",
    web_page: "网页",
    media: "媒体",
    manual: "手动",
    custom: "自定义",
  }
  return labels[value] ?? value
}

function categoryLabelValue(value: string) {
  return value
}
