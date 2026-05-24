import Link from "next/link"
import { papersCopy, t } from "@/lib/papers/copy"
import { taskName } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, TaskRef } from "@/lib/papers/types"

export function SisterTasksPanel({ tasks, locale }: { tasks: TaskRef[]; locale: Locale }) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{t(papersCopy.sisterTasks, locale)}</h2>
      <div className="mt-3 grid gap-2">
        {tasks.map((task) => (
          <Link key={task.id} href={papersRoutes.taskDetail(task.slug)} className="rounded-md bg-secondary/60 px-3 py-2 text-sm hover:bg-secondary">
            {taskName(task, locale)}
          </Link>
        ))}
      </div>
    </section>
  )
}
