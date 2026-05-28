"use client"

import { useMemo, useState, useTransition } from "react"
import Link from "next/link"
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react"
import { OpenReaderPage } from "@/components/papers/open-reader"
import { formatPaperDate, paperTitle } from "@/lib/papers/format"
import type { Locale } from "@/lib/papers/types"
import { paperDocumentToOpenReader } from "@/lib/paper-reader/open-reader-adapter"
import { triggerPaperCompile } from "@/lib/paper-reader/api"
import type { PaperDiagnostic, PaperDocumentResponse } from "@/lib/paper-reader/types"
import styles from "./paper-document-reader.module.css"

export function PaperDocumentReaderPage({ payload, locale }: { payload: PaperDocumentResponse; locale: Locale }) {
  const { paper, document, manifest, status } = payload
  const compiled = status.status === "compiled" && document && manifest
  const adapted = useMemo(() => (compiled ? paperDocumentToOpenReader(payload) : null), [compiled, payload])

  if (adapted) {
    return <OpenReaderPage reader={adapted.reader} locale={locale} visualLayer={adapted.visualLayer} />
  }

  return <CompileStatusPage payload={payload} locale={locale} />
}

function CompileStatusPage({ payload, locale }: { payload: PaperDocumentResponse; locale: Locale }) {
  const { paper, status } = payload
  const [queued, setQueued] = useState(false)
  const [isPending, startTransition] = useTransition()
  const title = paperTitle(paper, locale)

  function requestCompile(force: boolean) {
    startTransition(async () => {
      await triggerPaperCompile(paper.id, { force })
      setQueued(true)
    })
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
        onCompile={() => requestCompile(false)}
        onRecompile={() => requestCompile(true)}
        pending={isPending}
      />
    </main>
  )
}

function StatusGate({
  status,
  diagnostics,
  reviewSummary,
  onCompile,
  onRecompile,
  pending,
}: {
  status: string
  diagnostics: PaperDiagnostic[]
  reviewSummary?: string
  onCompile: () => void
  onRecompile: () => void
  pending: boolean
}) {
  return (
    <section className={styles.statusGate}>
      <div className={styles.statusIcon}><AlertTriangle size={22} aria-hidden="true" /></div>
      <div>
        <h2>Compiled document is not published</h2>
        <p>Status: <strong>{status}</strong></p>
        {reviewSummary ? <p>{reviewSummary}</p> : null}
        {diagnostics.length ? (
          <ul>{diagnostics.slice(0, 8).map((item) => <li key={`${item.code}-${item.message}`}>{item.message}</li>)}</ul>
        ) : null}
        <div className={styles.statusActions}>
          <button type="button" onClick={onCompile} disabled={pending}>
            <RefreshCw size={16} aria-hidden="true" />Compile
          </button>
          <button type="button" onClick={onRecompile} disabled={pending}>
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
