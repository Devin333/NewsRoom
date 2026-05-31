"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react"
import { OpenReaderPage } from "@/components/papers/open-reader"
import { formatPaperDate, paperTitle } from "@/lib/papers/format"
import type { Locale } from "@/lib/papers/types"
import { paperDocumentToOpenReader } from "@/lib/paper-reader/open-reader-adapter"
import { triggerPaperCompile } from "@/lib/paper-reader/api"
import type { PaperCompileTriggerResponse, PaperDiagnostic, PaperDocumentResponse } from "@/lib/paper-reader/types"
import styles from "./paper-document-reader.module.css"

export function PaperDocumentReaderPage({ payload, locale }: { payload: PaperDocumentResponse; locale: Locale }) {
  const { document, manifest, status } = payload
  const compiled = status.status === "compiled" && document && manifest
  const adapted = useMemo(() => (compiled ? paperDocumentToOpenReader(payload) : null), [compiled, payload])

  if (adapted) {
    return <OpenReaderPage reader={adapted.reader} locale={locale} visualLayer={adapted.visualLayer} />
  }

  return <CompileStatusPage payload={payload} locale={locale} />
}

function CompileStatusPage({ payload, locale }: { payload: PaperDocumentResponse; locale: Locale }) {
  const { paper, status } = payload
  const [queued, setQueued] = useState<PaperCompileTriggerResponse["enqueued"] | null>(null)
  const [compileError, setCompileError] = useState<string | null>(null)
  const [isPending, setPending] = useState(false)
  const title = paperTitle(paper, locale)

  async function requestCompile(force: boolean) {
    setPending(true)
    setCompileError(null)
    try {
      const result = await triggerPaperCompile(paper.id, { force })
      setQueued(result.enqueued)
    } catch (error) {
      setQueued(null)
      setCompileError(error instanceof Error ? error.message : "Compile request failed")
    } finally {
      setPending(false)
    }
  }

  return (
    <main className={styles.readerShell}>
      <header className={styles.header}>
        <Link className={styles.backLink} href="/papers" aria-label="Back to papers">
          <ArrowLeft size={18} aria-hidden="true" />
        </Link>
        <div className={styles.headerText}>
          <div className={styles.kicker}>Paper Reader</div>
          <h1>{title}</h1>
          <p>{paper.authors?.join(", ") || "Unknown authors"} / {paper.venue ?? "Paper"} / {formatPaperDate(paper.publishedAt, locale)}</p>
        </div>
        <StatusBadge status={queued ? "queued" : status.status} />
      </header>

      <StatusGate
        status={queued ? "queued" : status.status}
        diagnostics={status.diagnostics}
        reviewSummary={status.reviewReport?.summary}
        queued={queued}
        error={compileError}
        onCompile={() => void requestCompile(false)}
        onRecompile={() => void requestCompile(true)}
        pending={isPending}
      />
    </main>
  )
}

function StatusGate({
  status,
  diagnostics,
  reviewSummary,
  queued,
  error,
  onCompile,
  onRecompile,
  pending,
}: {
  status: string
  diagnostics: PaperDiagnostic[]
  reviewSummary?: string
  queued: PaperCompileTriggerResponse["enqueued"] | null
  error: string | null
  onCompile: () => void
  onRecompile: () => void
  pending: boolean
}) {
  const actionsDisabled = pending || Boolean(queued)
  return (
    <section className={styles.statusGate}>
      <div className={styles.statusIcon}><AlertTriangle size={22} aria-hidden="true" /></div>
      <div>
        <h2>Compiled document is not published</h2>
        <p>Status: <strong>{status}</strong></p>
        {queued ? (
          <p>Compile task queued: <strong>{queued.task_id}</strong></p>
        ) : null}
        {error ? (
          <p role="alert">{error}</p>
        ) : null}
        {reviewSummary ? <p>{reviewSummary}</p> : null}
        {diagnostics.length ? (
          <ul>{diagnostics.slice(0, 8).map((item) => <li key={`${item.code}-${item.message}`}>{item.message}</li>)}</ul>
        ) : null}
        <div className={styles.statusActions}>
          <button type="button" onClick={onCompile} disabled={actionsDisabled}>
            <RefreshCw size={16} aria-hidden="true" />{pending ? "Queueing" : "Compile"}
          </button>
          <button type="button" onClick={onRecompile} disabled={actionsDisabled}>
            <RefreshCw size={16} aria-hidden="true" />Recompile
          </button>
        </div>
      </div>
    </section>
  )
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`${styles.statusBadge} ${status === "compiled" ? styles.statusCompiled : styles.statusPending}`}>{status}</span>
}
