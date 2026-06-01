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
  emptyDescription,
  sort: controlledSort,
  onSortChange,
  onPreview
}: {
  papers: Paper[]
  locale: Locale
  title: string
  emptyDescription?: string
  sort?: PaperSort
  onSortChange?: (sort: PaperSort) => void
  onPreview: (paper: Paper) => void
}) {
  const [localSort, setLocalSort] = useState<PaperSort>("trending")
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const sort = controlledSort ?? localSort
  const sortedPapers = useMemo(() => (controlledSort ? papers : sortPapers(papers, sort)), [controlledSort, papers, sort])
  const visiblePapers = sortedPapers.slice(0, visibleCount)
  const hasMore = visiblePapers.length < sortedPapers.length

  function handleSortChange(nextSort: PaperSort) {
    setVisibleCount(PAGE_SIZE)
    if (controlledSort !== undefined) {
      onSortChange?.(nextSort)
      return
    }
    setLocalSort(nextSort)
  }

  return (
    <section className="rounded-xl border border-[#dfe5df] bg-white/60 dark:border-border dark:bg-card/40">
      <div className="flex flex-col gap-3 border-b border-[#dfe5df] px-4 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-border">
        {title ? <h2 className="text-sm font-semibold text-[#1f2933] dark:text-foreground">{title}</h2> : <div className="hidden sm:block" />}
        <PaperSortTabs value={sort} locale={locale} onChange={handleSortChange} />
      </div>
      {sortedPapers.length ? (
        <>
          <div className="divide-y divide-[#e1e7df] px-1 dark:divide-border">
            {visiblePapers.map((paper, index) => (
              <PaperRow key={paper.id} paper={paper} locale={locale} onPreview={onPreview} renderPdfPreview={index < 3} />
            ))}
          </div>
          {hasMore ? (
            <div className="flex justify-center border-t border-[#dfe5df] py-6 dark:border-border">
              <Button
                type="button"
                variant="outline"
                className="rounded-lg bg-white px-6 dark:bg-card"
                onClick={() => setVisibleCount((count) => Math.min(count + PAGE_SIZE, sortedPapers.length))}
              >
                {t(papersCopy.loadMorePapers, locale)}
                <span className="text-[#334155]/55">
                  {visiblePapers.length}/{sortedPapers.length}
                </span>
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="m-4 rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          <p>{t(papersCopy.noPapers, locale)}</p>
          {emptyDescription ? (
            <p className="mx-auto mt-2 max-w-2xl leading-6">{emptyDescription}</p>
          ) : null}
        </div>
      )}
    </section>
  )
}
