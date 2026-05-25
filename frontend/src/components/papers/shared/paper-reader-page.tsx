"use client"

import { FormEvent, useEffect, useState, type ReactNode } from "react"
import { ArrowLeft, Brain, ExternalLink, FileText, Github, MessageSquare, Quote, Sparkles, ThermometerSun } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  formatCompactNumber,
  formatPaperDate,
  methodName,
  paperPdfUrl,
  paperSnippet,
  paperTitle,
  taskName
} from "@/lib/papers/format"
import { askPaper } from "@/lib/papers/api"
import type {
  Locale,
  Paper,
  PaperAISummary,
  PaperReaderAnswer,
  PaperReaderPayload,
  PaperSection,
  RelatedNews,
  RelatedPaper,
  RelatedProject
} from "@/lib/papers/types"

export function PaperReaderPage({ reader, locale }: { reader: PaperReaderPayload; locale: Locale }) {
  const paper = reader.paper
  const title = paperTitle(paper, locale)
  const summary = reader.aiSummary ?? paper.aiSummary ?? null
  const pdfUrl = paperPdfUrl(paper)
  const authors = paper.authors ?? []
  const tasks = paper.taskRefs ?? []
  const methods = paper.methodRefs ?? []

  return (
    <main className="min-h-screen bg-[#f7f9f6] text-[#334155] dark:bg-background dark:text-foreground">
      <div className="mx-auto max-w-[118rem] px-5 py-5 sm:px-8 lg:px-10">
        <div className="mb-5 flex items-center justify-between gap-4 border-b border-[#d8dfd8] pb-4 dark:border-border">
          <Button asChild variant="ghost" className="rounded-full">
            <Link href="/papers">
              <ArrowLeft className="size-4" />
              Papers
            </Link>
          </Button>
          <div className="flex flex-wrap justify-end gap-2">
            <ExternalLinks paper={paper} />
          </div>
        </div>

        <header className="pb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#334155]/55">
            {paper.venue ?? "Paper"} / {formatPaperDate(paper.publishedAt, locale)}
          </p>
          <h1 className="mt-3 max-w-6xl text-4xl font-black leading-tight tracking-normal sm:text-5xl">
            {title}
          </h1>
          <p className="mt-4 max-w-5xl text-base leading-7 text-[#334155]/68 dark:text-muted-foreground">
            {authors.join(", ")}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {tasks.map((task) => (
              <Badge key={task.id} variant="accent" className="rounded-sm">
                {taskName(task, locale)}
              </Badge>
            ))}
            {methods.map((method) => (
              <Badge key={method.id} variant="muted" className="rounded-sm">
                {methodName(method, locale)}
              </Badge>
            ))}
          </div>
        </header>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_26rem] 2xl:grid-cols-[minmax(0,1fr)_30rem]">
          <section className="min-h-[42rem] overflow-hidden rounded-md border border-[#d8dfd8] bg-white dark:border-border dark:bg-card">
            {pdfUrl ? (
              <iframe
                title={title}
                src={`/api/papers/pdf?url=${encodeURIComponent(pdfUrl)}`}
                className="h-[78vh] min-h-[42rem] w-full bg-white"
              />
            ) : (
              <div className="p-7">
                <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/55">Text fallback</h2>
                <div className="mt-5 space-y-5">
                  {reader.sections.length ? (
                    reader.sections.map((section) => (
                      <ReaderTextSection key={section.id} section={section} />
                    ))
                  ) : (
                    <p className="text-base leading-8 text-[#334155]/72 dark:text-muted-foreground">
                      {paperSnippet(paper, locale)}
                    </p>
                  )}
                </div>
              </div>
            )}
          </section>

          <aside className="space-y-4">
            <ReaderPanel summary={summary} paper={paper} locale={locale} />
            <SignalPanel paper={paper} reader={reader} />
            <RelatedPanel reader={reader} />
          </aside>
        </div>
      </div>
    </main>
  )
}

