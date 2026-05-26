"use client"

import { Github } from "lucide-react"
import { translate } from "@/lib/i18n"
import { formatCompactNumber, paperTitle } from "@/lib/papers/format"
import type { Locale, Paper } from "@/lib/papers/types"

export function ImplementationList({ papers, locale, title }: { papers: Paper[]; locale: Locale; title: string }) {
  const implementations = implementationsFromPapers(papers, locale)

  return (
    <section className="rounded-md border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground">
          {translate(locale, "papers.reader.repositories", { count: implementations.length })}
        </span>
      </div>
      {implementations.length ? (
        <div className="mt-3 divide-y divide-border rounded-md border border-border bg-background/60">
          {implementations.map((implementation) => (
            <a
              key={implementation.id}
              href={implementation.repoUrl}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between gap-4 px-3 py-3 text-sm transition-colors hover:bg-secondary"
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <Github className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{implementation.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{implementation.paperTitle}</span>
                </span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {typeof implementation.githubStars === "number"
                  ? `${formatCompactNumber(implementation.githubStars)} ${translate(locale, "papers.reader.stars")}`
                  : translate(locale, "papers.reader.project")}
              </span>
            </a>
          ))}
        </div>
      ) : (
        <div className="mt-3 rounded-md border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
          {translate(locale, "papers.reader.noImplementations")}
        </div>
      )}
    </section>
  )
}

function implementationsFromPapers(papers: Paper[], locale: Locale) {
  const seen = new Set<string>()
  return papers.flatMap((paper) => {
    const items = paper.implementations?.length
      ? paper.implementations
      : paper.repoUrl?.startsWith("https://github.com/")
        ? [{ id: `${paper.id}-repo`, name: paper.repoUrl.replace(/^https:\/\/github\.com\//, ""), repoUrl: paper.repoUrl, githubStars: paper.githubStars }]
        : []

    return items
      .filter((item) => {
        if (seen.has(item.repoUrl)) {
          return false
        }
        seen.add(item.repoUrl)
        return true
      })
      .map((item) => ({
        ...item,
        paperTitle: paperTitle(paper, locale)
      }))
  })
}
