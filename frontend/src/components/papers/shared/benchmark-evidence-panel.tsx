"use client"

import { X } from "lucide-react"
import { methodName, taskName } from "@/lib/papers/format"
import type { Benchmark, BenchmarkRef, Locale, Paper, PaperBenchmarkResult, PaperMethod, PaperTask } from "@/lib/papers/types"

type BenchmarkEvidenceContext =
  | { type: "task"; task: PaperTask }
  | { type: "method"; method: PaperMethod }

export function BenchmarkEvidencePanel({
  benchmark,
  context,
  papers,
  locale,
  onClose,
  onPreviewPaper
}: {
  benchmark: BenchmarkRef | Benchmark
  context: BenchmarkEvidenceContext
  papers: Paper[]
  locale: Locale
  onClose: () => void
  onPreviewPaper: (paper: Paper) => void
}) {
  const matches = benchmarkPaperMatches(benchmark, papers)
  const category = benchmark.category ? benchmark.category : undefined
  const metric = "metric" in benchmark ? benchmark.metric : undefined
  const bestValue = "bestValue" in benchmark ? benchmark.bestValue : undefined
  const entryCount = matches.length

  return (
    <section className="rounded-md border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {locale === "zh" ? "评测证据" : "Benchmark Evidence"}
          </p>
          <h2 className="mt-2 text-lg font-semibold">{benchmark.name}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {contextDescription(context, locale)}
          </p>
        </div>
        <button
          type="button"
          className="rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
          aria-label={locale === "zh" ? "关闭评测证据" : "Close benchmark evidence"}
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <BenchmarkFact label={locale === "zh" ? "记录条目" : "Entries"} value={entryCount || matches.length || 0} />
        <BenchmarkFact label={locale === "zh" ? "指标" : "Metric"} value={metric ?? "Not recorded"} />
        <BenchmarkFact label={locale === "zh" ? "最佳值" : "Best Value"} value={bestValue ?? "Not recorded"} />
      </dl>
      {category ? (
        <p className="mt-3 text-xs text-muted-foreground">
          {locale === "zh" ? "类别" : "Category"}: {category}
        </p>
      ) : null}
      <div className="mt-4 space-y-3">
        <h3 className="text-sm font-semibold">{locale === "zh" ? "相关论文" : "Relevant Papers"}</h3>
        {matches.length ? (
          <div className="grid gap-2">
            {matches.map((match) => (
              <button
                key={match.paper.id}
                type="button"
                className="rounded-md border border-border bg-background/70 px-3 py-2 text-left text-sm hover:bg-secondary"
                onClick={() => onPreviewPaper(match.paper)}
              >
                <span className="block font-semibold">{match.paper.title}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{match.reason}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
            {emptyMessage(context, locale)}
          </p>
        )}
      </div>
    </section>
  )
}

function BenchmarkFact({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border bg-background/60 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm font-semibold">{value}</dd>
    </div>
  )
}

function contextDescription(context: BenchmarkEvidenceContext, locale: Locale) {
  if (context.type === "task") {
    return locale === "zh"
      ? `这里展示它和 ${taskName(context.task, locale)} 的真实关联：来自当前任务下论文记录的 benchmark 字段，以及论文标题或摘要中的直接提及。`
      : `This shows why it is tied to ${taskName(context.task, locale)} using recorded benchmark fields on papers in this task, plus direct title or abstract mentions.`
  }
  return locale === "zh"
    ? `这里展示它和 ${methodName(context.method, locale)} 的真实关联：来自当前方法下论文记录的 benchmark 字段，以及论文标题或摘要中的直接提及。`
    : `This shows why it is tied to ${methodName(context.method, locale)} using recorded benchmark fields on papers in this method, plus direct title or abstract mentions.`
}

function emptyMessage(context: BenchmarkEvidenceContext, locale: Locale) {
  if (context.type === "task") {
    return locale === "zh"
      ? "当前任务下没有论文记录这个 benchmark 的结构化结果或直接文本提及。"
      : "No paper under this task records a structured result or direct text mention for this benchmark yet."
  }
  return locale === "zh"
    ? "当前方法下没有论文记录这个 benchmark 的结构化结果或直接文本提及。"
    : "No paper under this method records a structured result or direct text mention for this benchmark yet."
}

function benchmarkPaperMatches(benchmark: BenchmarkRef | Benchmark, papers: Paper[]) {
  return papers.flatMap((paper) => {
    const result = (paper.benchmarks ?? []).find((item) => benchmarkResultMatches(item, benchmark))
    if (result) {
      const metric = result.metric ? `${result.metric}: ` : ""
      const value = result.value != null ? `${result.value}` : "recorded result"
      return [{ paper, reason: `${metric}${value}` }]
    }
    const text = `${paper.title} ${paper.abstractSnippet} ${paper.tags.join(" ")}`.toLocaleLowerCase()
    const terms = [benchmark.slug, benchmark.name].filter(Boolean).map((item) => item.toLocaleLowerCase())
    const matchedTerm = terms.find((term) => text.includes(term))
    return matchedTerm ? [{ paper, reason: `Mentioned in paper metadata: ${matchedTerm}` }] : []
  })
}

function benchmarkResultMatches(result: PaperBenchmarkResult, benchmark: BenchmarkRef | Benchmark) {
  const sameSlug = result.id === benchmark.id || slugifyBenchmarkName(result.name) === benchmark.slug
  const sameName = result.name.toLocaleLowerCase() === benchmark.name.toLocaleLowerCase()
  return sameSlug || sameName
}

function slugifyBenchmarkName(value: string) {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}
