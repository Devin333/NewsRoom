"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Layers3 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  getLocalizedStudioNavigationGroups,
  studioStatusLabel,
  studioStatusTone
} from "@/features/studio/shared/lib/studio-navigation"
import { useI18n } from "@/lib/i18n/use-i18n"

export function StudioSidebar() {
  const pathname = usePathname()
  const { locale, t } = useI18n()
  const navigationGroups = getLocalizedStudioNavigationGroups(locale)

  return (
    <aside className="hidden w-60 shrink-0 border-r border-border bg-card lg:block">
      <div className="flex h-14 items-center gap-3 border-b border-border px-4">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-primary">
          <Layers3 className="size-5" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-foreground">{t("studio.title")}</p>
          <p className="truncate text-xs text-muted-foreground">{t("studio.subtitle")}</p>
        </div>
      </div>

      <nav className="space-y-5 px-3 py-4" aria-label={t("studio.title")}>
        {navigationGroups.map((group) => (
          <div key={group.label} className="space-y-2">
            <p className="px-2 text-[10px] font-semibold uppercase tracking-normal text-muted-foreground">
              {group.label}
            </p>
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon
                const active = item.href === "/studio" ? pathname === item.href : pathname.startsWith(item.href)

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex min-h-9 items-center gap-3 rounded-md border border-transparent px-2.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
                      active && "border-border bg-secondary text-foreground shadow-sm"
                    )}
                  >
                    {Icon ? <Icon className="size-4 shrink-0" /> : null}
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.status ? <Badge className="min-h-5 px-1.5 py-0 text-[10px]" variant={studioStatusTone(item.status)}>{studioStatusLabel(item.status, locale)}</Badge> : null}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  )
}
