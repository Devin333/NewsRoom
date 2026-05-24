"use client"

import { useMemo, useState } from "react"
import { PaperRow } from "@/components/papers/paper-row"
import { PaperSortTabs } from "@/components/papers/shared/paper-sort-tabs"
import { papersCopy, t } from "@/lib/papers/copy"
import { sortPapers } from "@/lib/papers/format"
import type { Locale, Paper, PaperSort } from "@/lib/papers/types"

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
  const sortedPapers = useMemo(() => sortPapers(papers, sort), [papers, sort])

  return (
    <section className="rounded-3xl border border-[#dbe3dc] bg-white/95 p-6 shadow-[0_24px_70px_rgba(15,23,42,0.10)] dark:border-border dark:bg-card">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {title ? <h2 className="text-sm font-semibold">{title}</h2> : <span />}
        <PaperSortTabs value={sort} locale={locale} onChange={setSort} />
      </div>
      {sortedPapers.length ? (
        <div className="divide-y divide-[#d8dfd8] dark:divide-border">
          {sortedPapers.map((paper) => (
            <PaperRow key={paper.id} paper={paper} locale={locale} onPreview={onPreview} />
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {t(papersCopy.noPapers, locale)}
        </div>
      )}
    </section>
  )
}
