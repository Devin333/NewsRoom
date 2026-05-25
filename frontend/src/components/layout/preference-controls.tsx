"use client"

import { Languages, Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useI18n } from "@/lib/i18n/use-i18n"
import { cn } from "@/lib/utils"
import { useUiStore } from "@/stores/ui-store"

type PreferenceControlsProps = {
  className?: string
  compact?: boolean
}

export function PreferenceControls({ className, compact = false }: PreferenceControlsProps) {
  const { locale, t } = useI18n()
  const theme = useUiStore((state) => state.theme)
  const setLocale = useUiStore((state) => state.setLocale)
  const setTheme = useUiStore((state) => state.setTheme)
  const nextLocale = locale === "zh" ? "en" : "zh"
  const nextTheme = theme === "dark" ? "light" : "dark"
  const localeLabel = t("preference.language.switch")
  const themeLabel = theme === "dark" ? t("preference.theme.switchLight") : t("preference.theme.switchDark")

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size={compact ? "icon" : "sm"}
            aria-label={localeLabel}
            title={localeLabel}
            onClick={() => setLocale(nextLocale)}
          >
            <Languages className="size-4" />
            {!compact ? <span>{t("preference.language.current")}</span> : null}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{localeLabel}</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size={compact ? "icon" : "sm"}
            aria-label={themeLabel}
            title={themeLabel}
            onClick={() => setTheme(nextTheme)}
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            {!compact ? <span>{theme === "dark" ? t("preference.theme.dark") : t("preference.theme.light")}</span> : null}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{themeLabel}</TooltipContent>
      </Tooltip>
    </div>
  )
}
