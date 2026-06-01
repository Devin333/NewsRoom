import { paperPdfUrl } from "@/lib/papers/format"
import type { Paper } from "@/lib/papers/types"

export type PaperFeatureFilter = "pdf" | "code" | "benchmark" | "citation"

export const paperFeatureFilters: PaperFeatureFilter[] = ["pdf", "code", "benchmark", "citation"]

export function parsePaperFeatureFilters(value: string | string[] | null | undefined): PaperFeatureFilter[] {
  const values = Array.isArray(value) ? value : (value ?? "").split(",")
  const selected = new Set<PaperFeatureFilter>()

  for (const item of values) {
    const key = item.trim().toLowerCase()
    if (isPaperFeatureFilter(key)) {
      selected.add(key)
    }
  }

  return paperFeatureFilters.filter((filter) => selected.has(filter))
}

export function serializePaperFeatureFilters(filters: PaperFeatureFilter[]) {
  return paperFeatureFilters.filter((filter) => filters.includes(filter)).join(",")
}

export function paperMatchesFeatureFilters(paper: Paper, filters: PaperFeatureFilter[]) {
  return filters.every((filter) => paperHasFeature(paper, filter))
}

export function paperHasFeature(paper: Paper, filter: PaperFeatureFilter) {
  if (filter === "pdf") {
    return Boolean(paperPdfUrl(paper))
  }
  if (filter === "code") {
    return Boolean(validGithubRepoUrl(paper.repoUrl) || (paper.implementations ?? []).some((implementation) => validGithubRepoUrl(implementation.repoUrl)))
  }
  if (filter === "benchmark") {
    return (paper.benchmarks ?? []).length > 0
  }
  return typeof paper.citationCount === "number" && paper.citationCount > 0
}

function isPaperFeatureFilter(value: string): value is PaperFeatureFilter {
  return (paperFeatureFilters as string[]).includes(value)
}

function validGithubRepoUrl(value?: string) {
  return value?.startsWith("https://github.com/") && value !== "https://github.com/"
}
