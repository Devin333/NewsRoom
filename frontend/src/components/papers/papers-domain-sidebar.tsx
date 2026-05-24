import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, TaskRef } from "@/lib/papers/types"

export function PapersDomainSidebar({
  topDomains,
  trendingDomains,
  locale
}: {
  topDomains: TaskRef[]
  trendingDomains: TaskRef[]
  locale: Locale
}) {
  return (
    <aside className="space-y-4">
      <DomainPanel index="01/" title={t(papersCopy.topDomains, locale)} domains={topDomains} values={["33,503", "12,640", "9,354", "8,307"]} locale={locale} />
      <DomainPanel index="02/" title={t(papersCopy.trendingDomains, locale)} domains={trendingDomains} values={["1.5x", "2.0x", "3.4x", "1.4x"]} locale={locale} />
    </aside>
  )
}

function DomainPanel({ index, title, domains, values, locale }: { index: string; title: string; domains: TaskRef[]; values: string[]; locale: Locale }) {
  return (
    <section className="rounded-3xl border border-[#dbe3dc] bg-white/90 p-5 shadow-[0_24px_60px_rgba(15,23,42,0.08)] dark:border-border dark:bg-card">
      <p className="text-xs font-semibold text-emerald-600">{index}</p>
      <h2 className="mt-2 text-xs font-black uppercase tracking-[0.16em] text-[#111827] dark:text-foreground">{title}</h2>
      <div className="mt-5 grid gap-3">
        {domains.map((domain, index) => (
          <Link
            key={domain.id}
            href={papersRoutes.taskDetail(domain.slug)}
            className="group flex items-center justify-between gap-3 text-base font-semibold text-slate-600 transition-colors hover:text-emerald-700 dark:text-muted-foreground dark:hover:text-foreground"
          >
            <span>{taskName(domain, locale)}</span>
            <span className="font-mono text-xs text-slate-400">{values[index] ?? ""}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}
