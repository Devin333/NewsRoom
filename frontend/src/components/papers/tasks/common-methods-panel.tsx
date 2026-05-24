import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { methodName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, MethodRef } from "@/lib/papers/types"

export function CommonMethodsPanel({ methods, locale }: { methods: MethodRef[]; locale: Locale }) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{t(papersCopy.commonMethods, locale)}</h2>
      <div className="mt-3 flex flex-wrap gap-2">
        {methods.map((method) => (
          <Link key={method.id} href={papersRoutes.methodDetail(method.slug)} className="rounded-md border border-border bg-background px-3 py-2 text-sm hover:bg-secondary">
            {methodName(method, locale)}
          </Link>
        ))}
      </div>
    </section>
  )
}
