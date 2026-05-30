import Link from "next/link"
import { comicSansFont } from "@/lib/fonts"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { MethodAreaDomain } from "@/lib/papers/metrics"
import type { Locale, Paper, TaskRef } from "@/lib/papers/types"

export function PapersDomainSidebar({
  methodAreas,
  topTasks,
  papers,
  dashboardPapers,
  locale,
}: {
  methodAreas: MethodAreaDomain[]
  topTasks: TaskRef[]
  papers: Paper[]
  dashboardPapers: Paper[]
  locale: Locale
}) {
  return (
    <aside className="space-y-9">
      {/* 01/ Methods — 技术方法大类 */}
      <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
        <p className="text-[0.7rem] font-semibold text-emerald-600">01/</p>
        <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
          {t(papersCopy.methods, locale)}
        </h2>
        <div className="mt-5 grid gap-3.5">
          {methodAreas.map((area) => (
            <Link
              key={area.slug}
              href={`${papersRoutes.methods}#${area.slug}`}
              className="flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-emerald-700 dark:text-muted-foreground dark:hover:text-foreground"
              style={comicSansFont}
            >
              <span className="leading-5">{area.name}</span>
              <span className="text-[0.7rem] font-semibold text-[#334155]/52">
                {formatWholeNumber(area.count, locale)}
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* 02/ Tasks — 具体研究任务 */}
      <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
        <p className="text-[0.7rem] font-semibold text-sky-600">02/</p>
        <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
          {t(papersCopy.tasks, locale)}
        </h2>
        <div className="mt-5 grid gap-3.5">
          {topTasks.map((task) => {
            const count = dashboardPapers.filter(
              (p) => p.isPublished && (p.taskRefs ?? []).some((r) => r.slug === task.slug)
            ).length
            return (
              <Link
                key={task.id}
                href={papersRoutes.taskDetail(task.slug)}
                className="flex items-baseline justify-between gap-3 text-base font-semibold text-[#334155]/80 transition-colors hover:text-sky-700 dark:text-muted-foreground dark:hover:text-foreground"
                style={comicSansFont}
              >
                <span className="leading-5">{taskName(task, locale)}</span>
                <span className="text-[0.7rem] font-semibold text-[#334155]/52">
                  {formatWholeNumber(count, locale)}
                </span>
              </Link>
            )
          })}
        </div>
      </section>
    </aside>
  )
}

export function countPapersForTask(papers: Paper[], taskSlug: string) {
  return papers.filter(
    (p) => p.isPublished && (p.taskRefs ?? []).some((r) => r.slug === taskSlug)
  ).length
}
