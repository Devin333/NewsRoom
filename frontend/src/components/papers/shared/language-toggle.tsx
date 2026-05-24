"use client"

import { Languages } from "lucide-react"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Locale } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

export function PapersLanguageToggle({
  locale,
  onLocaleChange
}: {
  locale: Locale
  onLocaleChange: (locale: Locale) => void
}) {
  const nextLocale = locale === "zh" ? "en" : "zh"

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-10 gap-2 rounded-full border-[#d7dfd8] bg-white px-2.5 shadow-sm dark:border-border dark:bg-card"
      title={t(papersCopy.languageToggle, locale)}
      onClick={() => onLocaleChange(nextLocale)}
    >
      <Languages className="size-4" />
      <span className="flex items-center gap-1 text-xs font-semibold">
        <span
          className={cn(
            "rounded-full px-2 py-0.5 transition-colors",
            locale === "zh"
              ? "bg-[#0f172a] text-white dark:bg-foreground dark:text-background"
              : "text-slate-500 dark:text-muted-foreground"
          )}
        >
          中
        </span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 transition-colors",
            locale === "en"
              ? "bg-[#0f172a] text-white dark:bg-foreground dark:text-background"
              : "text-slate-500 dark:text-muted-foreground"
          )}
        >
          EN
        </span>
      </span>
    </Button>
  )
}
