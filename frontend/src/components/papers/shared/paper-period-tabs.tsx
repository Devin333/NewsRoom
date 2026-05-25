"use client"

import { periodLabels, t } from "@/lib/papers/copy"
import type { Locale, PaperPeriod } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const periods: PaperPeriod[] = ["daily", "weekly", "monthly", "all"]

export function PaperPeriodTabs({
  value,
  locale,
  onChange
}: {
  value: PaperPeriod
  locale: Locale
  onChange: (period: PaperPeriod) => void
}) {
  return (
    <div className="inline-flex flex-wrap gap-2" aria-label="Paper period">
      {periods.map((period) => (
        <button
          key={period}
          type="button"
          className={cn(
            "h-8 rounded-full border px-3 text-sm font-semibold transition-colors",
            value === period
              ? "border-[#315d8a] bg-[#315d8a] text-white"
              : "border-[#d7dfd8] bg-white text-[#334155]/65 hover:border-[#315d8a]/40 hover:text-[#334155] dark:border-border dark:bg-card dark:text-muted-foreground"
          )}
          onClick={() => onChange(period)}
        >
          {t(periodLabels[period], locale)}
        </button>
      ))}
    </div>
  )
}
