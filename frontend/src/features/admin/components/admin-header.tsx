"use client"

import { Filter, Play, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PreferenceControls } from "@/components/layout/preference-controls"
import { pageTitleKey, ui } from "@/features/admin/lib/i18n"
import type { AdminLang, AdminPage } from "@/features/admin/types"

export function AdminHeader({
  activePage,
  lang
}: {
  activePage: AdminPage
  lang: AdminLang
}) {
  const copy = ui[lang]
  const pageTitle = copy[pageTitleKey[activePage]]

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
      <div className="flex min-h-16 flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between lg:px-6">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">
            {copy.admin} / {pageTitle}
          </p>
          <h1 className="mt-1 truncate text-xl font-semibold text-foreground">{pageTitle}</h1>
        </div>

        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 md:justify-end">
          <div className="relative min-w-[14rem] flex-1 md:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" placeholder={copy.searchPlaceholder} aria-label={copy.searchPlaceholder} />
          </div>
          <Button type="button" variant="outline" size="sm">
            <Filter className="size-4" />
            {copy.filters}
          </Button>
          <PreferenceControls compact />
          <Button type="button" size="sm">
            <Play className="size-4" />
            {copy.runPipeline}
          </Button>
        </div>
      </div>
    </header>
  )
}
