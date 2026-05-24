"use client"

import { useMemo, useState } from "react"
import { PaperRow } from "@/components/papers/paper-row"
import { PaperSortTabs } from "@/components/papers/shared/paper-sort-tabs"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import { sortPapers } from "@/lib/papers/format"
import type { Locale, Paper, PaperSort } from "@/lib/papers/types"

const PAGE_SIZE = 100

export function PaperStream({
  papers,
  locale,
  title,
  onPreview
}: {
  papers: Paper[]
  locale: Locale
  title: string
  onPreview: (paper: Paper) => void
}) {
  const [sort, setSort] = useState<PaperSort>("trending")
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const sortedPapers = useMemo(() => sortPapers(papers, sort), [papers, sort])
  const visiblePapers = sortedPapers.slice(0, visibleCount)
  const hasMore = visiblePapers.length < sortedPapers.length

  return (
    <section className="border-t border-[#d7dfd8] dark:border-border">
      <div className="flex flex-col gap-3 border-b border-[#d7dfd8] py-4 sm:flex-row sm:items-center sm:justify-between dark:border-border">
        {title ? <h2 className="text-sm font-semibold">{title}</h2> : <div className="hidden sm:block" />}
        <PaperSortTabs value={sort} locale={locale} onChange={setSort} />
      </div>
      {sortedPapers.length ? (
        <>
          <div className="divide-y divide-[#d8dfd8] dark:divide-border">
            {visiblePapers.map((paper) => (
              <PaperRow key={paper.id} paper={paper} locale={locale} onPreview={onPreview} />
            ))}
          </div>
          {hasMore ? (
            <div className="flex justify-center border-t border-[#d8dfd8] py-8 dark:border-border">
              <Button
                type="button"
                variant="outline"
                className="rounded-full bg-white px-6 dark:bg-card"
                onClick={() => setVisibleCount((count) => Math.min(count + PAGE_SIZE, sortedPapers.length))}
              >
                Load more papers
                <span className="text-[#334155]/55">
                  {visiblePapers.length}/{sortedPapers.length}
                </span>
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {t(papersCopy.noPapers, locale)}
        </div>
      )}
    </section>
  )
}
