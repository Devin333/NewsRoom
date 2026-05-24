"use client"

import { useState } from "react"
import { CommonBenchmarksPanel } from "@/components/papers/methods/common-benchmarks-panel"
import { RelatedMethodsPanel } from "@/components/papers/methods/related-methods-panel"
import { RelatedTasksPanel } from "@/components/papers/methods/related-tasks-panel"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { papersCopy, t } from "@/lib/papers/copy"
import { methodDescription, methodName } from "@/lib/papers/format"
import { getBenchmarksForMethod, getPapersForMethod } from "@/lib/papers/catalog"
import { papersRoutes } from "@/lib/papers/routes"
import type { Benchmark, BenchmarkRef, Locale, Paper, PaperMethod } from "@/lib/papers/types"

export function MethodDetailPage({ method, locale, papers }: { method: PaperMethod; locale: Locale; papers?: Paper[] }) {
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const methodPapers = papers?.filter((paper) => paper.methodRefs.some((methodRef) => methodRef.slug === method.slug)) ?? getPapersForMethod(method.slug)
  const methodBenchmarks = getBenchmarksForMethod(method.slug)
  const commonBenchmarks = method.commonBenchmarks?.length ? method.commonBenchmarks : methodBenchmarks

  function previewPaper(paper: Paper) {
    setSelectedPaper(paper)
  }

  function previewBenchmark(benchmark: BenchmarkRef | Benchmark) {
    setNotice(`${benchmark.name}: ${t(papersCopy.benchmarkPreview, locale)}`)
  }

  return (
    <div className="space-y-6">
      <PapersMicrobar
        items={[{ label: "Methods", href: papersRoutes.methods }, { label: method.name }]}
        meta={t(papersCopy.methodDetailMeta, locale)}
        locale={locale}
      />
      <PapersHero
        eyebrow="Method"
        title={methodName(method, locale)}
        subtitle={methodDescription(method, locale)}
        stats={[
          { label: t(papersCopy.papers, locale), value: method.paperCount },
          { label: t(papersCopy.tasks, locale), value: method.taskCount },
          { label: t(papersCopy.implementations, locale), value: method.implementationCount ?? 0 }
        ]}
      />
      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <main className="space-y-6">
          <RelatedTasksPanel tasks={method.relatedTasks} locale={locale} />
          <PaperStream papers={methodPapers} locale={locale} title={t(papersCopy.papersUsingMethod, locale)} onPreview={previewPaper} />
        </main>
        <aside className="space-y-6 xl:sticky xl:top-24 xl:self-start">
          <RelatedMethodsPanel methods={method.relatedMethods} locale={locale} />
          <CommonBenchmarksPanel benchmarks={commonBenchmarks} locale={locale} onSelect={previewBenchmark} />
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
