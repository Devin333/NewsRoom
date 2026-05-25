"use client"

import type { MouseEvent, ReactNode } from "react"
import { Bell, BookOpen, Github, Heart } from "lucide-react"
import { PaperTags } from "@/components/papers/paper-tags"
import { PaperThumbnail } from "@/components/papers/paper-thumbnail"
import { Button } from "@/components/ui/button"
import { translate } from "@/lib/i18n"
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
  const authors = paper.authors ?? []
  const tasks = paper.taskRefs ?? []
  const methods = paper.methodRefs ?? []
  const tags = paper.tags ?? []

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
            <span>{authors.slice(0, 3).join(", ")}</span>
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
            <PaperTags tasks={tasks} methods={methods} tags={tags} locale={locale} />
          </div>
          {paper.userState?.favorite || paper.userState?.subscribed ? (
            <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-[#334155]/60 dark:text-muted-foreground">
              {paper.userState.favorite ? (
                <span className="inline-flex items-center gap-1 rounded-sm bg-[#eef4ef] px-2 py-1 dark:bg-secondary">
                  <Heart className="size-3 fill-current" />
                  {translate(locale, "papers.reader.favorite")}
                </span>
              ) : null}
              {paper.userState.subscribed ? (
                <span className="inline-flex items-center gap-1 rounded-sm bg-[#eef4ef] px-2 py-1 dark:bg-secondary">
                  <Bell className="size-3" />
                  {translate(locale, "papers.reader.subscribed")}
                </span>
              ) : null}
            </div>
          ) : null}

          <div className="mt-5 flex flex-wrap gap-2 lg:hidden">
            {paperHref ? (
              <Button asChild variant="outline" size="sm" aria-label={t(papersCopy.openPaper, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={paperHref} target="_blank" rel="noreferrer">
                  <BookOpen className="size-4" />
                  <span>{paperMetricValue(paper.citationCount)} {translate(locale, "papers.reader.cites")}</span>
                </a>
              </Button>
            ) : null}
            {repoHref ? (
              <Button asChild variant="outline" size="sm" aria-label={t(papersCopy.openCode, locale)} className="rounded-full bg-white dark:bg-card">
                <a href={repoHref} target="_blank" rel="noreferrer">
                  <Github className="size-4" />
                  <span>{paperMetricValue(paper.githubStars)} {translate(locale, "papers.reader.stars")}</span>
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
              label={translate(locale, "papers.reader.cites").toUpperCase()}
            />
          ) : null}
          {repoHref ? (
            <PaperActionMetric
              href={repoHref}
              ariaLabel={t(papersCopy.openCode, locale)}
              icon={<Github className="size-4" />}
              value={paperMetricValue(paper.githubStars)}
              label={translate(locale, "papers.reader.stars").toUpperCase()}
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
