import Link from "next/link"
import { comicSansFont } from "@/lib/fonts"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { MethodAreaDomain } from "@/lib/papers/metrics"
import type { Locale, Paper, TaskRef } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

export function PapersDomainSidebar({
  methodAreas,
  topTasks,
  dashboardPapers,
  locale
}: {
  methodAreas: MethodAreaDomain[]
  topTasks: TaskRef[]
  dashboardPapers: Paper[]
  locale: Locale
}) {
  return (
    <aside className="space-y-4 xl:sticky xl:top-24">
      <SidebarSection
        accent="emerald"
        index="01"
        title={t(papersCopy.methods, locale)}
        items={methodAreas.map((area) => ({
          key: area.slug,
          href: `${papersRoutes.methods}#${area.slug}`,
          label: area.name,
          count: area.count
        }))}
        locale={locale}
      />
      <SidebarSection
        accent="sky"
        index="02"
        title={t(papersCopy.tasks, locale)}
        items={topTasks.map((task) => ({
          key: task.id,
          href: papersRoutes.taskDetail(task.slug),
          label: taskName(task, locale),
          count: countPapersForTask(dashboardPapers, task.slug)
        }))}
        locale={locale}
      />
    </aside>
  )
}

function SidebarSection({
  accent,
  index,
  title,
  items,
  locale
}: {
  accent: "emerald" | "sky"
  index: string
  title: string
  items: Array<{ key: string; href: string; label: string; count: number }>
  locale: Locale
}) {
  const rowAccentClass = accent === "emerald" ? "hover:border-emerald-200 hover:bg-emerald-50/65 hover:text-emerald-800" : "hover:border-sky-200 hover:bg-sky-50/65 hover:text-sky-800"
  const countAccentClass = accent === "emerald" ? "bg-emerald-100 text-emerald-800" : "bg-sky-100 text-sky-800"
  const indexAccentClass = accent === "emerald" ? "text-emerald-600" : "text-sky-600"

  return (
    <section className="rounded-2xl border border-[#dbe3dc] bg-white/82 p-4 shadow-[0_12px_30px_rgba(15,23,42,0.06)] dark:border-border dark:bg-card">
      <div className="flex items-end justify-between gap-3 border-b border-[#e4ebe4] pb-3 dark:border-border">
        <div>
          <p className={cn("text-[0.7rem] font-semibold tracking-[0.16em]", indexAccentClass)}>{index}</p>
          <h2 className="mt-2 text-[0.76rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
            {title}
          </h2>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-[0.65rem] font-semibold", countAccentClass)}>
          {formatWholeNumber(items.length, locale)}
        </span>
      </div>
      <div className="mt-3 grid gap-2.5">
        {items.map((item) => (
          <Link
            key={item.key}
            href={item.href}
            className={cn(
              "group flex items-center justify-between gap-3 rounded-xl border border-transparent bg-[#f7faf7] px-3 py-3 text-[#334155] transition-all dark:bg-background/70 dark:text-foreground",
              rowAccentClass
            )}
            style={comicSansFont}
          >
            <span className="text-sm font-semibold leading-5">{item.label}</span>
            <span className={cn("rounded-full px-2.5 py-1 text-[0.68rem] font-semibold", countAccentClass)}>
              {formatWholeNumber(item.count, locale)}
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

export function countPapersForTask(papers: Paper[], taskSlug: string) {
  return papers.filter(
    (paper) => paper.isPublished && (paper.taskRefs ?? []).some((taskRef) => taskRef.slug === taskSlug)
  ).length
}
