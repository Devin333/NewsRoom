"use client"

import type { MouseEvent, ReactNode } from "react"
import { BookOpen, Github } from "lucide-react"
import { PaperTags } from "@/components/papers/paper-tags"
import { PaperThumbnail } from "@/components/papers/paper-thumbnail"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatCompactNumber, formatPaperDate, paperPdfUrl, paperSnippet, paperTitle } from "@/lib/papers/format"
import type { Locale, Paper } from "@/lib/papers/types"

export function PaperRow({
  paper,
  locale,
  onPreview
}: {
  paper: Paper
  locale: Locale
  onPreview: (paper: Paper) => void
}) {
  const paperHref = paperPdfUrl(paper) ?? paper.paperUrl ?? paper.arxivUrl
  const repoHref = paper.repoUrl?.startsWith("https://github.com/") && paper.repoUrl !== "https://github.com/" ? paper.repoUrl : undefined

  function handleRowClick(event: MouseEvent<HTMLElement>) {
    const target = event.target
    if (target instanceof Element && target.closest("a, button")) {
      return
    }
    onPreview(paper)
  }

  return (
    <article
      data-testid="paper-row"
      className="cursor-pointer py-7 transition-colors first:pt-6 last:pb-3"
      onClick={handleRowClick}
    >
      <div className="grid gap-7 lg:grid-cols-[11rem_minmax(0,1fr)_10rem] 2xl:grid-cols-[12rem_minmax(0,1fr)_10rem]">
        <div
          role="button"
          tabIndex={0}
          className="group w-fit shrink-0 justify-self-center sm:justify-self-start"
          onClick={() => onPreview(paper)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault()
              onPreview(paper)
            }
          }}
          aria-label={`Preview ${paper.title}`}
        >
          <PaperThumbnail paper={paper} locale={locale} />
        </div>

        <div className="min-w-0">
          <button type="button" className="block text-left" onClick={() => onPreview(paper)}>
            <h2 className="text-balance text-xl font-black leading-7 text-[#334155] sm:text-2xl dark:text-foreground">
              {paperTitle(paper, locale)}
            </h2>
          </button>

          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-[#334155]/55 dark:text-muted-foreground">
            <span>{paper.authors.slice(0, 3).join(", ")}</span>
            <span aria-hidden="true">·</span>
            <span>{formatPaperDate(paper.publishedAt, locale)}</span>
            {paper.venue ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{paper.venue}</span>
              </>
            ) : null}
          </p>

          <p className="mt-3 line-clamp-4 max-w-[90rem] text-base leading-7 text-[#334155]/70 dark:text-muted-foreground">
            {paperSnippet(paper, locale)}
          </p>

          <div className="mt-4">
            <PaperTags tasks={paper.taskRefs} methods={paper.methodRefs} tags={paper.tags} locale={locale} />
          </div>

          <div className="mt-5 flex flex-wrap gap-2 lg:hidden">
            {paperHref ? (
              <Button asChild variant="outline" size="sm" aria-label={t(papersCopy.openPaper, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={paperHref} target="_blank" rel="noreferrer">
                  <BookOpen className="size-4" />
                  <span>{paperMetricValue(paper.citationCount)} citations</span>
                </a>
              </Button>
            ) : null}
            {repoHref ? (
              <Button asChild variant="outline" size="sm" aria-label={t(papersCopy.openCode, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={repoHref} target="_blank" rel="noreferrer">
                  <Github className="size-4" />
                  <span>{paperMetricValue(paper.githubStars)} stars</span>
                </a>
              </Button>
            ) : null}
          </div>
        </div>

        <div className="hidden border-l border-[#e2e7e2] pl-6 lg:flex lg:flex-col lg:items-center lg:justify-center lg:gap-5 dark:border-border">
          {paperHref ? (
            <PaperActionMetric
              href={paperHref}
              ariaLabel={t(papersCopy.openPaper, locale)}
              icon={<BookOpen className="size-4" />}
              value={paperMetricValue(paper.citationCount)}
              label="CITATIONS"
            />
          ) : null}
          {repoHref ? (
            <PaperActionMetric
              href={repoHref}
              ariaLabel={t(papersCopy.openCode, locale)}
              icon={<Github className="size-4" />}
              value={paperMetricValue(paper.githubStars)}
              label="STARS"
            />
          ) : null}
        </div>
      </div>
    </article>
  )
}

function PaperActionMetric({
  href,
  ariaLabel,
  icon,
  value,
  label
}: {
  href: string
  ariaLabel: string
  icon: ReactNode
  value: string
  label: string
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={ariaLabel}
      className="group flex min-h-16 w-20 flex-col items-center justify-center rounded-md text-center text-[#334155] transition-colors hover:bg-[#eef4ef] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 dark:text-foreground dark:hover:bg-secondary"
    >
      <span className="flex items-center justify-center gap-1.5 text-base font-black leading-5">
        <span className="text-[#334155]/80 dark:text-muted-foreground">{icon}</span>
        <span>{value}</span>
      </span>
      <span className="mt-1 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-[#334155]/55 dark:text-muted-foreground">
        {label}
      </span>
    </a>
  )
}

function paperMetricValue(value?: number) {
  return typeof value === "number" ? formatCompactNumber(value) : "N/A"
}
