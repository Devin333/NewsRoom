"use client"

import { FormEvent, useCallback, useEffect, useState, type ReactNode } from "react"
import { ArrowLeft, Bell, Bookmark, Brain, CheckCircle2, ExternalLink, FileText, Github, Heart, MessageSquare, Quote, Sparkles, StickyNote, ThermometerSun, Trash2 } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PaperPdfViewer } from "@/components/papers/shared/paper-pdf-viewer"
import {
  formatCompactNumber,
  formatPaperDate,
  methodName,
  paperPdfUrl,
  paperSnippet,
  paperTitle,
  taskName
} from "@/lib/papers/format"
import {
  askPaper,
  createPaperReaderNote,
  deletePaperReaderNote,
  fetchPaperReaderNotes,
  fetchPaperUserState,
  patchPaperReaderNote,
  patchPaperUserState
} from "@/lib/papers/api"
import { translate } from "@/lib/i18n"
import { useI18n } from "@/lib/i18n/use-i18n"
import { benchmarkCategoryLabel } from "@/lib/papers/categories"
import type {
  Locale,
  Paper,
  PaperAISummary,
  PaperReaderAnswer,
  PaperReaderNote,
  PaperReaderNoteCreate,
  PaperReaderPayload,
  PaperSection,
  PaperUserState,
  ReadingStatus,
  RelatedNews,
  RelatedPaper,
  RelatedProject
} from "@/lib/papers/types"

