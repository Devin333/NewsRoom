"use client"

import type { FormEvent, ReactNode } from "react"
import { useEffect, useState } from "react"
import { Search, SlidersHorizontal } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/common/badge"
import { PageHeader } from "@/components/layout/page-header"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { CommunityFilterPanel } from "@/features/community/components/community-filter-panel"
import { CommunitySourceList } from "@/features/community/components/community-source-list"
import { CommunityTopicCard } from "@/features/community/components/community-topic-card"
import {
  COMMUNITY_SENTIMENTS,
  communitySentimentLabel,
  communitySourceLabel
} from "@/lib/community/community-filters"
import type { CommunityListParams, CommunityListResult } from "@/types/community"

export function CommunityPulsePage({
  result,
  filters,
  onChange
}: {
  result: CommunityListResult
  filters: CommunityListParams
  onChange: (patch: Partial<CommunityListParams>) => void
}) {
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [query, setQuery] = useState(filters.q ?? "")
  const page = result.page
  const totalPages = Math.max(1, Math.ceil(page.total / page.pageSize))

  useEffect(() => {
    setQuery(filters.q ?? "")
  }, [filters.q])

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onChange({ q: query.trim() || undefined })
  }

  return (
    <main className="space-y-8">
      <PageHeader
        eyebrow="Community Pulse"
        title="Developer community signals"
        description="Track public developer discussions, sentiment, controversy, adoption signals, and their links to papers, projects, and news."
        actions={
          <Badge tone={result.dataState === "empty" ? "warning" : "accent"}>
            {result.source === "artifact" ? "Local artifact" : result.source === "backend" ? "Backend output" : "Empty"}
          </Badge>
        }
      />

      <section className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Topics" value={result.metrics.totalTopics} />
        <MetricCard label="Sources" value={result.metrics.activeSources} />
        <MetricCard label="Avg heat" value={result.metrics.averageHeatScore ?? "n/a"} />
        <MetricCard label="Mixed signals" value={result.metrics.mixedCount} />
      </section>

      <div className="grid gap-8 xl:grid-cols-[190px_minmax(0,1fr)]">
        <CommunitySourceList options={result.options} filters={filters} onChange={onChange} />

        <section className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
            <SegmentButton active={!filters.sentiment} onClick={() => onChange({ sentiment: undefined })}>
              All sentiment
            </SegmentButton>
            {COMMUNITY_SENTIMENTS.map((sentiment) => (
              <SegmentButton
                key={sentiment}
                active={filters.sentiment === sentiment}
                onClick={() => onChange({ sentiment: filters.sentiment === sentiment ? undefined : sentiment })}
              >
                {communitySentimentLabel(sentiment)}
              </SegmentButton>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <SegmentButton active={!filters.source} onClick={() => onChange({ source: undefined })}>
              All sources
            </SegmentButton>
            {result.options.sources.map((source) => (
              <SegmentButton
                key={source.sourceType}
                active={filters.source === source.sourceType}
                onClick={() => onChange({ source: filters.source === source.sourceType ? undefined : source.sourceType })}
              >
                {communitySourceLabel(source.sourceType)}
              </SegmentButton>
            ))}
          </div>

          <form onSubmit={submitSearch} className="flex flex-col gap-3 rounded-md border border-border bg-card p-3 md:flex-row md:items-center">
            <label className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search discussions, entities, tags"
                className="h-10 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm text-foreground outline-none focus:border-primary"
                aria-label="Search community topics"
              />
            </label>
            <select
              value={filters.sort ?? "trending"}
              onChange={(event) => onChange({ sort: event.target.value as CommunityListParams["sort"] })}
              className="h-10 rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none"
              aria-label="Sort community topics"
            >
              <option value="trending">Trending</option>
              <option value="newest">Newest</option>
              <option value="controversial">Controversial</option>
              <option value="adoption">Adoption</option>
            </select>
            <Button type="submit" size="sm">
              Search
            </Button>
            <Button type="button" variant="outline" size="sm" className="xl:hidden" onClick={() => setMobileFiltersOpen((value) => !value)}>
              <SlidersHorizontal className="size-4" />
              Filters
            </Button>
          </form>

          <div className={mobileFiltersOpen ? "block xl:hidden" : "hidden"}>
            <CommunityFilterPanel filters={filters} onChange={onChange} />
          </div>

          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              Showing {page.items.length} of {page.total}
            </span>
            <span>
              Page {page.page} of {totalPages}
            </span>
          </div>

          {page.items.length ? (
            <div className="space-y-4">
              {page.items.map((topic) => (
                <CommunityTopicCard key={topic.id} topic={topic} />
              ))}
            </div>
          ) : (
            <EmptyState title="No community topics" description="No public Community Pulse topics matched the current filters." />
          )}

          {result.notices.length ? (
            <div className="space-y-2 text-xs text-muted-foreground">
              {result.notices.map((notice) => (
                <p key={notice}>{notice}</p>
              ))}
            </div>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            <Button variant="outline" disabled={page.page <= 1} onClick={() => onChange({ page: page.page - 1 })}>
              Previous
            </Button>
            <Button variant="outline" disabled={!page.hasNext} onClick={() => onChange({ page: page.page + 1 })}>
              Next
            </Button>
          </div>
        </section>
      </div>
    </main>
  )
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">{label}</p>
        <p className="mt-2 font-mono text-2xl font-semibold text-foreground">{value}</p>
      </CardContent>
    </Card>
  )
}

function SegmentButton({
  active,
  onClick,
  children
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "rounded-md bg-foreground px-3 py-2 text-xs font-semibold text-background"
          : "rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
      }
    >
      {children}
    </button>
  )
}
