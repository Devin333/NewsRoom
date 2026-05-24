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
    <div className="inline-flex gap-5">
      {sorts.map((sort) => (
        <button
          key={sort}
          type="button"
          className={cn(
            "relative h-8 text-sm font-medium transition-colors after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:origin-left after:scale-x-0 after:bg-emerald-600 after:transition-transform",
            value === sort
              ? "text-[#334155] after:scale-x-100 dark:text-foreground"
              : "text-[#334155]/55 hover:text-[#334155] dark:text-muted-foreground"
          )}
          onClick={() => onChange(sort)}
        >
          {t(sortLabels[sort], locale)}
        </button>
      ))}
    </div>
  )
}
