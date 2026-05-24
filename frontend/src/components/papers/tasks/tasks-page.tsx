import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { TaskSection } from "@/components/papers/tasks/task-section"
import { papersCopy, taskGroupLabels, t } from "@/lib/papers/copy"
import { benchmarks, papers, paperTasks } from "@/lib/papers/mock-data"
import type { Locale } from "@/lib/papers/types"

const taskGroups = ["general", "vision", "video", "language", "audio", "robotics", "infra"]

export function TasksPage({ locale }: { locale: Locale }) {
  return (
    <div className="space-y-6">
      <PapersMicrobar items={[{ label: "Tasks" }]} meta={t(papersCopy.taskBranch, locale)} locale={locale} />
      <PapersHero
        eyebrow="Papers / Tasks"
        title={t(papersCopy.tasks, locale)}
        subtitle={t(papersCopy.tasksSubtitle, locale)}
        stats={[
          { label: t(papersCopy.tasks, locale), value: paperTasks.length },
          { label: t(papersCopy.papers, locale), value: papers.length },
          { label: t(papersCopy.benchmarks, locale), value: benchmarks.length }
        ]}
      />
      <div className="space-y-6">
        {taskGroups.map((group) => (
          <TaskSection
            key={group}
            title={t(taskGroupLabels[group], locale, group)}
            tasks={paperTasks.filter((task) => task.group === group)}
            locale={locale}
          />
        ))}
      </div>
    </div>
  )
}
