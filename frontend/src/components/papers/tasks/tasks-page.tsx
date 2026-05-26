"use client"

import { useEffect, useState } from "react"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { TaskSection } from "@/components/papers/tasks/task-section"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { papersCopy, taskGroupLabels, t } from "@/lib/papers/copy"
import { benchmarks, paperTasks } from "@/lib/papers/catalog"
import { fetchPaperTasksResult, fetchPapers } from "@/lib/papers/api"
import type { Locale, Paper, PaperTask } from "@/lib/papers/types"

const taskGroups = ["general", "vision", "video", "language", "audio", "robotics", "infra"]

export function TasksPage({ locale }: { locale: Locale }) {
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [notice, setNotice] = useState<string | null>(null)
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)

  useEffect(() => {
    let active = true
    Promise.all([fetchPaperTasksResult(), fetchPapers({ limit: 1000, period: "all" })])
      .then(([apiTasks, apiPapers]) => {
        if (!active) {
          return
        }
        setTasks(apiTasks.tasks)
        setPaperItems(apiPapers.papers)
        setNotice(apiTasks.notices?.[0] ?? null)
        setStatus(apiTasks.dataState === "ready" || !apiTasks.dataState ? "ready" : "fallback")
      })
      .catch(() => {
        if (!active) {
          return
        }
        setTasks(emptyTaskCounts(paperTasks))
        setPaperItems([])
        setNotice(t(papersCopy.taskApiFallback, locale))
        setStatus("fallback")
      })
    return () => {
      active = false
    }
  }, [locale])

  const taskItems = status === "loading" ? [] : tasks
  const taskPaperItems = status === "loading" ? [] : paperItems
  const benchmarkCount = status === "fallback" ? benchmarks.length : taskItems.reduce((total, task) => total + task.benchmarkCount, 0)

  return (
    <div className="space-y-6">
      <PapersMicrobar items={[{ label: "Tasks" }]} meta={t(papersCopy.taskBranch, locale)} locale={locale} />
      <PapersHero
        eyebrow=""
        title={t(papersCopy.tasks, locale)}
        subtitle={t(papersCopy.tasksSubtitle, locale)}
        stats={[
          { label: t(papersCopy.tasks, locale), value: taskItems.length },
          { label: t(papersCopy.papers, locale), value: taskPaperItems.length },
          { label: t(papersCopy.benchmarks, locale), value: benchmarkCount }
        ]}
      />
      {status === "fallback" ? (
        <InlineNotice
          message={fallbackNoticeVisible ? notice ?? t(papersCopy.taskApiFallback, locale) : null}
          locale={locale}
          onDismiss={() => setFallbackNoticeVisible(false)}
        />
      ) : null}
      <div className="space-y-6">
        {status === "loading" ? (
          <p className="text-sm text-[#334155]/60 dark:text-muted-foreground">{t(papersCopy.loadingTasks, locale)}</p>
        ) : null}
        {status !== "loading" && taskItems.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-6 text-sm text-muted-foreground">
            {t(papersCopy.noPapers, locale)}
          </p>
        ) : null}
        {taskGroups.map((group) => (
          <TaskSection
            key={group}
            title={t(taskGroupLabels[group], locale, group)}
            tasks={taskItems.filter((task) => task.group === group)}
            locale={locale}
          />
        ))}
      </div>
    </div>
  )
}

function emptyTaskCounts(tasks: PaperTask[]): PaperTask[] {
  return tasks.map((task) => ({
    ...task,
    paperCount: 0,
    benchmarkCount: 0,
    methodCount: 0,
    latestPaperIds: [],
    implementationCount: 0
  }))
}
