"use client"

import { useEffect, useState, type ReactNode } from "react"
import { ExternalLink, FileText, Github, Globe2, Quote, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { papersCopy, t } from "@/lib/papers/copy"
import {
  formatCompactNumber,
  formatPaperDate,
  methodName,
  paperPdfUrl,
  paperSnippet,
  paperTitle,
  taskName
} from "@/lib/papers/format"
import type { Locale, Paper } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const CLOSE_ANIMATION_MS = 420

export function PaperDetailDrawer({
  paper,
  locale,
  open,
  onOpenChange
}: {
  paper: Paper | null
  locale: Locale
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [activePaper, setActivePaper] = useState<Paper | null>(paper)

  useEffect(() => {
    if (paper) {
      setActivePaper(paper)
      return
    }

    const timeout = window.setTimeout(() => setActivePaper(null), CLOSE_ANIMATION_MS)
    return () => window.clearTimeout(timeout)
  }, [paper])

  useEffect(() => {
    if (!open) {
      return
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onOpenChange(false)
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [onOpenChange, open])

  if (!activePaper) {
    return null
  }

  const isVisible = open && Boolean(paper)
  const title = paperTitle(activePaper, locale)
  const pdfHref = paperPdfUrl(activePaper)
  const arxivHref = activePaper.arxivUrl
  const repoHref = validGithubRepoUrl(activePaper.repoUrl)
  const projectHref =
    activePaper.paperUrl && activePaper.paperUrl !== pdfHref && activePaper.paperUrl !== arxivHref
      ? activePaper.paperUrl
      : undefined
  const citationCount = activePaper.citationCount

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-50 bg-[#0f172a]/25 backdrop-blur-sm transition-[opacity,backdrop-filter] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]",
          isVisible ? "opacity-100" : "pointer-events-none opacity-0 backdrop-blur-0"
        )}
        aria-hidden="true"
        onClick={() => onOpenChange(false)}
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex w-[min(58rem,96vw)] flex-col border-l border-[#d8dfd8] bg-[#f7f9f6] shadow-[-24px_0_70px_rgba(15,23,42,0.18)] transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] dark:border-border dark:bg-background xl:w-[min(76rem,72vw)] 2xl:w-[clamp(72rem,73vw,94rem)]",
          isVisible ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-full opacity-0"
        )}
        aria-label="Paper detail"
        aria-modal="true"
        role="dialog"
      >
        <div className="flex items-center justify-between border-b border-[#d8dfd8] px-7 py-5 dark:border-border">
          <div className="text-xs uppercase tracking-[0.16em] text-[#334155]/55">
            Trending
            {arxivHref ? <span> / {arxivIdFromUrl(arxivHref)}</span> : null}
          </div>
          <button
            type="button"
            className="rounded-full p-2 text-[#334155]/55 transition-colors hover:bg-white hover:text-[#334155] dark:hover:bg-card dark:hover:text-foreground"
            aria-label={t(papersCopy.dismiss, locale)}
            onClick={() => onOpenChange(false)}
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7">
          <header>
            <h2 className="max-w-4xl text-3xl font-black leading-tight text-[#334155] dark:text-foreground sm:text-4xl">
              {title}
            </h2>
            <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-[#334155]/55 dark:text-muted-foreground">
              <span>{activePaper.venue ?? "Paper"}</span>
              <span aria-hidden="true">/</span>
              <span>{formatPaperDate(activePaper.publishedAt, locale)}</span>
              {typeof citationCount === "number" ? (
                <>
                  <span aria-hidden="true">/</span>
                  <span className="inline-flex items-center gap-1">
                    <Quote className="size-4" />
                    {formatCompactNumber(citationCount)} OpenAlex citations
                  </span>
                </>
              ) : null}
            </div>
            <p className="mt-5 border-t border-[#d8dfd8] pt-5 text-base leading-7 text-[#334155] dark:border-border dark:text-foreground">
              {activePaper.authors.join(", ")}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {pdfHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={pdfHref} target="_blank" rel="noreferrer">
                    <FileText className="size-4" />
                    View PDF
                  </a>
                </Button>
              ) : null}
              {arxivHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={arxivHref} target="_blank" rel="noreferrer">
                    <ExternalLink className="size-4" />
                    arXiv page
                  </a>
                </Button>
              ) : null}
              {repoHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={repoHref} target="_blank" rel="noreferrer">
                    <Github className="size-4" />
                    Code
                    {typeof activePaper.githubStars === "number" ? (
                      <span className="text-[#334155]/55">/ {formatCompactNumber(activePaper.githubStars)} stars</span>
                    ) : null}
                  </a>
                </Button>
              ) : null}
              {projectHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={projectHref} target="_blank" rel="noreferrer">
                    <Globe2 className="size-4" />
                    Project page
                  </a>
                </Button>
              ) : null}
            </div>
          </header>

          <DetailSection title="TL;DR" meta="AI-generated">
            <div className="border-l-4 border-[#315d8a] bg-white px-5 py-4 text-base leading-7 text-[#334155] shadow-sm dark:bg-card dark:text-foreground">
              {buildTldr(activePaper, locale)}
            </div>
          </DetailSection>

          <DetailSection title="Abstract">
            <p className="max-w-5xl text-base leading-8 text-[#334155]/74 dark:text-muted-foreground">
              {paperSnippet(activePaper, locale)}
            </p>
          </DetailSection>

          <DetailSection title="Tasks" meta={`${activePaper.taskRefs.length} tagged`}>
            <div className="flex flex-wrap gap-2">
              {activePaper.taskRefs.map((task) => (
                <Badge key={task.id} variant="accent" className="rounded-sm border-emerald-200 bg-emerald-100/80 text-emerald-800">
                  {taskName(task, locale)}
                </Badge>
              ))}
            </div>
          </DetailSection>

          <DetailSection title="Methods" meta={`${activePaper.methodRefs.length} used`}>
            <div className="flex flex-wrap gap-2">
              {activePaper.methodRefs.map((method) => (
                <Badge key={method.id} variant="muted" className="rounded-sm bg-white text-[#334155] dark:bg-card dark:text-foreground">
                  {methodName(method, locale)}
                </Badge>
              ))}
            </div>
          </DetailSection>

          <DetailSection title="Results" meta="0 benchmarks">
            <p className="text-sm text-[#334155]/58 dark:text-muted-foreground">
              No benchmark results recorded yet.
            </p>
          </DetailSection>
        </div>
      </aside>
    </>
  )
}

