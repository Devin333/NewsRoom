import Link from "next/link"
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
  locale,
  className
}: {
  methodAreas: MethodAreaDomain[]
  topTasks: TaskRef[]
  dashboardPapers: Paper[]
  locale: Locale
  className?: string
}) {
  return (
    <aside className={cn("space-y-3 xl:sticky xl:top-24", className)}>
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
  const rowAccentClass = accent === "emerald" ? "hover:border-emerald-200 hover:bg-emerald-50/70 hover:text-emerald-800" : "hover:border-sky-200 hover:bg-sky-50/70 hover:text-sky-800"
  const countAccentClass = accent === "emerald" ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-100" : "bg-sky-50 text-sky-800 ring-1 ring-sky-100"
  const indexAccentClass = accent === "emerald" ? "text-emerald-600" : "text-sky-600"

  return (
    <section className="rounded-xl border border-[#dfe5df] bg-white/70 p-3 shadow-sm dark:border-border dark:bg-card/60">
      <div className="flex items-end justify-between gap-3 border-b border-[#e6ebe4] pb-2.5 dark:border-border">
        <div>
          <p className={cn("text-[0.68rem] font-semibold tracking-[0.14em]", indexAccentClass)}>{index}</p>
          <h2 className="mt-1.5 text-[0.76rem] font-semibold uppercase tracking-[0.14em] text-[#1f2933] dark:text-foreground">
            {title}
          </h2>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-[0.65rem] font-semibold", countAccentClass)}>
          {formatWholeNumber(items.length, locale)}
        </span>
      </div>
      <div className="mt-3 flex gap-2 overflow-x-auto xl:grid xl:overflow-visible">
        {items.map((item) => (
          <Link
            key={item.key}
            href={item.href}
            className={cn(
              "group flex shrink-0 items-center justify-between gap-3 rounded-full border border-transparent bg-[#f7faf5] px-3 py-2 text-[#334155] transition-all xl:shrink xl:rounded-lg xl:py-2.5 dark:bg-background/70 dark:text-foreground",
              rowAccentClass
            )}
          >
            <span className="text-sm font-medium leading-5">{item.label}</span>
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
    (paper) => paper.isPublished !== false && (paper.taskRefs ?? []).some((taskRef) => taskRef.slug === taskSlug)
  ).length
}
