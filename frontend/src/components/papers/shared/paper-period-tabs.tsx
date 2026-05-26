"use client"

import { periodLabels, t } from "@/lib/papers/copy"
import { comicSansFont } from "@/lib/fonts"
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
          ? "grid w-full grid-cols-4 gap-1 rounded-3xl border border-[#dbe3dc] bg-white/85 p-1.5 shadow-[0_18px_44px_rgba(15,23,42,0.08)] dark:border-border dark:bg-card"
          : "inline-flex flex-wrap gap-2"
      )}
      aria-label="Paper period"
      style={comicSansFont}
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
                "h-8 rounded-full border px-3 text-sm font-semibold transition-colors",
                fullWidth && "w-full border-transparent px-1 text-center",
                value === period
                  ? "border-[#315d8a] bg-[#315d8a] text-white"
                  : cn(
                      "border-[#d7dfd8] bg-white text-[#334155]/65 hover:border-[#315d8a]/40 hover:text-[#334155] dark:border-border dark:bg-card dark:text-muted-foreground",
                      fullWidth && "border-transparent bg-transparent hover:bg-[#edf1ee] dark:hover:bg-secondary"
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