export function PaperReaderPage({ reader, locale }: { reader: PaperReaderPayload; locale: Locale }) {
  const { locale: uiLocale, t } = useI18n()
  const activeLocale = uiLocale ?? locale
  const paper = reader.paper
  const title = paperTitle(paper, activeLocale)
  const summary = reader.aiSummary ?? paper.aiSummary ?? null
  const pdfUrl = paperPdfUrl(paper)
  const authors = paper.authors ?? []
  const tasks = paper.taskRefs ?? []
  const methods = paper.methodRefs ?? []
  const [userState, setUserState] = useState<PaperUserState | null>(paper.userState ?? null)
  const [stateStatus, setStateStatus] = useState<"idle" | "loading" | "saving" | "error">("idle")
  const [stateError, setStateError] = useState<string | null>(null)
  const [readerNotes, setReaderNotes] = useState<PaperReaderNote[]>(reader.readerNotes ?? [])
  const [notesStatus, setNotesStatus] = useState<"idle" | "loading" | "saving" | "error">("idle")
  const [notesError, setNotesError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setStateStatus("loading")
    setStateError(null)
    fetchPaperUserState(paper.id)
      .then((state) => {
        if (!cancelled) {
          setUserState(state)
          setStateStatus("idle")
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setStateStatus("error")
          setStateError(error instanceof Error ? error.message : "Paper state unavailable")
        }
      })
    return () => {
      cancelled = true
    }
  }, [paper.id])

  useEffect(() => {
    let cancelled = false
    setNotesStatus("loading")
    setNotesError(null)
    fetchPaperReaderNotes(paper.id)
      .then((notes) => {
        if (!cancelled) {
          setReaderNotes(notes)
          setNotesStatus("idle")
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setNotesStatus("error")
          setNotesError(error instanceof Error ? error.message : "Reader notes unavailable")
        }
      })
    return () => {
      cancelled = true
    }
  }, [paper.id])

  const updateUserState = useCallback(async (patch: Partial<PaperUserState> & { readingStatus?: ReadingStatus }) => {
    setStateStatus("saving")
    setStateError(null)
    try {
      const nextState = await patchPaperUserState(paper.id, {
        favorite: patch.favorite,
        subscribed: patch.subscribed,
        readingStatus: patch.readingStatus,
        currentPage: patch.currentPage,
        progressPercent: patch.progressPercent,
      })
      setUserState(nextState)
      setStateStatus("idle")
    } catch (error) {
      setStateStatus("error")
      setStateError(error instanceof Error ? error.message : "Paper state could not be saved")
    }
  }, [paper.id])

  const handlePdfPageChange = useCallback((pageNumber: number, numPages: number) => {
    const progressPercent = Math.min(100, Math.max(0, Math.round((pageNumber / Math.max(numPages, 1)) * 100)))
    void updateUserState({
      currentPage: pageNumber,
      progressPercent,
      readingStatus: progressPercent >= 100 ? "finished" : "reading",
    })
  }, [updateUserState])

  const createReaderNote = useCallback(async (note: PaperReaderNoteCreate) => {
    setNotesStatus("saving")
    setNotesError(null)
    try {
      const created = await createPaperReaderNote(paper.id, note)
      setReaderNotes((current) => [...current, created])
      setNotesStatus("idle")
    } catch (error) {
      setNotesStatus("error")
      setNotesError(error instanceof Error ? error.message : "Reader note could not be saved")
    }
  }, [paper.id])

  const updateReaderNote = useCallback(async (noteId: string, noteText: string) => {
    setNotesStatus("saving")
    setNotesError(null)
    try {
      const updated = await patchPaperReaderNote(paper.id, noteId, { noteText })
      setReaderNotes((current) => current.map((note) => (note.noteId === noteId ? updated : note)))
      setNotesStatus("idle")
    } catch (error) {
      setNotesStatus("error")
      setNotesError(error instanceof Error ? error.message : "Reader note could not be updated")
    }
  }, [paper.id])

  const removeReaderNote = useCallback(async (noteId: string) => {
    setNotesStatus("saving")
    setNotesError(null)
    try {
      await deletePaperReaderNote(paper.id, noteId)
      setReaderNotes((current) => current.filter((note) => note.noteId !== noteId))
      setNotesStatus("idle")
    } catch (error) {
      setNotesStatus("error")
      setNotesError(error instanceof Error ? error.message : "Reader note could not be deleted")
    }
  }, [paper.id])

  const createBookmark = useCallback(() => {
    const pageNumber = userState?.currentPage ?? 1
    void createReaderNote({
      kind: "bookmark",
      pageNumber,
      color: "yellow",
      label: `Page ${pageNumber}`,
    })
  }, [createReaderNote, userState?.currentPage])

  return (
    <main className="min-h-screen bg-[#f7f9f6] text-[#334155] dark:bg-background dark:text-foreground">
      <div className="mx-auto max-w-[118rem] px-5 py-5 sm:px-8 lg:px-10">
        <div className="mb-5 flex items-center justify-between gap-4 border-b border-[#d8dfd8] pb-4 dark:border-border">
          <Button asChild variant="ghost" className="rounded-full">
            <Link href="/papers">
              <ArrowLeft className="size-4" />
              {t("papers.reader.backToPapers")}
            </Link>
          </Button>
          <div className="flex flex-wrap justify-end gap-2">
            <PaperStateControls
              state={userState}
              status={stateStatus}
              notesStatus={notesStatus}
              onToggleFavorite={() => updateUserState({ favorite: !(userState?.favorite ?? false) })}
              onToggleSubscribed={() => updateUserState({ subscribed: !(userState?.subscribed ?? false) })}
              onStatusChange={(readingStatus) => updateUserState({ readingStatus, progressPercent: readingStatus === "finished" ? 100 : userState?.progressPercent ?? 0 })}
              onCreateBookmark={createBookmark}
              locale={activeLocale}
            />
            <ExternalLinks paper={paper} locale={activeLocale} />
          </div>
        </div>
        {stateError ? (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {stateError}
          </div>
        ) : null}
        {notesError ? (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {notesError}
          </div>
        ) : null}

        <header className="pb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#334155]/55">
            {paper.venue ?? t("papers.reader.paper")} / {formatPaperDate(paper.publishedAt, activeLocale)}
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
              <PaperPdfViewer
                paperId={paper.id}
                pdfUrl={pdfUrl}
                title={title}
                locale={activeLocale}
                fallback={<ReaderTextFallback reader={reader} paper={paper} locale={activeLocale} />}
                initialPage={userState?.currentPage}
                notes={readerNotes}
                onCreateReaderNote={(note) => void createReaderNote(note)}
                onPageChange={handlePdfPageChange}
              />
            ) : (
              <ReaderTextFallback reader={reader} paper={paper} locale={activeLocale} />
            )}
          </section>

          <aside className="space-y-4">
            <ReaderPanel summary={summary} paper={paper} locale={activeLocale} />
            <SignalPanel paper={paper} reader={reader} locale={activeLocale} />
            <ReaderNotesPanel
              notes={readerNotes}
              status={notesStatus}
              locale={activeLocale}
              onDeleteNote={(noteId) => void removeReaderNote(noteId)}
              onUpdateNote={(noteId, noteText) => void updateReaderNote(noteId, noteText)}
            />
            <RelatedPanel reader={reader} locale={activeLocale} />
          </aside>
        </div>
      </div>
    </main>
  )
}

