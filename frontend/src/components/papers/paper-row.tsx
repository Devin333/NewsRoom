"use client"

import { Fragment, type CSSProperties, type MouseEvent, type ReactNode } from "react"
import Link from "next/link"
import { Bell, BookOpen, Github, Heart } from "lucide-react"
import { PaperTags } from "@/components/papers/paper-tags"
import { PaperThumbnail } from "@/components/papers/paper-thumbnail"
import { Button } from "@/components/ui/button"
import { translate } from "@/lib/i18n"
import { papersCopy, t } from "@/lib/papers/copy"
import { formatCompactNumber, formatPaperDate, paperPdfUrl, paperSnippet, paperTitle } from "@/lib/papers/format"
import { papersRoutes } from "@/lib/papers/routes"
import type { Locale, Paper } from "@/lib/papers/types"

const PAPER_ROW_BODY_FONT: CSSProperties = {
  fontFamily: "\"Comic Sans MS\", \"Comic Sans\", cursive"
}

const PAPER_ROW_TITLE_FONT: CSSProperties = {
  fontFamily: "Comic Sans MS, \"Courier New\", monospace"
}

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
  const tasks = paper.taskRefs ?? []
  const methods = paper.methodRefs ?? []
  const tags = paper.tags ?? []
  const metadata = [paper.authors?.slice(0, 3).join(", "), formatPaperDate(paper.publishedAt, locale), paper.venue].filter(Boolean)

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
      className="group cursor-pointer rounded-[1.75rem] px-3 py-7 transition-colors first:pt-6 last:pb-3 hover:bg-[#f7faf7]/80 sm:px-4 dark:hover:bg-card/40"
      onClick={handleRowClick}
    >
      <div className="grid gap-6 lg:grid-cols-[10.5rem_minmax(0,1fr)] xl:gap-8">
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

        <div className="min-w-0 space-y-4">
          <Link href={papersRoutes.detail(paper.slug || paper.id)} className="block text-left">
            <h2
              className="max-w-5xl text-balance text-xl font-black leading-7 text-[#334155] sm:text-[1.72rem] sm:leading-8 dark:text-foreground"
              style={PAPER_ROW_TITLE_FONT}
            >
              {paperTitle(paper, locale)}
            </h2>
          </Link>

          <p
            className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 text-sm text-[#334155]/55 dark:text-muted-foreground"
            style={PAPER_ROW_BODY_FONT}
          >
            {metadata.map((item, index) => (
              <Fragment key={`${paper.id}-meta-${index}`}>
                {index > 0 ? <PaperMetaSeparator /> : null}
                <span className={index === 0 ? "font-semibold text-[#334155]/68 dark:text-foreground/80" : undefined}>{item}</span>
              </Fragment>
            ))}
          </p>

          <p
            className="line-clamp-3 max-w-4xl text-[0.98rem] leading-7 text-[#334155]/72 dark:text-muted-foreground"
            style={PAPER_ROW_BODY_FONT}
          >
            {paperSnippet(paper, locale)}
          </p>

          <div>
            <PaperTags tasks={tasks} methods={methods} tags={tags} locale={locale} />
          </div>

          <div className="flex flex-wrap gap-2.5">
            {paperHref ? (
              <PaperActionPill
                href={paperHref}
                ariaLabel={t(papersCopy.openPaper, locale)}
                icon={<BookOpen className="size-4" />}
                value={paperMetricValue(paper.citationCount)}
                label={translate(locale, "papers.reader.cites")}
              />
            ) : null}
            {repoHref ? (
              <PaperActionPill
                href={repoHref}
                ariaLabel={t(papersCopy.openCode, locale)}
                icon={<Github className="size-4" />}
                value={paperMetricValue(paper.githubStars)}
                label={translate(locale, "papers.reader.stars")}
              />
            ) : null}
          </div>

          {paper.userState?.favorite || paper.userState?.subscribed ? (
            <div className="flex flex-wrap gap-2 text-xs font-semibold text-[#334155]/60 dark:text-muted-foreground">
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
        </div>
      </div>
    </article>
  )
}

function PaperMetaSeparator() {
  return <span aria-hidden="true" className="size-1 rounded-full bg-[#94a3b8]/60" />
}

function PaperActionPill({
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
    <Button
      asChild
      variant="outline"
      size="sm"
      aria-label={ariaLabel}
      className="h-auto rounded-full border-[#dbe3dc] bg-white px-3.5 py-2 text-left hover:bg-[#eef4ef] dark:border-border dark:bg-card dark:hover:bg-secondary"
    >
      <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2.5">
        <span className="text-[#334155]/65 dark:text-muted-foreground">{icon}</span>
        <span className="font-semibold text-[#334155] dark:text-foreground">{value}</span>
        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-[#334155]/55 dark:text-muted-foreground">
          {label.toUpperCase()}
        </span>
      </a>
    </Button>
  )
}

function paperMetricValue(value?: number) {
  return typeof value === "number" ? formatCompactNumber(value) : "N/A"
}
