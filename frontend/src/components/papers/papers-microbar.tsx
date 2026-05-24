import Link from "next/link"
import { ChevronRight } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Locale } from "@/lib/papers/types"

export function PapersMicrobar({
  items,
  meta,
  locale
}: {
  items: Array<{ label: string; href?: string }>
  meta: string
  locale: Locale
}) {
  return (
    <div className="flex flex-col gap-2 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
      <nav className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.16em] text-slate-500" aria-label="Papers breadcrumb">
        <Link href="/papers" className="font-medium hover:text-primary">
          Papers
        </Link>
        {items.map((item) => (
          <span key={`${item.label}-${item.href ?? "current"}`} className="inline-flex items-center gap-1">
            <ChevronRight className="size-3" />
            {item.href ? (
              <Link href={item.href} className="hover:text-primary">
                {item.label}
              </Link>
            ) : (
              <span>{item.label}</span>
            )}
          </span>
        ))}
      </nav>
      <span className="inline-flex w-fit items-center gap-2 rounded-full border border-[#dbe5dd] bg-white/90 px-3 py-1 text-xs text-slate-600 shadow-sm dark:border-border dark:bg-card dark:text-muted-foreground">
        <span className="size-2 rounded-full bg-emerald-500" />
        {meta || t(papersCopy.frontendView, locale)}
      </span>
    </div>
  )
}
