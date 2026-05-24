import { TaskCell } from "@/components/papers/tasks/task-cell"
import type { Locale, PaperTask } from "@/lib/papers/types"

export function TaskSection({ title, tasks, locale }: { title: string; tasks: PaperTask[]; locale: Locale }) {
  if (!tasks.length) {
    return null
  }

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {tasks.map((task) => (
          <TaskCell key={task.id} task={task} locale={locale} />
        ))}
      </div>
    </section>
  )
}
