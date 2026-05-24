"use client"

import { ArrowRight } from "lucide-react"
import { papersCopy, t } from "@/lib/papers/copy"
import type { Benchmark, Locale } from "@/lib/papers/types"

export function BenchmarkList({
  benchmarks,
  locale,
  onSelect
}: {
  benchmarks: Benchmark[]
  locale: Locale
  onSelect: (benchmark: Benchmark) => void
}) {
  return (
    <section className="rounded-md border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{t(papersCopy.benchmarksTitle, locale)}</h2>
      <div className="mt-3 grid gap-2">
        {benchmarks.map((benchmark, index) => (
          <button
            key={benchmark.id}
            type="button"
            className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/60 px-3 py-2 text-left text-sm transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onSelect(benchmark)}
          >
            <span>
              <span className="mr-3 text-xs font-semibold text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
              <span className="font-medium">{benchmark.name}</span>
              <span className="ml-2 text-xs text-muted-foreground">{benchmark.entryCount} entries</span>
            </span>
            <ArrowRight className="size-4 text-muted-foreground" />
          </button>
        ))}
      </div>
    </section>
  )
}
