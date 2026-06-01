"use client"

import { useEffect, useState } from "react"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { TaskSection } from "@/components/papers/tasks/task-section"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { Button } from "@/components/ui/button"
import { orderedTaskGroups, taskGroupLabel } from "@/lib/papers/categories"
import { localizedResearchNotice, papersCopy, t } from "@/lib/papers/copy"
import { fetchPaperTasksResult, fetchPapers } from "@/lib/papers/api"
import type { Locale, Paper, PaperTask } from "@/lib/papers/types"

type TaxonomySort = "paper_count" | "recent" | "benchmark"

export function TasksPage({ locale }: { locale: Locale }) {
  const [tasks, setTasks] = useState<PaperTask[]>([])
  const [paperItems, setPaperItems] = useState<Paper[]>([])
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading")
  const [notice, setNotice] = useState<string | null>(null)
  const [fallbackNoticeVisible, setFallbackNoticeVisible] = useState(true)
  const [sort, setSort] = useState<TaxonomySort>("paper_count")

  useEffect(() => {
    let active = true
    Promise.allSettled([fetchPaperTasksResult(), fetchPapers({ limit: 5000, period: "all" })])
      .then(([tasksResult, papersResult]) => {
        if (!active) {
          return
        }

        const publicPaperItems = papersResult.status === "fulfilled" ? publicPapers(papersResult.value.papers) : []

        if (tasksResult.status === "rejected") {
          setTasks([])
          setPaperItems(publicPaperItems)
          setNotice(t(papersCopy.taskApiFallback, locale))
          setStatus("fallback")
          return
        }

        setTasks(tasksResult.value.tasks.filter((task) => task.paperCount > 0))
        setPaperItems(publicPaperItems)
        setNotice(combineNotices([
          localizedResearchNotice(tasksResult.value.notices?.[0] ?? null, locale),
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

  const taskItems = status === "loading" ? [] : sortTasks(tasks.filter((task) => task.paperCount > 0), paperItems, sort)
  const taskPaperItems = status === "loading" ? [] : paperItems.filter((paper) => (paper.taskRefs ?? []).length > 0)
  const taskPaperCount = taskPaperItems.length || paperCountFromTasks(taskItems)
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
          { label: t(papersCopy.papers, locale), value: taskPaperCount },
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
        {status !== "loading" && taskItems.length > 0 ? (
          <TaxonomySortControls value={sort} locale={locale} onChange={setSort} />
        ) : null}
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

function publicPapers(papers: Paper[]) {
  return papers.filter((paper) => paper.isPublished !== false)
}

function paperCountFromTasks(tasks: PaperTask[]) {
  const ids = new Set(tasks.flatMap((task) => task.latestPaperIds ?? []))
  return ids.size || tasks.reduce((total, task) => total + task.paperCount, 0)
}

function paperListUnavailableNotice(locale: Locale) {
  return locale === "zh"
    ? "论文列表正在刷新；任务目录仍使用已验证分类。"
    : "Paper list is refreshing; task taxonomy remains available from verified data."
}

function combineNotices(notices: Array<string | null | undefined>) {
  const uniqueNotices = [...new Set(notices.filter((notice): notice is string => Boolean(notice)))]
  return uniqueNotices.length ? uniqueNotices.join(" ") : null
}

function TaxonomySortControls({
  value,
  locale,
  onChange
}: {
  value: TaxonomySort
  locale: Locale
  onChange: (value: TaxonomySort) => void
}) {
  const items: TaxonomySort[] = ["paper_count", "recent", "benchmark"]
  return (
    <div className="flex gap-2 overflow-x-auto" aria-label={locale === "zh" ? "任务排序" : "Task sorting"}>
      {items.map((item) => (
        <Button
          key={item}
          type="button"
          variant={item === value ? "default" : "outline"}
          size="sm"
          className="h-8 shrink-0 rounded-full px-3 text-xs shadow-none"
          onClick={() => onChange(item)}
        >
          {sortLabel(item, locale)}
        </Button>
      ))}
    </div>
  )
}

function sortTasks(tasks: PaperTask[], papers: Paper[], sort: TaxonomySort) {
  const latestByTask = latestPaperTimeBySlug(papers, "task")
  return [...tasks].sort((left, right) => {
    if (sort === "recent") {
      return (latestByTask.get(right.slug) ?? 0) - (latestByTask.get(left.slug) ?? 0) || right.paperCount - left.paperCount
    }
    if (sort === "benchmark") {
      return right.benchmarkCount - left.benchmarkCount || right.paperCount - left.paperCount
    }
    return right.paperCount - left.paperCount || left.name.localeCompare(right.name)
  })
}

function latestPaperTimeBySlug(papers: Paper[], kind: "task" | "method") {
  const records = new Map<string, number>()
  for (const paper of publicPapers(papers)) {
    const time = new Date(paper.publishedAt).getTime()
    if (!Number.isFinite(time)) {
      continue
    }
    const refs = kind === "task" ? paper.taskRefs : paper.methodRefs
    for (const ref of refs ?? []) {
      records.set(ref.slug, Math.max(records.get(ref.slug) ?? 0, time))
    }
  }
  return records
}

function sortLabel(value: TaxonomySort, locale: Locale) {
  if (value === "recent") return locale === "zh" ? "最近更新" : "Recent"
  if (value === "benchmark") return locale === "zh" ? "有评测" : "Benchmarks"
  return locale === "zh" ? "按论文数" : "Paper count"
}
