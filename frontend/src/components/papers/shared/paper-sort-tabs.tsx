"use client"

import { sortLabels, t } from "@/lib/papers/copy"
import type { Locale, PaperSort } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const sorts: PaperSort[] = ["trending", "newest", "most_cited"]

export function PaperSortTabs({
  value,
  locale,
  onChange
}: {
  value: PaperSort
  locale: Locale
  onChange: (sort: PaperSort) => void
}) {
  return (
    <div className="inline-flex rounded-xl bg-[#eef3ef] p-1 dark:bg-secondary">
      {sorts.map((sort) => (
        <button
          key={sort}
          type="button"
          className={cn(
            "h-8 rounded-full px-4 text-sm font-medium transition-colors",
            value === sort ? "bg-[#0f172a] text-white shadow-sm dark:bg-background dark:text-foreground" : "text-slate-500 hover:text-foreground dark:text-muted-foreground"
          )}
          onClick={() => onChange(sort)}
        >
          {t(sortLabels[sort], locale)}
        </button>
      ))}
    </div>
  )
}
