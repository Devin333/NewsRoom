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
    <div className="inline-flex rounded-lg border border-[#dfe5df] bg-white/75 p-1 dark:border-border dark:bg-card" aria-label="Paper sort">
      {sorts.map((sort) => (
        <button
          key={sort}
          type="button"
          className={cn(
            "h-8 rounded-md px-3 text-sm font-medium transition-colors",
            value === sort
              ? "bg-[#172033] text-white shadow-sm dark:bg-primary dark:text-primary-foreground"
              : "text-[#334155]/58 hover:bg-[#eef2ec] hover:text-[#172033] dark:text-muted-foreground dark:hover:bg-secondary"
          )}
          onClick={() => onChange(sort)}
        >
          {t(sortLabels[sort], locale)}
        </button>
      ))}
    </div>
  )
}
