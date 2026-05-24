"use client"

import { Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Locale } from "@/lib/papers/types"
import type { ThemeMode } from "@/stores/ui-store"

export function PapersThemeToggle({
  theme,
  locale,
  onThemeChange
}: {
  theme: ThemeMode
  locale: Locale
  onThemeChange: (theme: ThemeMode) => void
}) {
  const nextTheme = theme === "dark" ? "light" : "dark"
  const label = theme === "dark" ? t(papersCopy.themeLight, locale) : t(papersCopy.themeDark, locale)

  return (
    <Button type="button" variant="outline" size="sm" aria-label={label} title={label} className="rounded-full bg-white px-3 dark:bg-card" onClick={() => onThemeChange(nextTheme)}>
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
      <span>{theme === "dark" ? t(papersCopy.darkMode, locale) : t(papersCopy.lightMode, locale)}</span>
    </Button>
  )
}
