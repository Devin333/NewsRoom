"use client"

import { Filter, Search } from "lucide-react"
import { NewsViewModeToggle } from "@/features/news/components/news-view-mode-toggle"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { NewsFilters, NewsViewMode } from "@/types/news"

export function NewsToolbar({
  filters,
  onChange,
  onToggleFilters
}: {
  filters: NewsFilters
  onChange: (patch: Partial<NewsFilters>) => void
  onToggleFilters: () => void
}) {
  const { locale, t } = useI18n()

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3 lg:flex-row lg:items-center">
      <label className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
        <Search className="h-4 w-4 shrink-0" />
        <input
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ keyword: event.target.value })}
          placeholder={locale === "zh" ? "搜索新闻、主题、来源、标签" : "Search news, topics, sources, tags"}
          className="min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={filters.sort ?? "publishedAt"}
          onChange={(event) => onChange({ sort: event.target.value as NewsFilters["sort"] })}
          className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none"
        >
          <option value="publishedAt">{locale === "zh" ? "发布时间" : "Published time"}</option>
          <option value="collectedAt">{locale === "zh" ? "采集时间" : "Collected time"}</option>
          <option value="heatScore">{locale === "zh" ? "热度" : "Heat"}</option>
          <option value="qualityScore">{locale === "zh" ? "质量分" : "Quality score"}</option>
        </select>

        <NewsViewModeToggle value={(filters.viewMode ?? "card") as NewsViewMode} onChange={(viewMode) => onChange({ viewMode })} />

        <button
          type="button"
          onClick={onToggleFilters}
          className="inline-flex h-10 items-center gap-2 rounded-md border border-border px-3 text-sm text-foreground hover:bg-secondary lg:hidden"
        >
          <Filter className="h-4 w-4" />
          {t("common.filters")}
        </button>
      </div>
    </div>
  )
}
