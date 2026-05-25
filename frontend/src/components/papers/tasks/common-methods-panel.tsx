import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { methodName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, MethodRef } from "@/lib/papers/types"

export function CommonMethodsPanel({ methods, locale }: { methods: MethodRef[]; locale: Locale }) {
  return (
    <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
      <p className="text-[0.68rem] font-black text-emerald-700 dark:text-emerald-400">03/</p>
      <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
        {t(papersCopy.commonMethods, locale)}
      </h2>
      <div className="mt-5 grid gap-3">
        {methods.map((method, index) => (
          <Link
            key={method.id}
            href={papersRoutes.methodDetail(method.slug)}
            className="group grid grid-cols-[1.5rem_minmax(0,1fr)] items-baseline gap-3 text-sm text-[#334155]/72 transition-colors hover:text-blue-700 dark:text-muted-foreground dark:hover:text-foreground"
          >
            <span className="text-[0.66rem] font-black text-[#334155]/42 dark:text-muted-foreground">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="font-semibold leading-5">{methodName(method, locale)}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}
