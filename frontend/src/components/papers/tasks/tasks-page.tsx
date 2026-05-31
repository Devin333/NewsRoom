"use client"

import { useEffect, useState } from "react"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { TaskSection } from "@/components/papers/tasks/task-section"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { orderedTaskGroups, taskGroupLabel } from "@/lib/papers/categories"
import { papersCopy, t } from "@/lib/papers/copy"
import { paperTasks } from "@/lib/papers/catalog"
import { fetchPaperTasksResult, fetchPapers } from "@/lib/papers/api"
import { deriveTasksFromPapers } from "@/lib/papers/taxonomy-fallback"
import type { Locale, Paper, PaperTask } from "@/lib/papers/types"

export function TasksPage({ locale }: { locale: Locale }) {
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [notice, setNotice] = useState<string | null>(null)
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)

  useEffect(() => {
    let active = true
    Promise.allSettled([fetchPaperTasksResult(), fetchPapers({ limit: 5000, period: "all" })])
      .then(([tasksResult, papersResult]) => {
        if (!active) {
          return
        }

        if (tasksResult.status === "rejected") {
          setTasks(papersResult.status === "fulfilled" ? deriveTasksFromPapers(paperTasks, papersResult.value.papers) : emptyTaskCounts(paperTasks))
          setPaperItems(papersResult.status === "fulfilled" ? papersResult.value.papers : [])
          setNotice(t(papersCopy.taskApiFallback, locale))
          setStatus("fallback")
          return
        }

        setTasks(tasksResult.value.tasks)
        setPaperItems(papersResult.status === "fulfilled" ? papersResult.value.papers : [])
        setNotice(combineNotices([
          tasksResult.value.notices?.[0] ?? null,
          papersResult.status === "rejected" ? paperListUnavailableNotice(locale) : null
        ]))
        setStatus(
          (tasksResult.value.dataState === "ready" || !tasksResult.value.dataState) && papersResult.status === "fulfilled"
            ? "ready"
            : "fallback"
        )
      })
    return () => {
      active = false
    }
  }, [locale])

  const taskItems = status === "loading" ? [] : tasks
  const taskPaperItems = status === "loading" ? [] : paperItems
  const benchmarkCount = taskItems.reduce((total, task) => total + task.benchmarkCount, 0)
  const visibleTaskGroups = orderedTaskGroups(taskItems)

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
        {visibleTaskGroups.map((group) => (
          <TaskSection
            key={group}
            title={taskGroupLabel(group, locale)}
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

function paperListUnavailableNotice(locale: Locale) {
  return locale === "zh"
    ? "论文列表 API 暂不可用；任务目录保留真实分类数据，论文统计暂时不可用。"
    : "Paper list API is unavailable; task taxonomy remains live, but paper totals are temporarily unavailable."
}

function combineNotices(notices: Array<string | null | undefined>) {
  const uniqueNotices = [...new Set(notices.filter((notice): notice is string => Boolean(notice)))]
  return uniqueNotices.length ? uniqueNotices.join(" ") : null
}