function PaperStateControls({
  state,
  status,
  notesStatus,
  locale,
  onToggleFavorite,
  onToggleSubscribed,
  onStatusChange,
  onCreateBookmark,
}: {
  state: PaperUserState | null
  status: "idle" | "loading" | "saving" | "error"
  notesStatus: "idle" | "loading" | "saving" | "error"
  locale: Locale
  onToggleFavorite: () => void
  onToggleSubscribed: () => void
  onStatusChange: (status: ReadingStatus) => void
  onCreateBookmark: () => void
}) {
  const disabled = status === "loading" || status === "saving"
  const notesDisabled = notesStatus === "loading" || notesStatus === "saving"
  const readingStatus = state?.readingStatus ?? "unread"
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant={state?.favorite ? "default" : "outline"} className="rounded-full bg-white dark:bg-card" disabled={disabled} onClick={onToggleFavorite}>
        <Heart className={state?.favorite ? "size-4 fill-current" : "size-4"} />
        {translate(locale, "papers.reader.favorite")}
      </Button>
      <Button type="button" variant={state?.subscribed ? "default" : "outline"} className="rounded-full bg-white dark:bg-card" disabled={disabled} onClick={onToggleSubscribed}>
        <Bell className="size-4" />
        {translate(locale, "papers.reader.subscribe")}
      </Button>
      <Button
        type="button"
        variant={readingStatus === "finished" ? "default" : "outline"}
        className="rounded-full bg-white dark:bg-card"
        disabled={disabled}
        onClick={() => onStatusChange(readingStatus === "finished" ? "reading" : "finished")}
      >
        <CheckCircle2 className="size-4" />
        {translate(locale, `papers.reader.${readingStatus}`)}
      </Button>
      <Button type="button" variant="outline" className="rounded-full bg-white dark:bg-card" disabled={notesDisabled} onClick={onCreateBookmark}>
        <Bookmark className="size-4" />
        {translate(locale, "papers.reader.bookmark")}
      </Button>
    </div>
  )
}

function ReaderTextFallback({ reader, paper, locale }: { reader: PaperReaderPayload; paper: Paper; locale: Locale }) {
  return (
    <div className="p-7">
      <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/55">{translate(locale, "papers.reader.textFallback")}</h2>
      <div className="mt-5 space-y-5">
        {reader.sections.length ? (
          reader.sections.map((section) => (
            <ReaderTextSection key={section.id} section={section} locale={locale} />
          ))
        ) : (
          <p className="text-base leading-8 text-[#334155]/72 dark:text-muted-foreground">
            {paperSnippet(paper, locale)}
          </p>
        )}
      </div>
    </div>
  )
}

