"use client"

import { useState } from "react"
import { BenchmarkList } from "@/components/papers/tasks/benchmark-list"
import { CommonMethodsPanel } from "@/components/papers/tasks/common-methods-panel"
import { SisterTasksPanel } from "@/components/papers/tasks/sister-tasks-panel"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { ImplementationList } from "@/components/papers/shared/implementation-list"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { translate } from "@/lib/i18n"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatWholeNumber, taskDescription, taskName } from "@/lib/papers/format"
import { getBenchmarksForTask, getPapersForTask } from "@/lib/papers/catalog"
import { papersRoutes } from "@/lib/papers/routes"
import type { Benchmark, Locale, Paper, PaperTask } from "@/lib/papers/types"

export function TaskDetailPage({
  task,
  locale,
  papers,
  fallbackNotice
}: {
  task: PaperTask
  locale: Locale
  papers?: Paper[]
  fallbackNotice?: string | null
}) {
  const [notice, setNotice] = useState<string | null>(fallbackNotice ?? null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const taskPapers = papers?.filter((p) => (p.taskRefs ?? []).some((r) => r.slug === task.slug)) ?? getPapersForTask(task.slug)
  const taskBenchmarks = getBenchmarksForTask(task.slug)

  return (
    <div className="space-y-8">
      <PapersMicrobar
        items={[{ label: "Tasks", href: papersRoutes.tasks }, { label: task.name.toUpperCase() }]}
        meta={t(papersCopy.taskDetailMeta, locale)}
        locale={locale}
      />

      {/* Hero */}
      <section className="border-b border-[#d7dfd8] pb-9 pt-1 dark:border-border">
        <p className="text-[0.72rem] font-black uppercase tracking-[0.2em] text-emerald-700 dark:text-emerald-400">Task</p>
        <div className="mt-4 grid gap-8 lg:grid-cols-[minmax(0,1fr)_14rem] lg:items-start">
          {/* Left: title + description */}
          <div>
            <h1 className="max-w-5xl text-balance text-5xl font-black uppercase leading-[0.95] tracking-normal text-[#334155] sm:text-6xl lg:text-7xl dark:text-foreground">
              {taskName(task, locale)}
            </h1>
            <p className="mt-6 max-w-4xl text-lg leading-8 text-[#334155]/72 dark:text-muted-foreground">
              {taskDescription(task, locale)}
            </p>
          </div>
          {/* Right: stats */}
          <div className="flex flex-row gap-6 lg:flex-col lg:gap-0 lg:divide-y lg:divide-[#d7dfd8] dark:lg:divide-border">
            {[
              { label: t(papersCopy.papers, locale), value: taskPapers.length },
              { label: t(papersCopy.benchmarks, locale), value: taskBenchmarks.length || task.benchmarkCount },
              {
                label: t(papersCopy.methodsUsed, locale),
                value: new Set(taskPapers.flatMap((p) => (p.methodRefs ?? []).map((m) => m.slug))).size || task.methodCount
              }
            ].map((stat) => (
              <div key={stat.label} className="lg:py-4 first:lg:pt-0 last:lg:pb-0">
                <p className="text-4xl font-black leading-none text-[#334155] dark:text-foreground">
                  {formatWholeNumber(stat.value, locale)}
                </p>
                <p className="mt-1.5 text-[0.66rem] font-black uppercase tracking-[0.14em] text-[#334155]/55 dark:text-muted-foreground">
                  {stat.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />

      {/* Main content + sidebar */}
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_19rem]">
        <main className="space-y-6">
          <PaperStream
            papers={taskPapers}
            locale={locale}
            title={t(papersCopy.papersUnderTask, locale)}
            onPreview={(p) => setSelectedPaper(p)}
          />
          <BenchmarkList benchmarks={taskBenchmarks} task={task} locale={locale} onSelect={(b) => setNotice(`${b.name}: ${t(papersCopy.benchmarkPreview, locale)}`)} />
          <ImplementationList papers={taskPapers} locale={locale} title={translate(locale, "papers.reader.implementations")} />
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
        onOpenChange={(open) => { if (!open) setSelectedPaper(null) }}
      />
    </div>
  )
}
