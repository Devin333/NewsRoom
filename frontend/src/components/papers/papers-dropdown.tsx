"use client"

import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import { papersDropdownItems } from "@/lib/papers/routes"
import type { Locale } from "@/lib/papers/types"

export function PapersDropdown({ locale }: { locale: Locale }) {
  return (
    <div className="absolute left-1/2 top-full w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 pt-2">
      <div className="rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-soft">
        <div className="grid gap-1">
          {papersDropdownItems.map((item) => {
            const label = t(papersCopy[item.labelKey], locale)
            return (
              <Link
                key={item.href}
                href={item.href}
                className="group rounded-md px-3 py-2 transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex items-center justify-between gap-3 text-sm font-semibold text-foreground">
                  {label}
                  <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-70" />
                </span>
                <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                  {t(papersCopy[item.descriptionKey], locale)}
                </span>
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
