"use client"

import Link from "next/link"
import type { NavigationItem } from "@/config/navigation"
import { navigationLabel } from "@/lib/i18n/navigation"
import { useI18n } from "@/lib/i18n/use-i18n"
import { cn } from "@/lib/utils"

export function MegaMenu({ item, className }: { item: NavigationItem; className?: string }) {
  const { locale, t } = useI18n()
  const itemLabel = navigationLabel(item.label, locale)

  return (
    <div
      className={cn(
        "absolute left-1/2 top-full w-[min(42rem,calc(100vw-3rem))] -translate-x-1/2 pt-2",
        className
      )}
    >
      <div className="rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-soft">
        <div className="mb-2 flex items-center justify-between gap-4 px-2">
          <Link href={item.href} className="text-sm font-semibold text-foreground hover:text-primary">
            {itemLabel}
          </Link>
          <span className="text-xs text-muted-foreground">{t("nav.explore", { section: itemLabel })}</span>
        </div>
        <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {item.children.map((child) => (
            <Link
              key={`${item.label}-${child.label}`}
              href={child.href}
              className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="block font-medium text-foreground">{navigationLabel(child.label, locale)}</span>
              {child.description ? (
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">{child.description}</span>
              ) : null}
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
