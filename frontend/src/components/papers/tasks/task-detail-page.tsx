"use client"

import { useState } from "react"
import { BenchmarkList } from "@/components/papers/tasks/benchmark-list"
import { CommonMethodsPanel } from "@/components/papers/tasks/common-methods-panel"
import { SisterTasksPanel } from "@/components/papers/tasks/sister-tasks-panel"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { papersCopy, t } from "@/lib/papers/copy"
import { taskDescription, taskName } from "@/lib/papers/format"
import { getBenchmarksForTask, getPapersForTask } from "@/lib/papers/catalog"
import { papersRoutes } from "@/lib/papers/routes"
import type { Benchmark, Locale, Paper, PaperTask } from "@/lib/papers/types"

export function TaskDetailPage({ task, locale, papers }: { task: PaperTask; locale: Locale; papers?: Paper[] }) {
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const taskPapers = papers?.filter((paper) => paper.taskRefs.some((taskRef) => taskRef.slug === task.slug)) ?? getPapersForTask(task.slug)
  const taskBenchmarks = getBenchmarksForTask(task.slug)

  function previewPaper(paper: Paper) {
    setSelectedPaper(paper)
  }

  function previewBenchmark(benchmark: Benchmark) {
    setNotice(`${benchmark.name}: ${t(papersCopy.benchmarkPreview, locale)}`)
  }

  return (
    <div className="space-y-6">
      <PapersMicrobar
        items={[{ label: "Tasks", href: papersRoutes.tasks }, { label: task.name.toUpperCase() }]}
        meta={t(papersCopy.taskDetailMeta, locale)}
        locale={locale}
      />
      <PapersHero
        eyebrow="Task"
        title={taskName(task, locale).toUpperCase()}
        subtitle={taskDescription(task, locale)}
        stats={[
          { label: t(papersCopy.papers, locale), value: task.paperCount },
          { label: t(papersCopy.benchmarks, locale), value: task.benchmarkCount },
          { label: t(papersCopy.methodsUsed, locale), value: task.methodCount }
        ]}
      />
      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <main className="space-y-6">
          <BenchmarkList benchmarks={taskBenchmarks} locale={locale} onSelect={previewBenchmark} />
          <PaperStream papers={taskPapers} locale={locale} title={t(papersCopy.papersUnderTask, locale)} onPreview={previewPaper} />
        </main>
        <aside className="space-y-6 xl:sticky xl:top-24 xl:self-start">
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
