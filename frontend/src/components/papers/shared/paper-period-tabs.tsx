"use client"

import { periodLabels, t } from "@/lib/papers/copy"
import type { Locale, PaperPeriod } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const periods: PaperPeriod[] = ["daily", "weekly", "monthly", "all"]

export function PaperPeriodTabs({
  value,
  locale,
  hrefForPeriod,
  onChange,
  fullWidth = false
}: {
  value: PaperPeriod
  locale: Locale
  hrefForPeriod?: (period: PaperPeriod) => string
  onChange: (period: PaperPeriod) => void
  fullWidth?: boolean
}) {
  return (
    <div
      className={cn(
        fullWidth
          ? "grid w-full grid-cols-4 gap-1 rounded-xl border border-[#dfe5df] bg-white/80 p-1 shadow-sm dark:border-border dark:bg-card"
          : "inline-flex flex-wrap gap-2"
      )}
      aria-label="Paper period"
    >
      {periods.map((period) => {
        const href = hrefForPeriod?.(period) ?? "#"
        const formId = `paper-period-${period}`
        return (
          <span key={period} className={cn("inline-flex", fullWidth && "min-w-0")}>
            <form id={formId} action={actionPath(href)} method="get" className="hidden" aria-hidden="true">
              {hiddenFields(href).map(([name, hiddenValue]) => (
                <input key={name} type="hidden" name={name} value={hiddenValue} />
              ))}
            </form>
            <button
              type="submit"
              form={formId}
              className={cn(
                "h-8 rounded-lg border px-3 text-sm font-medium transition-colors",
                fullWidth && "w-full border-transparent px-1 text-center",
                value === period
                  ? "border-[#172033] bg-[#172033] text-white"
                  : cn(
                      "border-[#d7dfd8] bg-white text-[#334155]/65 hover:border-[#172033]/30 hover:text-[#172033] dark:border-border dark:bg-card dark:text-muted-foreground",
                      fullWidth && "border-transparent bg-transparent hover:bg-[#eef2ec] dark:hover:bg-secondary"
                    )
              )}
              onClick={(event) => {
                event.preventDefault()
                onChange(period)
              }}
            >
              {t(periodLabels[period], locale)}
            </button>
          </span>
        )
      })}
    </div>
  )
}

function actionPath(href: string) {
  return href.split("?")[0] || "#"
}

function hiddenFields(href: string) {
  const query = href.split("?")[1]
  if (!query) {
    return []
  }
  return Array.from(new URLSearchParams(query).entries())
}
