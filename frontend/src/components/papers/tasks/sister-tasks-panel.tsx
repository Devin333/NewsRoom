import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, Paper, TaskRef } from "@/lib/papers/types"

export function SisterTasksPanel({
  tasks,
  papers,
  locale
}: {
  tasks: TaskRef[]
  papers: Paper[]
  locale: Locale
}) {
  if (!tasks.length) return null
  return (
    <section className="border-t border-[#d7dfd8] pt-5 dark:border-border">
      <p className="text-[0.68rem] font-black text-emerald-700 dark:text-emerald-400">01/</p>
      <h2 className="mt-2 text-[0.72rem] font-black uppercase tracking-[0.18em] text-[#334155] dark:text-foreground">
        {t(papersCopy.sisterTasks, locale)}
      </h2>
      <div className="mt-4 divide-y divide-[#e8eeea] dark:divide-border">
        {tasks.map((task) => {
          const count = papers.filter(
            (p) => p.isPublished !== false && (p.taskRefs ?? []).some((r) => r.slug === task.slug)
          ).length
          return (
            <Link
              key={task.id}
              href={papersRoutes.taskDetail(task.slug)}
              className="flex items-baseline justify-between gap-3 py-2.5 text-sm text-[#334155]/72 transition-colors hover:text-emerald-700 dark:text-muted-foreground dark:hover:text-foreground"
            >
              <span className="font-semibold leading-5">{taskName(task, locale)}</span>
              {count > 0 && (
                <span className="shrink-0 text-xs text-[#334155]/45 dark:text-muted-foreground">
                  {formatWholeNumber(count, locale)}
                </span>
              )}
            </Link>
          )
        })}
      </div>
    </section>
  )
}
