"use client"

import { useState } from "react"
import { BenchmarkList } from "@/components/papers/tasks/benchmark-list"
import { CommonMethodsPanel } from "@/components/papers/tasks/common-methods-panel"
import { SisterTasksPanel } from "@/components/papers/tasks/sister-tasks-panel"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskDescription, taskName } from "@/lib/papers/format"
import { getBenchmarksForTask, getPapersForTask } from "@/lib/papers/catalog"
import { papersRoutes } from "@/lib/papers/routes"
import type { Benchmark, Locale, Paper, PaperTask } from "@/lib/papers/types"

export function TaskDetailPage({ task, locale, papers }: { task: PaperTask; locale: Locale; papers?: Paper[] }) {
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const taskPapers = papers?.filter((paper) => (paper.taskRefs ?? []).some((taskRef) => taskRef.slug === task.slug)) ?? getPapersForTask(task.slug)
  const taskBenchmarks = getBenchmarksForTask(task.slug)

  function previewPaper(paper: Paper) {
    setSelectedPaper(paper)
  }

  function previewBenchmark(benchmark: Benchmark) {
    setNotice(`${benchmark.name}: ${t(papersCopy.benchmarkPreview, locale)}`)
  }

  return (
    <div className="space-y-8">
      <PapersMicrobar
        items={[{ label: "Tasks", href: papersRoutes.tasks }, { label: task.name.toUpperCase() }]}
        meta={t(papersCopy.taskDetailMeta, locale)}
        locale={locale}
      />
      <TaskDetailHero task={task} taskPapers={taskPapers} benchmarks={taskBenchmarks} locale={locale} />
      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_19rem]">
        <main className="space-y-6">
          <BenchmarkList benchmarks={taskBenchmarks} task={task} locale={locale} onSelect={previewBenchmark} />
          <PaperStream papers={taskPapers} locale={locale} title={t(papersCopy.papersUnderTask, locale)} onPreview={previewPaper} />
        </main>
        <aside className="space-y-8 border-t border-[#d7dfd8] pt-6 xl:sticky xl:top-24 xl:self-start xl:border-t-0 xl:pt-0 dark:border-border">
          <SisterTasksPanel tasks={task.sisterTasks} locale={locale} />
          <CommonMethodsPanel methods={task.commonMethods} locale={locale} />
        </aside>
      </div>
      <PaperDetailDrawer
        paper={selectedPaper}
        locale={locale}
        open={Boolean(selectedPaper)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedPaper(null)
          }
        }}
      />
    </div>
  )
}

function TaskDetailHero({
  task,
  taskPapers,
  benchmarks,
  locale
}: {
  task: PaperTask
  taskPapers: Paper[]
  benchmarks: Benchmark[]
  locale: Locale
}) {
  const methodsUsed = new Set(taskPapers.flatMap((paper) => (paper.methodRefs ?? []).map((method) => method.slug))).size || task.methodCount
  const statItems = [
    { label: t(papersCopy.papers, locale), value: taskPapers.length },
    { label: t(papersCopy.benchmarks, locale), value: benchmarks.length || task.benchmarkCount },
    { label: t(papersCopy.methodsUsed, locale), value: methodsUsed }
  ]

  return (
    <section className="border-b border-[#d7dfd8] pb-9 pt-1 dark:border-border">
      <p className="text-[0.72rem] font-black uppercase tracking-[0.2em] text-emerald-700 dark:text-emerald-400">Task</p>
      <div className="mt-4 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-end">
        <div>
          <h1 className="max-w-5xl text-balance text-5xl font-black uppercase leading-[0.95] tracking-normal text-[#334155] sm:text-6xl lg:text-7xl dark:text-foreground">
            {taskName(task, locale)}
          </h1>
          <p className="mt-6 max-w-4xl text-lg leading-8 text-[#334155]/72 dark:text-muted-foreground">
            {taskDescription(task, locale)}
          </p>
        </div>
        <div className="grid grid-cols-3 gap-4 lg:grid-cols-1 lg:gap-3">
          {statItems.map((stat) => (
            <div key={stat.label} className="border-l border-[#cfd9d1] pl-4 dark:border-border">
              <p className="text-2xl font-black leading-none text-[#334155] dark:text-foreground">
                {formatWholeNumber(stat.value, locale)}
              </p>
              <p className="mt-1 text-[0.66rem] font-black uppercase tracking-[0.14em] text-[#334155]/55 dark:text-muted-foreground">
                {stat.label}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
