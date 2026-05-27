"use client"

import { useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import { Bell, BookOpen, Brain, ExternalLink, FileText, Github, Globe2, Heart, Quote, RefreshCw, ThermometerSun, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { translate } from "@/lib/i18n"
import { fetchPaperDetail, requestPaperSummary } from "@/lib/papers/api"
import { benchmarkCategoryLabel } from "@/lib/papers/categories"
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
import type { Locale, Paper, PaperAISummary, PaperSourceRef } from "@/lib/papers/types"
import { cn } from "@/lib/utils"

const CLOSE_ANIMATION_MS = 420

export function PaperDetailDrawer({
  paper,
  paperId,
  locale,
  open,
  closeHref,
  onOpenChange
}: {
  paper: Paper | null
  paperId?: string | null
  locale: Locale
  open: boolean
  closeHref?: string
  onOpenChange: (open: boolean) => void
}) {
  const [activePaper, setActivePaper] = useState<Paper | null>(paper)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [summary, setSummary] = useState<PaperAISummary | null>(paper?.aiSummary ?? null)
  const [summaryStatus, setSummaryStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [summaryRetry, setSummaryRetry] = useState(0)

  useEffect(() => {
    if (paper) {
      setActivePaper(paper)
      setSummary(paper.aiSummary ?? null)
      setDetailError(null)
      return
    }
    if (open && paperId) {
      return
    }

    const timeout = window.setTimeout(() => setActivePaper(null), CLOSE_ANIMATION_MS)
    return () => window.clearTimeout(timeout)
  }, [open, paper, paperId])

  useEffect(() => {
    if (!open || !paperId) {
      return
    }
    if (paper && (paper.id === paperId || paper.slug === paperId)) {
      return
    }

    let cancelled = false
    setDetailError(null)
    fetchPaperDetail(paperId)
      .then((detail) => {
        if (!cancelled) {
          setActivePaper(detail)
          setSummary(detail.aiSummary ?? null)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDetailError(error instanceof Error ? error.message : "Paper detail request failed")
        }
      })
    return () => {
      cancelled = true
    }
  }, [open, paper, paperId])

  useEffect(() => {
    if (!open || !activePaper) {
      return
    }
    if (summary && summary.locale === locale && summary.paperId === activePaper.id) {
      setSummaryStatus("success")
      return
    }
    let cancelled = false
    setSummaryStatus("loading")
    setSummaryError(null)
    requestPaperSummary(activePaper.id, locale)
      .then((result) => {
        if (!cancelled) {
          setSummary(result)
          setSummaryStatus("success")
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSummaryStatus("error")
          setSummaryError(error instanceof Error ? error.message : "AI summary request failed")
        }
      })
    return () => {
      cancelled = true
    }
  }, [activePaper, locale, open, summary, summaryRetry])

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

  const isVisible = open && Boolean(activePaper)
  const title = paperTitle(activePaper, locale)
  const pdfHref = paperPdfUrl(activePaper)
  const arxivHref = activePaper.arxivUrl
  const repoHref = validGithubRepoUrl(activePaper.repoUrl)
  const projectHref =
    activePaper.projectUrl ??
    (activePaper.paperUrl && activePaper.paperUrl !== pdfHref && activePaper.paperUrl !== arxivHref
      ? activePaper.paperUrl
      : undefined)
  const citationCount = activePaper.citationCount
  const authors = activePaper.authors ?? []
  const tasks = activePaper.taskRefs ?? []
  const methods = activePaper.methodRefs ?? []
  const implementations = activePaper.implementations ?? []
  const benchmarks = activePaper.benchmarks ?? []
  const newsSources = (activePaper.sourceRefs ?? []).filter(isNewsSourceRef)
  const communitySignals = (activePaper.sourceRefs ?? []).filter(isCommunitySourceRef)
  const evidenceRefs = activePaper.evidenceRefs ?? []

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
            {translate(locale, "papers.reader.trending")}
            {arxivHref ? <span> / {arxivIdFromUrl(arxivHref)}</span> : null}
          </div>
          <a
            href={closeHref ?? "/papers"}
            role="button"
            className="rounded-full p-2 text-[#334155]/55 transition-colors hover:bg-white hover:text-[#334155] dark:hover:bg-card dark:hover:text-foreground"
            aria-label={t(papersCopy.dismiss, locale)}
              onClick={(event) => {
                event.preventDefault()
                onOpenChange(false)
              }}
            >
              <X className="size-5" />
          </a>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7">
          {detailError ? (
            <div className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
              {detailError}
            </div>
          ) : null}
          <header>
            <h2 className="max-w-4xl text-3xl font-black leading-tight text-[#334155] dark:text-foreground sm:text-4xl">
              {title}
            </h2>
            <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-[#334155]/55 dark:text-muted-foreground">
              <span>{activePaper.venue ?? translate(locale, "papers.reader.paper")}</span>
              <span aria-hidden="true">/</span>
              <span>{formatPaperDate(activePaper.publishedAt, locale)}</span>
              {typeof citationCount === "number" ? (
                <>
                  <span aria-hidden="true">/</span>
                  <span className="inline-flex items-center gap-1">
                    <Quote className="size-4" />
                    {formatCompactNumber(citationCount)} {translate(locale, "papers.reader.openAlexCitations")}
                  </span>
                </>
              ) : null}
            </div>
            <p className="mt-5 border-t border-[#d8dfd8] pt-5 text-base leading-7 text-[#334155] dark:border-border dark:text-foreground">
              {authors.join(", ")}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {activePaper.userState?.favorite ? (
                <Badge variant="accent" className="rounded-sm">
                  <Heart className="mr-1 size-3 fill-current" />
                  {translate(locale, "papers.reader.favorite")}
                </Badge>
              ) : null}
              {activePaper.userState?.subscribed ? (
                <Badge variant="muted" className="rounded-sm">
                  <Bell className="mr-1 size-3" />
                  {translate(locale, "papers.reader.subscribed")}
                </Badge>
              ) : null}
              {pdfHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={pdfHref} target="_blank" rel="noreferrer">
                    <FileText className="size-4" />
                    {translate(locale, "papers.reader.viewPdf")}
                  </a>
                </Button>
              ) : null}
              {arxivHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={arxivHref} target="_blank" rel="noreferrer">
                    <ExternalLink className="size-4" />
                    {translate(locale, "papers.reader.arxivPage")}
                  </a>
                </Button>
              ) : null}
              {repoHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={repoHref} target="_blank" rel="noreferrer">
                    <Github className="size-4" />
                    {translate(locale, "papers.reader.code")}
                    {typeof activePaper.githubStars === "number" ? (
                      <span className="text-[#334155]/55">/ {formatCompactNumber(activePaper.githubStars)} {translate(locale, "papers.reader.stars")}</span>
                    ) : null}
                  </a>
                </Button>
              ) : null}
              {projectHref ? (
                <Button asChild variant="outline" className="rounded-md bg-white dark:bg-card">
                  <a href={projectHref} target="_blank" rel="noreferrer">
                    <Globe2 className="size-4" />
                    {translate(locale, "papers.reader.projectPage")}
                  </a>
                </Button>
              ) : null}
              <Button asChild className="rounded-md">
                <Link href={`/papers/${encodeURIComponent(activePaper.slug || activePaper.id)}`}>
                  <BookOpen className="size-4" />
                  {translate(locale, "papers.reader.openReader")}
                </Link>
              </Button>
            </div>
          </header>

          <DetailSection title="NewsRoom AI" meta={summary?.cached ? translate(locale, "papers.reader.cached") : translate(locale, "papers.reader.onDemand")}>
            <AISummaryBlock
              status={summaryStatus}
              summary={summary}
              error={summaryError}
              locale={locale}
              onRetry={() => {
                setSummary(null)
                setSummaryStatus("idle")
                setSummaryRetry((count) => count + 1)
              }}
            />
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.abstract")}>
            <p className="max-w-5xl text-base leading-8 text-[#334155]/74 dark:text-muted-foreground">
              {paperSnippet(activePaper, locale)}
            </p>
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.implementations")} meta={translate(locale, "papers.reader.repositories", { count: implementations.length })}>
            {implementations.length ? (
              <div className="divide-y divide-[#d8dfd8] rounded-md border border-[#d8dfd8] bg-white dark:divide-border dark:border-border dark:bg-card">
                {implementations.map((implementation) => (
                  <a
                    key={implementation.id}
                    href={implementation.repoUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center justify-between gap-4 px-4 py-3 text-sm text-[#334155] transition-colors hover:bg-[#eef4ef] dark:text-foreground dark:hover:bg-secondary"
                  >
                    <span className="inline-flex min-w-0 items-center gap-2">
                      <Github className="size-4 shrink-0" />
                      <span className="truncate font-semibold">{implementation.name}</span>
                    </span>
                    {typeof implementation.githubStars === "number" ? (
                      <span className="shrink-0 text-[#334155]/58">{formatCompactNumber(implementation.githubStars)} {translate(locale, "papers.reader.stars")}</span>
                    ) : null}
                  </a>
                ))}
              </div>
            ) : (
              <EmptyState text={translate(locale, "papers.reader.noImplementations")} />
            )}
          </DetailSection>

          <DetailSection title={translate(locale, "papers.tasks")} meta={translate(locale, "papers.reader.tagged", { count: tasks.length })}>
            <TaxonomyLinks
              items={tasks.map((task) => ({
                id: task.id,
                href: `/papers/tasks/${encodeURIComponent(task.slug)}`,
                label: taskName(task, locale),
                variant: "task" as const,
              }))}
              empty={translate(locale, "papers.reader.noTasks")}
            />
          </DetailSection>

          <DetailSection title={translate(locale, "papers.methods")} meta={translate(locale, "papers.reader.used", { count: methods.length })}>
            <TaxonomyLinks
              items={methods.map((method) => ({
                id: method.id,
                href: `/papers/methods/${encodeURIComponent(method.slug)}`,
                label: methodName(method, locale),
                variant: "method" as const,
              }))}
              empty={translate(locale, "papers.reader.noMethods")}
            />
          </DetailSection>

          <DetailSection title="Benchmarks / SOTA" meta={translate(locale, "papers.reader.results", { count: benchmarks.length })}>
            {benchmarks.length ? (
              <div className="divide-y divide-[#d8dfd8] rounded-md border border-[#d8dfd8] bg-white dark:divide-border dark:border-border dark:bg-card">
                {benchmarks.map((benchmark) => (
                  <a
                    key={benchmark.id}
                    href={benchmark.url ?? "#"}
                    target={benchmark.url ? "_blank" : undefined}
                    rel={benchmark.url ? "noreferrer" : undefined}
                    className="flex items-center justify-between gap-4 px-4 py-3 text-sm text-[#334155] dark:text-foreground"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{benchmark.name}</span>
                      {benchmark.category ? (
                        <span className="mt-1 inline-flex rounded-sm border border-[#d8dfd8] bg-[#eef4ef] px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#334155]/64 dark:border-border dark:bg-secondary dark:text-muted-foreground">
                          {benchmarkCategoryLabel(benchmark.category, locale) ?? benchmark.category}
                        </span>
                      ) : null}
                    </span>
                    <span className="shrink-0 text-[#334155]/58">
                      {[benchmark.metric, benchmark.value].filter(Boolean).join(" · ") || translate(locale, "papers.reader.reported")}
                    </span>
                  </a>
                ))}
              </div>
            ) : (
              <EmptyState text={translate(locale, "papers.reader.noBenchmarks")} />
            )}
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.newsSources")} meta={translate(locale, "papers.reader.results", { count: newsSources.length })}>
            <RelatedSourceList
              items={newsSources.map((source, index) => ({
                id: source.sourceId ?? source.externalId ?? `news-${index}`,
                title: source.title ?? source.sourceName ?? source.sourceType ?? translate(locale, "papers.reader.newsSources"),
                meta: source.sourceName ?? source.sourceType ?? translate(locale, "papers.reader.newsSources"),
                url: source.url
              }))}
              empty={translate(locale, "papers.reader.noNewsSources")}
            />
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.communitySignals")} meta={translate(locale, "papers.reader.results", { count: communitySignals.length })}>
            <RelatedSourceList
              items={communitySignals.map((source, index) => ({
                id: source.sourceId ?? source.externalId ?? `community-${index}`,
                title: source.title ?? source.sourceName ?? source.sourceType ?? translate(locale, "papers.reader.communitySignals"),
                meta: source.sourceName ?? source.sourceType ?? translate(locale, "papers.reader.communitySignals"),
                url: source.url
              }))}
              empty={translate(locale, "papers.reader.noCommunitySignals")}
            />
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.evidenceRefs")} meta={translate(locale, "papers.reader.results", { count: evidenceRefs.length })}>
            <RelatedSourceList
              items={evidenceRefs.map((evidence, index) => ({
                id: evidence.evidenceId ?? evidence.sourceId ?? `evidence-${index}`,
                title: evidence.summary ?? evidence.quote ?? evidence.title ?? translate(locale, "papers.reader.evidenceRefs"),
                meta: evidence.sourceName ?? evidence.sourceType ?? translate(locale, "papers.reader.evidenceRefs"),
                url: evidence.url
              }))}
              empty={translate(locale, "papers.reader.noEvidenceRefs")}
            />
          </DetailSection>

          <DetailSection title={translate(locale, "papers.reader.heat")} meta={translate(locale, "papers.reader.realSignalsOnly")}>
            <div className="flex flex-wrap gap-3 text-sm text-[#334155]/72 dark:text-muted-foreground">
              <MetricPill
                icon={<ThermometerSun className="size-4" />}
                label={translate(locale, "papers.reader.newsroomHeat")}
                value={typeof activePaper.newsroomHeatScore === "number" ? activePaper.newsroomHeatScore.toFixed(1) : "N/A"}
              />
              <MetricPill
                icon={<Github className="size-4" />}
                label={translate(locale, "papers.reader.githubStars")}
                value={typeof activePaper.githubStars === "number" ? formatCompactNumber(activePaper.githubStars) : "N/A"}
              />
              <MetricPill
                icon={<Quote className="size-4" />}
                label={translate(locale, "papers.reader.openAlexCitations")}
                value={typeof citationCount === "number" ? formatCompactNumber(citationCount) : "N/A"}
              />
            </div>
          </DetailSection>
        </div>
      </aside>
    </>
  )
}

function AISummaryBlock({
  status,
  summary,
  error,
  locale,
  onRetry
}: {
  status: "idle" | "loading" | "success" | "error"
  summary: PaperAISummary | null
  error: string | null
  locale: Locale
  onRetry: () => void
}) {
  if (summary) {
    return (
      <div className="space-y-4 border-l-4 border-[#315d8a] bg-white px-5 py-4 text-base leading-7 text-[#334155] shadow-sm dark:bg-card dark:text-foreground">
        <p>{summary.summary}</p>
        {summary.keyInsights.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-[#334155]/72 dark:text-muted-foreground">
            {summary.keyInsights.map((insight) => (
              <li key={insight}>{insight}</li>
            ))}
          </ul>
        ) : null}
        {summary.contributions?.length ? (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">{translate(locale, "papers.reader.contributions")}</h4>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-[#334155]/72 dark:text-muted-foreground">
              {summary.contributions.map((contribution) => (
                <li key={contribution}>{contribution}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    )
  }
  if (status === "loading" || status === "idle") {
    return (
      <div className="flex items-center gap-3 rounded-md border border-[#d8dfd8] bg-white px-4 py-4 text-sm text-[#334155]/68 dark:border-border dark:bg-card dark:text-muted-foreground">
        <Brain className="size-4 animate-pulse" />
        {translate(locale, "papers.reader.generatingSummary")}
      </div>
    )
  }
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-900">
      <p>{error ?? translate(locale, "papers.reader.summaryUnavailable")}</p>
      <button type="button" className="mt-3 inline-flex items-center gap-2 font-semibold" onClick={onRetry}>
        <RefreshCw className="size-4" />
        {translate(locale, "common.retry")}
      </button>
    </div>
  )
}

function TaxonomyLinks({
  items,
  empty,
}: {
  items: Array<{ id: string; href: string; label: string; variant: "task" | "method" }>
  empty: string
}) {
  if (!items.length) {
    return <EmptyState text={empty} />
  }
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <Link
          key={item.id}
          href={item.href}
          className={cn(
            "inline-flex items-center rounded-sm border px-2.5 py-1 text-xs font-semibold transition-colors",
            item.variant === "task"
              ? "border-emerald-200 bg-emerald-100/80 text-emerald-800 hover:bg-emerald-100"
              : "border-[#d8dfd8] bg-white text-[#334155] hover:bg-[#eef4ef] dark:border-border dark:bg-card dark:text-foreground dark:hover:bg-secondary"
          )}
        >
          {item.label}
        </Link>
      ))}
    </div>
  )
}

function RelatedSourceList({
  items,
  empty
}: {
  items: Array<{ id: string; title: string; meta: string; url?: string }>
  empty: string
}) {
  if (!items.length) {
    return <EmptyState text={empty} />
  }

  return (
    <div className="divide-y divide-[#d8dfd8] rounded-md border border-[#d8dfd8] bg-white dark:divide-border dark:border-border dark:bg-card">
      {items.map((item) => {
        const content = (
          <>
            <span className="min-w-0">
              <span className="block line-clamp-2 font-semibold">{item.title}</span>
              <span className="mt-1 block truncate text-xs text-[#334155]/58 dark:text-muted-foreground">{item.meta}</span>
            </span>
            <ExternalLink className="size-4 shrink-0 text-[#334155]/45 dark:text-muted-foreground" />
          </>
        )

        return item.url ? (
          <a
            key={item.id}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between gap-4 px-4 py-3 text-sm text-[#334155] transition-colors hover:bg-[#eef4ef] dark:text-foreground dark:hover:bg-secondary"
          >
            {content}
          </a>
        ) : (
          <div key={item.id} className="flex items-center justify-between gap-4 px-4 py-3 text-sm text-[#334155] dark:text-foreground">
            {content}
          </div>
        )
      })}
    </div>
  )
}

function isNewsSourceRef(source: PaperSourceRef) {
  const value = `${source.sourceType ?? ""} ${source.sourceName ?? ""}`.toLowerCase()
  return ["news", "blog", "rss", "official", "media", "press"].some((token) => value.includes(token))
}

function isCommunitySourceRef(source: PaperSourceRef) {
  const value = `${source.sourceType ?? ""} ${source.sourceName ?? ""}`.toLowerCase()
  return ["hackernews", "reddit", "github", "community", "discussion", "hn"].some((token) => value.includes(token))
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-[#d8dfd8] px-4 py-5 text-sm text-[#334155]/58 dark:border-border dark:text-muted-foreground">
      {text}
    </div>
  )
}

function MetricPill({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[#d8dfd8] bg-white px-3 py-1.5 dark:border-border dark:bg-card">
      {icon}
      <span className="font-semibold text-[#334155] dark:text-foreground">{value}</span>
      <span>{label}</span>
    </span>
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
