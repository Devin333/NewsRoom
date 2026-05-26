"use client"

import { ArrowRight, Layers3 } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import { taskName } from "@/lib/papers/format"
import type { Benchmark, Locale, MethodRef, PaperTask, TaskRef } from "@/lib/papers/types"

export function BenchmarkList({
  benchmarks,
  task,
  locale,
  onSelect
}: {
  benchmarks: Benchmark[]
  task: PaperTask
  locale: Locale
  onSelect: (benchmark: Benchmark) => void
}) {
  const visibleItems = benchmarks.length ? benchmarkItems(benchmarks) : branchItems(task)

  return (
    <section className="border-t border-[#d7dfd8] pt-6 dark:border-border">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <p className="text-[0.68rem] font-black uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-400">
            01/
          </p>
          <h2 className="mt-2 text-xl font-black text-[#334155] dark:text-foreground">
            {benchmarks.length ? t(papersCopy.benchmarksTitle, locale) : t(papersCopy.taskBranches, locale)}
          </h2>
        </div>
        <p className="hidden max-w-sm text-right text-xs leading-5 text-[#334155]/55 sm:block dark:text-muted-foreground">
          {benchmarks.length
            ? t(papersCopy.benchmarkEntryHelp, locale)
            : t(papersCopy.taskBranchHelp, locale)}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visibleItems.map((item, index) => (
          <button
            key={item.id}
            type="button"
            className="group min-h-32 rounded-md border border-[#d7dfd8] bg-white/55 p-4 text-left transition-colors hover:border-emerald-300 hover:bg-[#f3f8f4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/45 dark:border-border dark:bg-card dark:hover:bg-secondary"
            onClick={() => onSelect(item.benchmark)}
          >
            <span className="flex items-start justify-between gap-3">
              <span className="flex size-9 items-center justify-center rounded-md bg-[#e7f1eb] text-emerald-700 dark:bg-secondary dark:text-emerald-400">
                <Layers3 className="size-4" />
              </span>
              <span className="text-[0.68rem] font-black text-[#334155]/50 dark:text-muted-foreground">
                {String(index + 1).padStart(2, "0")}
              </span>
            </span>
            <span className="mt-5 block text-base font-black leading-5 text-[#334155] dark:text-foreground">
              {item.name}
            </span>
            <span className="mt-3 flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-[0.12em] text-[#334155]/55 dark:text-muted-foreground">
              <span>{item.meta}</span>
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

type BenchmarkCardItem = {
  id: string
  name: string
  meta: string
  benchmark: Benchmark
}

function benchmarkItems(benchmarks: Benchmark[]): BenchmarkCardItem[] {
  return benchmarks.map((benchmark) => ({
    id: benchmark.id,
    name: benchmark.name,
    meta: `${benchmark.entryCount} entries`,
    benchmark
  }))
}

function branchItems(task: PaperTask): BenchmarkCardItem[] {
  const taskBranches = task.sisterTasks.slice(0, 3).map((taskRef) => taskBranchItem(task, taskRef))
  const methodBranches = task.commonMethods.slice(0, 3).map((methodRef) => methodBranchItem(task, methodRef))
  return [...taskBranches, ...methodBranches]
}

function taskBranchItem(task: PaperTask, taskRef: TaskRef): BenchmarkCardItem {
  return {
    id: `${task.id}-${taskRef.id}`,
    name: taskName(taskRef, "en"),
    meta: "task branch",
    benchmark: {
      id: `${task.id}-${taskRef.id}`,
      slug: taskRef.slug,
      name: taskName(taskRef, "en"),
      taskSlug: task.slug,
      entryCount: task.paperCount
    }
  }
}

function methodBranchItem(task: PaperTask, methodRef: MethodRef): BenchmarkCardItem {
  return {
    id: `${task.id}-${methodRef.id}`,
    name: methodRef.name,
    meta: "method branch",
    benchmark: {
      id: `${task.id}-${methodRef.id}`,
      slug: methodRef.slug,
      name: methodRef.name,
      taskSlug: task.slug,
      entryCount: task.methodCount
    }
  }
}