function ReaderTextSection({ section, locale }: { section: PaperSection; locale: Locale }) {
  return (
    <article className="rounded-md border border-[#d8dfd8] p-5 dark:border-border">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-bold">{section.title}</h3>
        <Badge variant="muted" className="rounded-sm">
          {formatSectionType(section.sectionType, locale)}
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

function formatSectionType(value: PaperSection["sectionType"], locale: Locale) {
  const zhLabels: Partial<Record<PaperSection["sectionType"], string>> = {
    abstract: "摘要",
    summary: "总结",
    contribution: "贡献",
    introduction: "引言",
    related_work: "相关工作",
    method: "方法",
    experiment: "实验",
    result: "结果",
    limitation: "局限",
    implementation: "实现",
    benchmark: "基准评测",
    evidence: "证据",
    conclusion: "结论",
    appendix: "附录",
    unknown: "未知"
  }
  if (locale === "zh") {
    return zhLabels[value] ?? value
  }
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
          {translate(locale, "papers.reader.aiReader")}
        </h2>
        <Badge variant="muted" className="rounded-sm">
          v1
        </Badge>
      </div>
      {summary ? (
        <div className="mt-4 space-y-4">
          <p className="text-base leading-7">{summary.summary}</p>
          {summary.keyInsights.length ? (
            <Block title={translate(locale, "papers.reader.tldr")} items={summary.keyInsights} />
          ) : null}
          {summary.contributions?.length ? (
            <Block title={translate(locale, "papers.reader.contributions")} items={summary.contributions} />
          ) : null}
          {summary.methodSummary ? (
            <SummaryField title={translate(locale, "papers.reader.method")} value={summary.methodSummary} />
          ) : null}
          {summary.experimentSummary ? (
            <SummaryField title={translate(locale, "papers.reader.experiments")} value={summary.experimentSummary} />
          ) : null}
          {summary.engineeringRelevance ? (
            <SummaryField title={translate(locale, "papers.reader.engineeringRelevance")} value={summary.engineeringRelevance} />
          ) : null}
          {summary.readingDifficulty || summary.recommendedAudience?.length ? (
            <div className="flex flex-wrap gap-2">
              {summary.readingDifficulty ? (
                <Badge variant="muted" className="rounded-sm">
                  {translate(locale, "papers.reader.difficulty", { difficulty: formatSummaryToken(summary.readingDifficulty, locale) })}
                </Badge>
              ) : null}
              {summary.recommendedAudience?.map((audience) => (
                <Badge key={audience} variant="accent" className="rounded-sm">
                  {formatSummaryToken(audience, locale)}
                </Badge>
              ))}
            </div>
          ) : null}
          {summary.limitations.length ? (
            <Block title={translate(locale, "papers.reader.limitations")} items={summary.limitations} />
          ) : null}
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6 text-[#334155]/64 dark:text-muted-foreground">
          {translate(locale, "papers.reader.summaryMissing")}
        </p>
      )}
      <AskPaperPanel paperId={paper.id} locale={locale} />
      <div className="mt-5 grid grid-cols-3 gap-2 text-sm">
        <Metric icon={<ThermometerSun className="size-4" />} value={paper.newsroomHeatScore?.toFixed(1) ?? "N/A"} label={translate(locale, "papers.reader.heat")} />
        <Metric icon={<Github className="size-4" />} value={paper.githubStars ? formatCompactNumber(paper.githubStars) : "N/A"} label={translate(locale, "papers.reader.stars")} />
        <Metric icon={<Quote className="size-4" />} value={paper.citationCount ? formatCompactNumber(paper.citationCount) : "N/A"} label={translate(locale, "papers.reader.cites")} />
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
      setError(translate(locale, "papers.reader.enterQuestion"))
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
      setError(requestError instanceof Error ? requestError.message : translate(locale, "papers.reader.readerAgentFailed"))
    }
  }

  return (
    <section className="mt-5 rounded-md border border-[#d8dfd8] p-4 text-sm dark:border-border">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 font-semibold text-[#334155] dark:text-foreground">
          <MessageSquare className="size-4" />
          {translate(locale, "papers.reader.ask")}
        </div>
        {answer?.cached ? (
          <Badge variant="muted" className="rounded-sm">
            {translate(locale, "papers.reader.cached")}
          </Badge>
        ) : null}
      </div>
      <form className="mt-3 space-y-3" onSubmit={submitQuestion}>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={translate(locale, "papers.reader.askPlaceholder")}
          className="min-h-20 w-full resize-y rounded-md border border-[#d8dfd8] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#315d8a] focus:ring-2 focus:ring-[#315d8a]/15 dark:border-border dark:bg-background"
          maxLength={1000}
        />
        <Button type="button" className="w-full rounded-md" disabled={!isHydrated || status === "loading"} onClick={() => submitQuestion()}>
          {!isHydrated ? translate(locale, "papers.reader.loading") : status === "loading" ? translate(locale, "papers.reader.asking") : translate(locale, "papers.reader.askButton")}
        </Button>
      </form>
      {status === "error" ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
          {error ?? translate(locale, "papers.reader.readerAgentUnavailable")}
        </div>
      ) : null}
      {answer ? (
        <div className="mt-4 space-y-3 border-t border-[#d8dfd8] pt-4 dark:border-border">
          <p className="text-sm leading-6 text-[#334155] dark:text-foreground">{answer.answer}</p>
          <div className="flex items-center justify-between text-xs text-[#334155]/58 dark:text-muted-foreground">
            <span>{translate(locale, "papers.reader.confidence", { value: Math.round(answer.confidence * 100) })}</span>
            <span>{new Date(answer.generatedAt).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")}</span>
          </div>
          {answer.citations.length ? (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#334155]/52">{translate(locale, "papers.reader.citations")}</h3>
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

function SignalPanel({ paper, reader, locale }: { paper: Paper; reader: PaperReaderPayload; locale: Locale }) {
  const implementations = paper.implementations ?? []
  const benchmarks = paper.benchmarks ?? []
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <h2 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">
        <Sparkles className="size-4" />
        {translate(locale, "papers.reader.researchSignals")}
      </h2>
      <div className="mt-4 space-y-4">
        <MiniList title={translate(locale, "papers.reader.implementations")} empty={translate(locale, "papers.reader.noImplementations")}>
          {implementations.map((item) => (
            <a key={item.id} href={item.repoUrl} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="truncate font-semibold">{item.name}</span>
              <Github className="size-4 shrink-0 text-[#334155]/48" />
            </a>
          ))}
        </MiniList>
        <MiniList title={translate(locale, "papers.reader.benchmarks")} empty={translate(locale, "papers.reader.noBenchmarks")}>
          {benchmarks.map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-semibold">{item.name}</span>
                {item.category ? (
                  <span className="mt-0.5 block text-xs text-[#334155]/52 dark:text-muted-foreground">
                    {benchmarkCategoryLabel(item.category, locale) ?? item.category}
                  </span>
                ) : null}
              </span>
              <span className="text-[#334155]/58">{[item.metric, item.value].filter(Boolean).join(" / ")}</span>
            </div>
          ))}
        </MiniList>
        <div className="rounded-md bg-[#eef4ef] p-3 text-xs leading-5 text-[#334155]/68 dark:bg-secondary dark:text-muted-foreground">
          {translate(locale, "papers.reader.qualityLine", {
            pdf: translate(locale, reader.quality.pdfAvailable ? "papers.reader.available" : "papers.reader.missing"),
            summary: translate(locale, reader.quality.summaryAvailable ? "papers.reader.available" : "papers.reader.notCached"),
            text: translate(locale, reader.quality.textExtracted ? "papers.reader.extracted" : "papers.reader.missing"),
            coverage: Math.round(reader.quality.evidenceCoverage * 100)
          })}
        </div>
      </div>
    </section>
  )
}

function ReaderNotesPanel({
  notes,
  status,
  locale,
  onDeleteNote,
  onUpdateNote,
}: {
  notes: PaperReaderNote[]
  status: "idle" | "loading" | "saving" | "error"
  locale: Locale
  onDeleteNote: (noteId: string) => void
  onUpdateNote: (noteId: string, noteText: string) => void
}) {
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <div className="flex items-center justify-between gap-3">
        <h2 className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">
          <StickyNote className="size-4" />
          {translate(locale, "papers.reader.notes")}
        </h2>
        {status === "loading" || status === "saving" ? (
          <Badge variant="muted" className="rounded-sm">
            {status}
          </Badge>
        ) : null}
      </div>
      {notes.length ? (
        <div className="mt-4 space-y-3">
          {notes.map((note) => (
            <ReaderNoteRow
              key={note.noteId}
              note={note}
              locale={locale}
              disabled={status === "loading" || status === "saving"}
              onDeleteNote={onDeleteNote}
              onUpdateNote={onUpdateNote}
            />
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm leading-6 text-[#334155]/62 dark:text-muted-foreground">
          {translate(locale, "papers.reader.noNotes")}
        </p>
      )}
    </section>
  )
}

function ReaderNoteRow({
  note,
  disabled,
  locale,
  onDeleteNote,
  onUpdateNote,
}: {
  note: PaperReaderNote
  disabled: boolean
  locale: Locale
  onDeleteNote: (noteId: string) => void
  onUpdateNote: (noteId: string, noteText: string) => void
}) {
  const [draft, setDraft] = useState(note.noteText ?? "")

  useEffect(() => {
    setDraft(note.noteText ?? "")
  }, [note.noteText])

  return (
    <article className="rounded-md border border-[#d8dfd8] p-3 text-sm dark:border-border">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={note.kind === "bookmark" ? "muted" : "accent"} className="rounded-sm">
              {formatSummaryToken(note.kind, locale)}
            </Badge>
            <span className="text-xs font-semibold text-[#334155]/55 dark:text-muted-foreground">
              {translate(locale, "papers.reader.page", { page: note.pageNumber })}
            </span>
          </div>
          <h3 className="mt-2 font-semibold text-[#334155] dark:text-foreground">
            {note.label ?? (note.kind === "bookmark" ? translate(locale, "papers.reader.page", { page: note.pageNumber }) : note.quote)}
          </h3>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={translate(locale, "papers.reader.deleteKind", { kind: formatSummaryToken(note.kind, locale) })}
          disabled={disabled}
          onClick={() => onDeleteNote(note.noteId)}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
      {note.quote && note.kind !== "bookmark" ? (
        <p className="mt-2 rounded-md bg-[#eef4ef] px-3 py-2 text-xs leading-5 text-[#334155]/70 dark:bg-secondary dark:text-muted-foreground">
          {note.quote}
        </p>
      ) : null}
      {note.kind === "note" ? (
        <div className="mt-2 space-y-2">
          <textarea
            aria-label={translate(locale, "papers.reader.editNote", { page: note.pageNumber })}
            className="min-h-16 w-full resize-y rounded-md border border-[#d8dfd8] bg-white px-3 py-2 text-xs outline-none transition focus:border-[#315d8a] focus:ring-2 focus:ring-[#315d8a]/15 dark:border-border dark:bg-background"
            value={draft}
            maxLength={4000}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button type="button" size="sm" variant="outline" className="h-8 rounded-md" disabled={disabled} onClick={() => onUpdateNote(note.noteId, draft)}>
            {translate(locale, "papers.reader.saveNote")}
          </Button>
        </div>
      ) : null}
    </article>
  )
}

function RelatedPanel({ reader, locale }: { reader: PaperReaderPayload; locale: Locale }) {
  const hasRelated = reader.relatedPapers.length || reader.relatedProjects.length || reader.relatedNews.length
  return (
    <section className="rounded-md border border-[#d8dfd8] bg-white p-5 dark:border-border dark:bg-card">
      <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-[#334155]/58">{translate(locale, "papers.reader.relatedEntities")}</h2>
      {hasRelated ? (
        <div className="mt-4 space-y-4">
          <MiniList title={translate(locale, "papers.reader.relatedPapers")} empty={translate(locale, "papers.reader.noRelatedPapers")}>
            {reader.relatedPapers.map((item) => (
              <RelatedPaperRow key={item.id} item={item} />
            ))}
          </MiniList>
          <MiniList title={translate(locale, "papers.reader.projects")} empty={translate(locale, "papers.reader.noProjects")}>
            {reader.relatedProjects.map((item) => (
              <RelatedProjectRow key={item.id} item={item} />
            ))}
          </MiniList>
          <MiniList title={translate(locale, "papers.reader.newsSources")} empty={translate(locale, "papers.reader.noNewsSources")}>
            {reader.relatedNews.map((item) => (
              <RelatedNewsRow key={item.id} item={item} />
            ))}
          </MiniList>
        </div>
      ) : (
        <p className="mt-3 text-sm leading-6 text-[#334155]/62 dark:text-muted-foreground">
          {translate(locale, "papers.reader.noRelated")}
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

function ExternalLinks({ paper, locale }: { paper: Paper; locale: Locale }) {
  const links = [
    { href: paperPdfUrl(paper), label: "PDF", icon: <FileText className="size-4" /> },
    { href: paper.arxivUrl, label: "arXiv", icon: <ExternalLink className="size-4" /> },
    { href: paper.repoUrl, label: translate(locale, "papers.reader.code"), icon: <Github className="size-4" /> },
    { href: paper.projectUrl, label: translate(locale, "papers.reader.project"), icon: <ExternalLink className="size-4" /> },
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

function formatSummaryToken(value: string, locale: Locale = "en") {
  if (locale === "zh") {
    const zhTokens: Record<string, string> = {
      bookmark: "书签",
      highlight: "高亮",
      note: "批注",
      low: "低",
      medium: "中",
      high: "高"
    }
    if (zhTokens[value]) {
      return zhTokens[value]
    }
  }
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
