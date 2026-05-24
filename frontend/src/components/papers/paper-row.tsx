"use client"

import { BookOpen, Github } from "lucide-react"
import { PaperMetrics } from "@/components/papers/paper-metrics"
import { PaperTags } from "@/components/papers/paper-tags"
import { PaperThumbnail } from "@/components/papers/paper-thumbnail"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatPaperDate, paperPdfUrl, paperSnippet, paperTitle } from "@/lib/papers/format"
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

  return (
    <article className="py-7 transition-colors first:pt-2 last:pb-3">
      <div className="grid gap-6 lg:grid-cols-[9rem_minmax(0,1fr)_9.25rem]">
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
          <PaperThumbnail paper={paper} />
        </div>

        <div className="min-w-0">
          <button type="button" className="block text-left" onClick={() => onPreview(paper)}>
            <h2 className="text-balance font-serif text-xl font-black leading-7 text-[#101827] sm:text-2xl dark:text-foreground">
              {paperTitle(paper, locale)}
            </h2>
          </button>

          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-500 dark:text-muted-foreground">
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

          <p className="mt-3 line-clamp-2 text-base leading-7 text-[#243044] dark:text-muted-foreground">
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
                  <span>{t(papersCopy.paperRecord, locale)}</span>
                </a>
              </Button>
            ) : null}
            {paper.repoUrl ? (
              <Button asChild variant="outline" size="sm" aria-label={t(papersCopy.openCode, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={paper.repoUrl} target="_blank" rel="noreferrer">
                  <Github className="size-4" />
                  <span>GitHub</span>
                </a>
              </Button>
            ) : null}
          </div>
        </div>

        <div className="hidden border-l border-[#e2e7e2] pl-6 lg:flex lg:flex-col lg:items-start lg:justify-center dark:border-border">
          <PaperMetrics paper={paper} locale={locale} />
          <div className="mt-5 flex gap-2">
            {paperHref ? (
              <Button asChild variant="outline" size="icon" aria-label={t(papersCopy.openPaper, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={paperHref} target="_blank" rel="noreferrer">
                  <BookOpen className="size-4" />
                </a>
              </Button>
            ) : null}
            {paper.repoUrl ? (
              <Button asChild variant="outline" size="icon" aria-label={t(papersCopy.openCode, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={paper.repoUrl} target="_blank" rel="noreferrer">
                  <Github className="size-4" />
                </a>
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </article>
  )
}
