"use client"

import { Filter, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { NewsViewModeToggle } from "@/features/news/components/news-view-mode-toggle"
import type { NewsFilterOptions, NewsFilters, NewsViewMode } from "@/types/news"

export function NewsToolbar({
  filters,
  options,
  onChange,
  onToggleFilters,
}: {
  filters: NewsFilters
  options: NewsFilterOptions
  onChange: (patch: Partial<NewsFilters>) => void
  onToggleFilters: () => void
}) {
  return (
    <div className="grid gap-3 rounded-md border border-[#dbe3dc] bg-white/85 p-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center dark:border-border dark:bg-card">
      <label className="flex min-w-0 items-center gap-2 rounded-md border border-[#dbe3dc] bg-[#f7f9f6] px-3 py-2 text-sm text-[#334155]/60 dark:border-border dark:bg-background dark:text-muted-foreground">
        <Search className="h-4 w-4 shrink-0" />
        <input
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ keyword: event.target.value })}
          placeholder="Search news, topics, sources, tags"
          className="min-w-0 flex-1 bg-transparent text-[#334155] outline-none placeholder:text-[#334155]/45 dark:text-foreground dark:placeholder:text-muted-foreground"
        />
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={filters.sourceType?.[0] ?? ""}
          onChange={(event) => onChange({ sourceType: event.target.value ? [event.target.value as NonNullable<NewsFilters["sourceType"]>[number]] : undefined })}
          className="h-10 rounded-md border border-[#dbe3dc] bg-white px-3 text-sm text-[#334155] outline-none dark:border-border dark:bg-background dark:text-foreground"
          aria-label="Source type"
        >
          <option value="">All sources</option>
          {options.sourceTypes.map((sourceType) => (
            <option key={sourceType} value={sourceType}>
              {sourceTypeLabel(sourceType)}
            </option>
          ))}
        </select>

        <select
          value={filters.sort ?? "publishedAt"}
          onChange={(event) => onChange({ sort: event.target.value as NewsFilters["sort"] })}
          className="h-10 rounded-md border border-[#dbe3dc] bg-white px-3 text-sm text-[#334155] outline-none dark:border-border dark:bg-background dark:text-foreground"
          aria-label="Sort"
        >
          <option value="heatScore">Top</option>
          <option value="publishedAt">Newest</option>
          <option value="collectedAt">Recently collected</option>
          <option value="qualityScore">Trusted</option>
        </select>

        <NewsViewModeToggle value={(filters.viewMode ?? "card") as NewsViewMode} onChange={(viewMode) => onChange({ viewMode })} />

        <Button type="button" variant="outline" onClick={onToggleFilters} className="lg:hidden">
          <Filter className="h-4 w-4" />
          Filters
        </Button>
      </div>
    </div>
  )
}

function sourceTypeLabel(value: string) {
  const labels: Record<string, string> = {
    official_blog: "Official blog",
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
    web_page: "Web page",
    media: "Media",
    manual: "Manual",
    custom: "Custom",
  }
  return labels[value] ?? value
}
