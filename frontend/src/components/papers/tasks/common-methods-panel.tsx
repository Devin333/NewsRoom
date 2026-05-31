import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, methodName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, MethodRef, Paper } from "@/lib/papers/types"

export function CommonMethodsPanel({
  methods,
  papers,
  locale
}: {
  methods: MethodRef[]
  papers: Paper[]
  locale: Locale
}) {
  const visibleMethods = methods
    .map((method) => ({
      method,
      count: papers.filter(
        (p) => p.isPublished !== false && (p.methodRefs ?? []).some((r) => r.slug === method.slug)
      ).length
    }))
    .filter((item) => item.count > 0)

  if (!visibleMethods.length) return null
  return (
    <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
      <p className="text-[0.68rem] font-black text-emerald-700 dark:text-emerald-400">02/</p>
      <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
        {t(papersCopy.commonMethods, locale)}
      </h2>
      <div className="mt-4 divide-y divide-[#e8eeea] dark:divide-border">
        {visibleMethods.map(({ method, count }) => {
          return (
            <Link
              key={method.id}
              href={papersRoutes.methodDetail(method.slug)}
              className="flex items-baseline justify-between gap-3 py-2.5 text-sm text-[#334155]/72 transition-colors hover:text-blue-700 dark:text-muted-foreground dark:hover:text-foreground"
            >
              <span className="font-semibold leading-5">{methodName(method, locale)}</span>
              <span className="shrink-0 text-xs text-[#334155]/45 dark:text-muted-foreground">
                {formatWholeNumber(count, locale)}
              </span>
            </Link>
          )
        })}
      </div>
    </section>
  )
}