function DetailSection({
  title,
  meta,
  children
}: {
  title: string
  meta?: string
  children: ReactNode
}) {
  return (
    <section className="mt-9">
      <div className="mb-4 flex items-center justify-between border-b border-[#d8dfd8] pb-3 dark:border-border">
        <h3 className="text-xs font-semibold uppercase tracking-[0.22em] text-[#334155]/55">{title}</h3>
        {meta ? <span className="text-xs italic text-[#334155]/52 dark:text-muted-foreground">{meta}</span> : null}
      </div>
      {children}
    </section>
  )
}

function buildTldr(paper: Paper, locale: Locale) {
  const snippet = paperSnippet(paper, locale).split(/[.!?]/).find(Boolean)?.trim()
  return snippet ? `${snippet}.` : `${paperTitle(paper, locale)} summarizes a verified research item in the Papers stream.`
}

function arxivIdFromUrl(value: string) {
  try {
    const url = new URL(value)
    const match = url.pathname.match(/^\/(?:abs|pdf)\/([^/?#]+?)(?:\.pdf)?$/i)
    return match?.[1]?.replace(/v\d+$/i, "")
  } catch {
    return undefined
  }
}

function validGithubRepoUrl(value?: string) {
  return value?.startsWith("https://github.com/") && value !== "https://github.com/" ? value : undefined
}
