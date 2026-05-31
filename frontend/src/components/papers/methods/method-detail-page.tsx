"use client"

import { useState } from "react"
import { CommonBenchmarksPanel } from "@/components/papers/methods/common-benchmarks-panel"
import { RelatedMethodsPanel } from "@/components/papers/methods/related-methods-panel"
import { RelatedTasksPanel } from "@/components/papers/methods/related-tasks-panel"
import { PapersHero } from "@/components/papers/papers-hero"
import { PapersMicrobar } from "@/components/papers/papers-microbar"
import { BenchmarkEvidencePanel } from "@/components/papers/shared/benchmark-evidence-panel"
import { InlineNotice } from "@/components/papers/shared/inline-notice"
import { ImplementationList } from "@/components/papers/shared/implementation-list"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { PaperStream } from "@/components/papers/shared/paper-stream"
import { translate } from "@/lib/i18n"
import { papersCopy, t } from "@/lib/papers/copy"
import { methodDescription, methodName } from "@/lib/papers/format"
import { getBenchmarksForMethod, getPapersForMethod } from "@/lib/papers/catalog"
import { papersRoutes } from "@/lib/papers/routes"
import type { Benchmark, BenchmarkRef, Locale, Paper, PaperMethod } from "@/lib/papers/types"

export function MethodDetailPage({
  method,
  locale,
  papers,
  fallbackNotice
}: {
  method: PaperMethod
  locale: Locale
  papers?: Paper[]
  fallbackNotice?: string | null
}) {
  const [notice, setNotice] = useState<string | null>(fallbackNotice ?? null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const [selectedBenchmark, setSelectedBenchmark] = useState<BenchmarkRef | Benchmark | null>(null)
  const methodPapers = papers?.filter((paper) => (paper.methodRefs ?? []).some((methodRef) => methodRef.slug === method.slug)) ?? getPapersForMethod(method.slug)
  const methodBenchmarks = getBenchmarksForMethod(method.slug)
  const commonBenchmarks = method.commonBenchmarks?.length ? method.commonBenchmarks : methodBenchmarks
  const methodStats = deriveMethodDetailStats(method, methodPapers)

  function previewPaper(paper: Paper) {
    setSelectedPaper(paper)
  }

  function previewBenchmark(benchmark: BenchmarkRef | Benchmark) {
    setSelectedBenchmark(benchmark)
    if (notice && notice !== fallbackNotice) {
      setNotice(null)
    }
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
          { label: t(papersCopy.papers, locale), value: methodStats.paperCount },
          { label: t(papersCopy.tasks, locale), value: methodStats.taskCount },
          { label: t(papersCopy.implementations, locale), value: methodStats.implementationCount }
        ]}
      />
      <InlineNotice message={notice} locale={locale} onDismiss={() => setNotice(null)} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <main className="space-y-6">
          {selectedBenchmark ? (
            <BenchmarkEvidencePanel
              benchmark={selectedBenchmark}
              context={{ type: "method", method }}
              papers={methodPapers}
              locale={locale}
              onClose={() => setSelectedBenchmark(null)}
              onPreviewPaper={previewPaper}
            />
          ) : null}
          <RelatedTasksPanel tasks={method.relatedTasks} locale={locale} />
          <ImplementationList papers={methodPapers} locale={locale} title={translate(locale, "papers.reader.projects")} />
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

function deriveMethodDetailStats(method: PaperMethod, papers: Paper[]) {
  const taskCount =
    new Set(papers.flatMap((paper) => (paper.taskRefs ?? []).map((task) => task.slug))).size ||
    method.taskCount
  const implementationCount =
    countImplementationsFromPapers(papers)

  return {
    paperCount: papers.length,
    taskCount,
    implementationCount,
  }
}

function countImplementationsFromPapers(papers: Paper[]) {
  const seen = new Set<string>()
  for (const paper of papers) {
    const implementations = paper.implementations?.length
      ? paper.implementations
      : paper.repoUrl?.startsWith("https://github.com/")
        ? [{ repoUrl: paper.repoUrl }]
        : []
    for (const implementation of implementations) {
      if (implementation.repoUrl) {
        seen.add(implementation.repoUrl)
      }
    }
  }
  return seen.size
}