function ReaderTextSection({ section }: { section: PaperSection }) {
  return (
    <article className="rounded-md border border-[#d8dfd8] p-5 dark:border-border">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-bold">{section.title}</h3>
        <Badge variant="muted" className="rounded-sm">
          {formatSectionType(section.sectionType)}
        </Badge>
      </div>
      {section.summary ? (
        <p className="mt-3 text-sm font-medium leading-6 text-[#334155]/75 dark:text-muted-foreground">
          {section.summary}
        </p>
      ) : null}
      <p className="mt-3 whitespace-pre-line text-base leading-8 text-[#334155]/72 dark:text-muted-foreground">
        {section.textExcerpt}
      </p>
    </article>
  )
}

function formatSectionType(value: PaperSection["sectionType"]) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function ReaderPanel({ summary, paper, locale }: { summary: PaperAISummary | null; paper: Paper; locale: Locale }) {
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-[#d8dfd8] pb-3 dark:border-border">
        <h2 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">
          <Brain className="size-4" />
          AI Reader
        </h2>
        <Badge variant="muted" className="rounded-sm">
          v1
        </Badge>
      </div>
      {summary ? (
        <div className="mt-4 space-y-4">
          <p className="text-base leading-7">{summary.summary}</p>
          {summary.keyInsights.length ? (
            <Block title="TL;DR" items={summary.keyInsights} />
          ) : null}
          {summary.contributions?.length ? (
            <Block title="Contributions" items={summary.contributions} />
          ) : null}
          {summary.methodSummary ? (
            <SummaryField title="Method" value={summary.methodSummary} />
          ) : null}
          {summary.experimentSummary ? (
            <SummaryField title="Experiments" value={summary.experimentSummary} />
          ) : null}
          {summary.engineeringRelevance ? (
            <SummaryField title="Engineering Relevance" value={summary.engineeringRelevance} />
          ) : null}
          {summary.readingDifficulty || summary.recommendedAudience?.length ? (
            <div className="flex flex-wrap gap-2">
              {summary.readingDifficulty ? (
                <Badge variant="muted" className="rounded-sm">
                  Difficulty: {formatSummaryToken(summary.readingDifficulty)}
                </Badge>
              ) : null}
              {summary.recommendedAudience?.map((audience) => (
                <Badge key={audience} variant="accent" className="rounded-sm">
                  {formatSummaryToken(audience)}
                </Badge>
              ))}
            </div>
          ) : null}
          {summary.limitations.length ? (
            <Block title="Limitations" items={summary.limitations} />
          ) : null}
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-[#334155]/64 dark:text-muted-foreground">
          AI summary is not cached yet. Open the preview drawer to generate it on demand.
        </p>
      )}
      <AskPaperPanel paperId={paper.id} locale={locale} />
      <div className="mt-5 grid grid-cols-3 gap-2 text-sm">
        <Metric icon={<ThermometerSun className="size-4" />} value={paper.newsroomHeatScore?.toFixed(1) ?? "N/A"} label="Heat" />
        <Metric icon={<Github className="size-4" />} value={paper.githubStars ? formatCompactNumber(paper.githubStars) : "N/A"} label="Stars" />
        <Metric icon={<Quote className="size-4" />} value={paper.citationCount ? formatCompactNumber(paper.citationCount) : "N/A"} label="Cites" />
      </div>
    </section>
  )
}

function AskPaperPanel({ paperId, locale }: { paperId: string; locale: Locale }) {
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<PaperReaderAnswer | null>(null)
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [error, setError] = useState<string | null>(null)
  const [isHydrated, setIsHydrated] = useState(false)

  useEffect(() => {
    setIsHydrated(true)
  }, [])

  async function submitQuestion(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    const trimmed = question.trim()
    if (!trimmed) {
      setStatus("error")
      setError(locale === "zh" ? "请输入一个问题。" : "Enter a question first.")
      return
    }
    setStatus("loading")
    setError(null)
    try {
      const result = await askPaper(paperId, trimmed, locale)
      setAnswer(result)
      setStatus("success")
    } catch (requestError) {
      setStatus("error")
      setError(requestError instanceof Error ? requestError.message : "Reader Agent request failed")
    }
  }

  return (
    <section className="mt-5 rounded-md border border-[#d8dfd8] p-4 text-sm dark:border-border">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-semibold text-[#334155] dark:text-foreground">
          <MessageSquare className="size-4" />
          Ask this paper
        </div>
        {answer?.cached ? (
          <Badge variant="muted" className="rounded-sm">
            cached
          </Badge>
        ) : null}
      </div>
      <form className="mt-3 space-y-3" onSubmit={submitQuestion}>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={locale === "zh" ? "问一个关于这篇论文的问题..." : "Ask a question about this paper..."}
          className="min-h-20 w-full resize-y rounded-md border border-[#d8dfd8] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#315d8a] focus:ring-2 focus:ring-[#315d8a]/15 dark:border-border dark:bg-background"
          maxLength={1000}
        />
        <Button type="button" className="w-full rounded-md" disabled={!isHydrated || status === "loading"} onClick={() => submitQuestion()}>
          {!isHydrated ? "Loading..." : status === "loading" ? "Asking..." : "Ask"}
        </Button>
      </form>
      {status === "error" ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
          {error ?? "Reader Agent is unavailable."}
        </div>
      ) : null}
      {answer ? (
        <div className="mt-4 space-y-3 border-t border-[#d8dfd8] pt-4 dark:border-border">
          <p className="text-sm leading-6 text-[#334155] dark:text-foreground">{answer.answer}</p>
          <div className="flex items-center justify-between text-xs text-[#334155]/58 dark:text-muted-foreground">
            <span>Confidence {Math.round(answer.confidence * 100)}%</span>
            <span>{new Date(answer.generatedAt).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")}</span>
          </div>
          {answer.citations.length ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">Citations</h3>
              {answer.citations.map((citation) => (
                <div key={citation.id} className="rounded-md bg-[#eef4ef] px-3 py-2 text-xs leading-5 text-[#334155]/70 dark:bg-secondary dark:text-muted-foreground">
                  <div className="font-semibold text-[#334155] dark:text-foreground">
                    {citation.label} / {citation.sourceType}
                  </div>
                  {citation.textExcerpt ? <p className="mt-1">{citation.textExcerpt}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function SignalPanel({ paper, reader }: { paper: Paper; reader: PaperReaderPayload }) {
  const implementations = paper.implementations ?? []
  const benchmarks = paper.benchmarks ?? []
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <h2 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">
        <Sparkles className="size-4" />
        Research Signals
      </h2>
      <div className="mt-4 space-y-4">
        <MiniList title="Implementations" empty="No verified implementation repository yet.">
          {implementations.map((item) => (
            <a key={item.id} href={item.repoUrl} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate font-semibold">{item.name}</span>
              <Github className="size-4 shrink-0 text-[#334155]/48" />
            </a>
          ))}
        </MiniList>
        <MiniList title="Benchmarks" empty="No real benchmark fields are recorded yet.">
          {benchmarks.map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="font-semibold">{item.name}</span>
              <span className="text-[#334155]/58">{[item.metric, item.value].filter(Boolean).join(" / ")}</span>
            </div>
          ))}
        </MiniList>
        <div className="rounded-md bg-[#eef4ef] p-3 text-xs leading-5 text-[#334155]/68 dark:bg-secondary dark:text-muted-foreground">
          Quality: PDF {reader.quality.pdfAvailable ? "available" : "missing"} / summary{" "}
          {reader.quality.summaryAvailable ? "available" : "not cached"} / text{" "}
          {reader.quality.textExtracted ? "extracted" : "missing"} / evidence coverage{" "}
          {Math.round(reader.quality.evidenceCoverage * 100)}%
        </div>
      </div>
    </section>
  )
}

function RelatedPanel({ reader }: { reader: PaperReaderPayload }) {
  const hasRelated = reader.relatedPapers.length || reader.relatedProjects.length || reader.relatedNews.length
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">Related entities</h2>
      {hasRelated ? (
        <div className="mt-4 space-y-4">
          <MiniList title="Related papers" empty="No related papers yet.">
            {reader.relatedPapers.map((item) => (
              <RelatedPaperRow key={item.id} item={item} />
            ))}
          </MiniList>
          <MiniList title="Projects" empty="No related projects yet.">
            {reader.relatedProjects.map((item) => (
              <RelatedProjectRow key={item.id} item={item} />
            ))}
          </MiniList>
          <MiniList title="News and sources" empty="No related news sources yet.">
            {reader.relatedNews.map((item) => (
              <RelatedNewsRow key={item.id} item={item} />
            ))}
          </MiniList>
        </div>
      ) : (
        <p className="mt-3 text-sm leading-6 text-[#334155]/62 dark:text-muted-foreground">
          No related paper, project, or news signals are available yet.
        </p>
      )}
    </section>
  )
}

function RelatedPaperRow({ item }: { item: RelatedPaper }) {
  return (
    <Link href={`/papers/${item.slug}`} className="block py-2 text-sm">
      <span className="flex items-center justify-between gap-3">
        <span className="font-semibold text-[#334155] dark:text-foreground">{item.title}</span>
        <FileText className="size-4 shrink-0 text-[#334155]/48" />
      </span>
      <span className="mt-1 block text-xs leading-5 text-[#334155]/60 dark:text-muted-foreground">
        {item.relationReason}
      </span>
    </Link>
  )
}

function RelatedProjectRow({ item }: { item: RelatedProject }) {
  const content = (
    <>
      <span className="flex items-center justify-between gap-3">
        <span className="font-semibold text-[#334155] dark:text-foreground">{item.name}</span>
        {item.url ? <Github className="size-4 shrink-0 text-[#334155]/48" /> : null}
      </span>
      <span className="mt-1 block text-xs leading-5 text-[#334155]/60 dark:text-muted-foreground">
        {item.relationReason}
      </span>
    </>
  )
  return item.url ? (
    <a href={item.url} target="_blank" rel="noreferrer" className="block py-2 text-sm">
      {content}
    </a>
  ) : (
    <div className="py-2 text-sm">{content}</div>
  )
}

function RelatedNewsRow({ item }: { item: RelatedNews }) {
  const content = (
    <>
      <span className="flex items-center justify-between gap-3">
        <span className="font-semibold text-[#334155] dark:text-foreground">{item.title}</span>
        {item.url ? <ExternalLink className="size-4 shrink-0 text-[#334155]/48" /> : null}
      </span>
      <span className="mt-1 block text-xs leading-5 text-[#334155]/60 dark:text-muted-foreground">
        {item.relationReason} / {item.sourceType}
      </span>
      {item.summary ? (
        <span className="mt-1 block text-xs leading-5 text-[#334155]/58 dark:text-muted-foreground">
          {item.summary}
        </span>
      ) : null}
    </>
  )
  return item.url ? (
    <a href={item.url} target="_blank" rel="noreferrer" className="block py-2 text-sm">
      {content}
    </a>
  ) : (
    <div className="py-2 text-sm">{content}</div>
  )
}

function ExternalLinks({ paper }: { paper: Paper }) {
  const links = [
    { href: paperPdfUrl(paper), label: "PDF", icon: <FileText className="size-4" /> },
    { href: paper.arxivUrl, label: "arXiv", icon: <ExternalLink className="size-4" /> },
    { href: paper.repoUrl, label: "Code", icon: <Github className="size-4" /> },
    { href: paper.projectUrl, label: "Project", icon: <ExternalLink className="size-4" /> },
  ].filter((link) => link.href)

  return links.map((link) => (
    <Button key={link.label} asChild variant="outline" className="rounded-full bg-white dark:bg-card">
      <a href={link.href} target="_blank" rel="noreferrer">
        {link.icon}
        {link.label}
      </a>
    </Button>
  ))
}

function Block({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">{title}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-[#334155]/72 dark:text-muted-foreground">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function SummaryField({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-[#334155]/72 dark:text-muted-foreground">{value}</p>
    </div>
  )
}

function formatSummaryToken(value: string) {
  return value
    .split(/[_-]+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function Metric({ icon, value, label }: { icon: ReactNode; value: string; label: string }) {
  return (
    <div className="rounded-md border border-[#d8dfd8] p-3 dark:border-border">
      <div className="flex items-center gap-2 text-[#334155]/55">{icon}</div>
      <div className="mt-2 font-bold">{value}</div>
      <div className="text-xs text-[#334155]/55">{label}</div>
    </div>
  )
}

function MiniList({ title, empty, children }: { title: string; empty: string; children: ReactNode }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : []
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">{title}</h3>
      <div className="mt-2 divide-y divide-[#d8dfd8] dark:divide-border">
        {items.length ? items : <p className="py-2 text-sm text-[#334155]/58 dark:text-muted-foreground">{empty}</p>}
      </div>
    </div>
  )
}
