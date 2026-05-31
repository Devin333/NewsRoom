"use client"

import { useState } from "react"
import { BenchmarkList } from "@/components/papers/tasks/benchmark-list"
import { CommonMethodsPanel } from "@/components/papers/tasks/common-methods-panel"
import { SisterTasksPanel } from "@/components/papers/tasks/sister-tasks-panel"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { BenchmarkEvidencePanel, benchmarkPaperMatches } from "@/components/papers/shared/benchmark-evidence-panel"
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
  const [selectedBenchmark, setSelectedBenchmark] = useState<Benchmark | null>(null)

  const taskPapers = papers?.filter(
    (p) => p.isPublished !== false && (p.taskRefs ?? []).some((r) => r.slug === task.slug)
  ) ?? getPapersForTask(task.slug)

  const taskBenchmarks = getBenchmarksForTask(task.slug).map((benchmark) => ({
    ...benchmark,
    entryCount: benchmarkPaperMatches(benchmark, taskPapers).length
  }))
  const taskStats = deriveTaskDetailStats(taskPapers, taskBenchmarks)

  function previewBenchmark(benchmark: Benchmark) {
    setSelectedBenchmark(benchmark)
    if (notice && notice !== fallbackNotice) {
      setNotice(null)
    }
  }

  return (
    <div className="space-y-8">
      <PapersMicrobar
        items={[{ label: "Tasks", href: papersRoutes.tasks }, { label: task.name.toUpperCase() }]}
        meta={t(papersCopy.taskDetailMeta, locale)}
        locale={locale}
      />

      {/* Hero */}
      <section className="border-b border-[#d7dfd8] pb-8 pt-1 dark:border-border">
        <p className="text-[0.72rem] font-black uppercase tracking-[0.2em] text-emerald-700 dark:text-emerald-400">
          Task
        </p>
        <h1 className="mt-3 max-w-5xl text-balance text-5xl font-black uppercase leading-[0.95] tracking-normal text-[#334155] sm:text-6xl lg:text-7xl dark:text-foreground">
          {taskName(task, locale)}
        </h1>
        <p className="mt-5 max-w-3xl text-base leading-7 text-[#334155]/70 dark:text-muted-foreground">
          {taskDescription(task, locale)}
        </p>
        {/* Inline stats — Papers with Code style */}
        <p className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-[#334155]/60 dark:text-muted-foreground">
          <span>
            <strong className="font-black text-[#334155] dark:text-foreground">
              {formatWholeNumber(taskPapers.length, locale)}
            </strong>{" "}
            <span className="text-[0.72rem] font-black uppercase tracking-[0.12em]">
              {t(papersCopy.papers, locale)}
            </span>
          </span>
          <span aria-hidden="true" className="text-[#d7dfd8]">·</span>
          <span>
            <strong className="font-black text-[#334155] dark:text-foreground">
              {formatWholeNumber(taskStats.benchmarkCount, locale)}
            </strong>{" "}
            <span className="text-[0.72rem] font-black uppercase tracking-[0.12em]">
              {t(papersCopy.benchmarks, locale)}
            </span>
          </span>
          <span aria-hidden="true" className="text-[#d7dfd8]">·</span>
          <span>
            <strong className="font-black text-[#334155] dark:text-foreground">
              {formatWholeNumber(taskStats.methodCount, locale)}
            </strong>{" "}
            <span className="text-[0.72rem] font-black uppercase tracking-[0.12em]">
              {t(papersCopy.methodsUsed, locale)}
            </span>
          </span>
        </p>
      </section>

      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />

      {/* Main + sidebar */}
      <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_19rem]">
        <main className="space-y-10">
          {selectedBenchmark ? (
            <BenchmarkEvidencePanel
              benchmark={selectedBenchmark}
              context={{ type: "task", task }}
              papers={taskPapers}
              locale={locale}
              onClose={() => setSelectedBenchmark(null)}
              onPreviewPaper={(paper) => setSelectedPaper(paper)}
            />
          ) : null}
          <BenchmarkList
            benchmarks={taskBenchmarks}
            task={task}
            locale={locale}
            onSelect={previewBenchmark}
          />
          <PaperStream
            papers={taskPapers}
            locale={locale}
            title={t(papersCopy.papersUnderTask, locale)}
            onPreview={(p) => setSelectedPaper(p)}
          />
          <ImplementationList
            papers={taskPapers}
            locale={locale}
            title={translate(locale, "papers.reader.implementations")}
          />
        </main>

        <aside className="space-y-0 border-t border-[#d7dfd8] pt-6 xl:sticky xl:top-24 xl:self-start xl:border-t-0 xl:pt-0 dark:border-border">
          <SisterTasksPanel tasks={task.sisterTasks} papers={papers ?? []} locale={locale} />
          <CommonMethodsPanel methods={task.commonMethods} papers={papers ?? []} locale={locale} />
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

function deriveTaskDetailStats(papers: Paper[], taskBenchmarks: Benchmark[]) {
  const benchmarkCount = taskBenchmarks.length
    ? taskBenchmarks.filter((benchmark) => (benchmark.entryCount ?? 0) > 0).length
    : countBenchmarksFromPapers(papers)
  const methodCount = new Set(papers.flatMap((paper) => (paper.methodRefs ?? []).map((method) => method.slug))).size

  return {
    benchmarkCount,
    methodCount,
  }
}

function countBenchmarksFromPapers(papers: Paper[]) {
  const seen = new Set<string>()
  for (const paper of papers) {
    for (const benchmark of paper.benchmarks ?? []) {
      seen.add(benchmark.id || benchmark.name)
    }
  }
  return seen.size
}
