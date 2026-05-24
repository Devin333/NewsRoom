"use client"

import { ArrowRight } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Benchmark, BenchmarkRef, Locale } from "@/lib/papers/types"

export function CommonBenchmarksPanel({
  benchmarks,
  locale,
  onSelect
}: {
  benchmarks: Array<BenchmarkRef | Benchmark>
  locale: Locale
  onSelect: (benchmark: BenchmarkRef | Benchmark) => void
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{t(papersCopy.commonBenchmarks, locale)}</h2>
      <div className="mt-3 grid gap-2">
        {benchmarks.map((benchmark) => (
          <button
            key={benchmark.id}
            type="button"
            className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/60 px-3 py-2 text-left text-sm hover:bg-secondary"
            onClick={() => onSelect(benchmark)}
          >
            {benchmark.name}
            <ArrowRight className="size-4 text-muted-foreground" />
          </button>
        ))}
      </div>
    </section>
  )
}
