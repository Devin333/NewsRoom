"use client"

import { useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { NewsFilterPanel } from "@/features/news/components/news-filter-panel"
import { NewsList } from "@/features/news/components/news-list"
import { NewsToolbar } from "@/features/news/components/news-toolbar"
import { useNewsList } from "@/features/news/hooks/use-news-list"
import { filtersFromSearchParams, filtersToSearchParams, updateFilters } from "@/features/news/lib/news-filters"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { NewsFilters, NewsViewMode } from "@/types/news"

export function NewsPageClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { locale, t } = useI18n()
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const filters = useMemo(() => filtersFromSearchParams(new URLSearchParams(searchParams.toString())), [searchParams])
  const { data, isLoading, isError, error, refetch } = useNewsList(filters)

  const setFilters = (patch: Partial<NewsFilters>) => {
    const next = updateFilters(filters, patch)
    const params = filtersToSearchParams(next)
    router.replace(params.size ? `/news?${params.toString()}` : "/news", { scroll: false })
  }

  if (isLoading) {
    return <PageSkeleton />
  }

  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : t("portal.news.loadError")} onRetry={() => refetch()} />
  }

  if (!data) {
    return <EmptyState title={t("portal.news.emptyTitle")} description={t("portal.news.emptyDescription")} />
  }

  const page = data.page
  const viewMode = (filters.viewMode ?? "card") as NewsViewMode
  const totalPages = Math.max(1, Math.ceil(page.total / page.pageSize))
  const allItems = data.allItems
  const categories = data.options.categories.map((category) => ({
    name: category,
    count: allItems.filter((item) => item.category === category).length
  }))
  const trendingSources = data.options.sourceTypes.map((sourceType) => ({
    name: sourceType,
    count: allItems.filter((item) => item.sourceType === sourceType).length
  }))

  return (
    <main className="space-y-8">
      <header className="pt-2">
        <h1 className="font-serif text-4xl font-semibold tracking-normal text-foreground">
          {locale === "zh" ? t("portal.news.title") : (
            <>
              Trending <span className="italic text-primary">{t("portal.news.titleAccent")}</span>
            </>
          )}
        </h1>
        <p className="mt-2 font-serif text-sm italic text-muted-foreground">{t("portal.news.description")}</p>
      </header>

      <div className="grid gap-8 xl:grid-cols-[190px_minmax(0,1fr)]">
        <aside className="hidden space-y-8 xl:block">
          <DomainList title={t("portal.news.topDomains")} items={categories} locale={locale} onSelect={(category) => setFilters({ category: [category] })} />
          <DomainList
            title={t("portal.news.trendingSources")}
            items={trendingSources}
            locale={locale}
            onSelect={(sourceType) => setFilters({ sourceType: [sourceType as NonNullable<NewsFilters["sourceType"]>[number]] })}
          />
        </aside>

        <section className="min-w-0 space-y-5">
          <div className="flex flex-col gap-4 border-b border-border pb-3 xl:flex-row xl:items-end xl:justify-between">
            <div className="flex flex-wrap items-center gap-3">
              {[
                ["heatScore", t("portal.news.sort.trending")],
                ["publishedAt", t("portal.news.sort.newest")],
                ["qualityScore", t("portal.news.sort.quality")]
              ].map(([sort, label]) => (
                <button
                  key={sort}
                  type="button"
                  onClick={() => setFilters({ sort: sort as NewsFilters["sort"] })}
                  className={
                    (filters.sort ?? "publishedAt") === sort
                      ? "rounded-sm bg-foreground px-3 py-1.5 font-mono text-xs font-semibold text-background"
                      : "rounded-sm px-3 py-1.5 font-mono text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {[
                ["", t("common.allTime")],
                ["today", t("common.today")],
                ["week", t("common.thisWeek")],
                ["month", t("common.thisMonth")]
              ].map(([dateRange, label]) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setFilters({ dateRange: dateRange ? (dateRange as NewsFilters["dateRange"]) : undefined })}
                  className={
                    (filters.dateRange ?? "") === dateRange
                      ? "rounded-md bg-foreground px-3 py-2 text-xs font-semibold text-background"
                      : "rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <NewsToolbar filters={filters} onChange={setFilters} onToggleFilters={() => setMobileFiltersOpen((value) => !value)} />

          <div className={mobileFiltersOpen ? "block xl:hidden" : "hidden"}>
            <NewsFilterPanel filters={filters} options={data.options} onChange={setFilters} />
          </div>

          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>{t("portal.news.showing", { shown: page.items.length, total: page.total })}</span>
            <span>{t("portal.news.page", { page: page.page, totalPages })}</span>
          </div>

          <NewsList items={page.items} viewMode={viewMode} />

          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              disabled={page.page <= 1}
              onClick={() => setFilters({ page: page.page - 1 })}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45"
            >
              {t("common.previousPage")}
            </button>
            <button
              type="button"
              disabled={!page.hasNext}
              onClick={() => setFilters({ page: page.page + 1 })}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-45"
            >
              {t("common.nextPage")}
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}

function DomainList({
  title,
  items,
  locale,
  onSelect
}: {
  title: string
  items: Array<{ name: string; count: number }>
  locale: "zh" | "en"
  onSelect: (name: string) => void
}) {
  const { t, status } = useI18n()

  return (
    <section className="space-y-3">
      <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</h2>
      <div className="space-y-2">
        {items.slice(0, 8).map((item) => (
          <button
            key={item.name}
            type="button"
            onClick={() => onSelect(item.name)}
            className="flex w-full items-baseline justify-between gap-3 text-left text-sm text-muted-foreground hover:text-foreground"
          >
            <span className="truncate">{labelValue(item.name, locale, status)}</span>
            <span className="font-mono text-[11px]">{item.count}</span>
          </button>
        ))}
      </div>
      <button type="button" className="font-serif text-sm italic text-muted-foreground hover:text-foreground">
        {t("portal.news.allDomains")} →
      </button>
    </section>
  )
}

function labelValue(value: string, locale: "zh" | "en", status: (value: string | null | undefined) => string) {
  const labels: Record<string, string> = {
    official_blog: locale === "zh" ? "官方博客" : "Official Blog",
    rss: "RSS",
    github: "GitHub",
    hackernews: "Hacker News",
    reddit: "Reddit",
    arxiv: "arXiv",
    media: locale === "zh" ? "媒体" : "Media",
    custom: locale === "zh" ? "自定义" : "Custom"
  }

  if (value === "passed" || value === "review" || value === "failed") {
    return status(value)
  }

  return labels[value] ?? value
}
