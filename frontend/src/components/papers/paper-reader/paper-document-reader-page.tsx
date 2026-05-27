"use client"

import { useMemo, useState, useTransition } from "react"
import Link from "next/link"
import Image from "next/image"
import {
  AlertTriangle,
  ArrowLeft,
  Eye,
  FileText,
  ImageIcon,
  RefreshCw,
  Sigma,
  Table2,
  X,
} from "lucide-react"
import { formatPaperDate, paperTitle } from "@/lib/papers/format"
import { recordReaderEvent } from "@/lib/papers/api"
import type { Locale } from "@/lib/papers/types"
import { paperAssetUrl, paperSourcePreviewUrl, triggerPaperCompile } from "@/lib/paper-reader/api"
import { targetForPaperBlock } from "@/lib/paper-reader/interactions"
import type {
  PaperBlock,
  PaperDiagnostic,
  PaperDocumentResponse,
  PaperSourceRegion,
  PaperVisualAsset,
} from "@/lib/paper-reader/types"
import styles from "./paper-document-reader.module.css"

export function PaperDocumentReaderPage({ payload, locale }: { payload: PaperDocumentResponse; locale: Locale }) {
  const { paper, document, manifest, status, ai } = payload
  const [preview, setPreview] = useState<{ title: string; source: PaperSourceRegion } | null>(null)
  const [queued, setQueued] = useState(false)
  const [isPending, startTransition] = useTransition()
  const title = paperTitle(paper, locale)
  const assetsById = useMemo(() => new Map((manifest?.assets ?? []).map((asset) => [asset.assetId, asset])), [manifest])
  const compiled = status.status === "compiled" && document && manifest

  function requestCompile(force: boolean) {
    startTransition(async () => {
      await triggerPaperCompile(paper.id, { force })
      setQueued(true)
    })
  }

  function openSourcePreview(block: PaperBlock) {
    if (!block.source) return
    setPreview({ title: block.label || block.text || `Page ${block.source.pageNumber}`, source: block.source })
    void recordReaderEvent(paper.id, {
      type: block.type === "table" ? "table_explanation_requested" : block.type === "figure" ? "figure_explanation_requested" : "reader_progress_sampled",
      target: targetForPaperBlock(block),
      paragraphId: block.type === "paragraph" || block.type === "heading" ? block.id : undefined,
      payload: { action: "source_preview_opened" },
    }).catch(() => undefined)
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

      {compiled ? (
        <div className={styles.readerGrid}>
          <Outline items={document.outline} />
          <article className={styles.article} aria-label="Compiled paper body">
            {document.blocks.map((block) => (
              <BlockView
                key={block.id}
                block={block}
                asset={block.assetId ? assetsById.get(block.assetId) : undefined}
                paperId={paper.id}
                onPreview={openSourcePreview}
              />
            ))}
          </article>
          <AiPanel ai={ai} diagnostics={status.diagnostics} />
        </div>
      ) : (
        <StatusGate
          status={queued ? "queued" : status.status}
          diagnostics={status.diagnostics}
          reviewSummary={status.reviewReport?.summary}
          onCompile={() => requestCompile(false)}
          onRecompile={() => requestCompile(true)}
          pending={isPending}
        />
      )}

      {preview ? (
        <SourcePreviewModal
          paperId={paper.id}
          title={preview.title}
          source={preview.source}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </main>
  )
}

function BlockView({
  block,
  asset,
  paperId,
  onPreview,
}: {
  block: PaperBlock
  asset?: PaperVisualAsset
  paperId: string
  onPreview: (block: PaperBlock) => void
}) {
  if (block.type === "heading") {
    const level = Math.min(Math.max(block.level ?? 2, 2), 4)
    const Heading = `h${level}` as "h2" | "h3" | "h4"
    return (
      <section id={block.id} className={styles.headingBlock} data-block-id={block.id}>
        <Heading>{block.text}</Heading>
        {block.source ? (
          <button type="button" className={styles.inlineIconButton} title="Open source preview" onClick={() => onPreview(block)}>
            <Eye size={16} aria-hidden="true" />
          </button>
        ) : null}
      </section>
    )
  }

  if (block.type === "paragraph") {
    return (
      <p id={block.id} className={styles.paragraph} data-block-id={block.id}>
        {block.text}
        {block.source ? (
          <button type="button" className={styles.paragraphPreview} title="Open source preview" onClick={() => onPreview(block)}>
            <Eye size={14} aria-hidden="true" />
          </button>
        ) : null}
      </p>
    )
  }

  return <VisualBlock block={block} asset={asset} paperId={paperId} onPreview={onPreview} />
}

function VisualBlock({
  block,
  asset,
  paperId,
  onPreview,
}: {
  block: PaperBlock
  asset?: PaperVisualAsset
  paperId: string
  onPreview: (block: PaperBlock) => void
}) {
  const Icon = block.type === "table" ? Table2 : block.type === "equation" ? Sigma : ImageIcon
  return (
    <figure id={block.id} className={styles.visualBlock} data-block-id={block.id} data-asset-id={asset?.assetId}>
      <div className={styles.visualToolbar}>
        <span><Icon size={17} aria-hidden="true" />{block.label || asset?.label || block.type}</span>
        {block.source ? (
          <button type="button" className={styles.iconButton} title="Open source preview" onClick={() => onPreview(block)}>
            <Eye size={16} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {asset ? (
        <Image
          src={paperAssetUrl(paperId, asset.assetId)}
          alt={block.caption || asset.caption || block.label || asset.kind}
          className={styles.visualImage}
          loading="lazy"
          width={asset.width}
          height={asset.height}
          unoptimized
        />
      ) : (
        <div className={styles.assetMissing}><AlertTriangle size={18} aria-hidden="true" />Asset unavailable</div>
      )}
      <figcaption>{block.caption || asset?.caption || block.text}</figcaption>
    </figure>
  )
}

function Outline({ items }: { items: NonNullable<PaperDocumentResponse["document"]>["outline"] }) {
  return (
    <aside className={styles.outline}>
      <div className={styles.panelTitle}><FileText size={16} aria-hidden="true" />Outline</div>
      <nav>
        {items.map((item) => (
          <a key={item.id} href={`#${item.blockId || item.id}`} style={{ paddingLeft: `${Math.max(0, item.level - 1) * 12}px` }}>
            <span>{item.title}</span>
            {item.pageNumber ? <small>p.{item.pageNumber}</small> : null}
          </a>
        ))}
      </nav>
    </aside>
  )
}

function AiPanel({ ai, diagnostics }: { ai: PaperDocumentResponse["ai"]; diagnostics: PaperDiagnostic[] }) {
  return (
    <aside className={styles.aiPanel}>
      <div className={styles.panelTitle}>AI Panel</div>
      {ai?.summary ? (
        <section>
          <h2>Summary</h2>
          <p>{ai.summary.summary}</p>
          {ai.summary.keyInsights?.length ? (
            <ul>{ai.summary.keyInsights.slice(0, 4).map((item) => <li key={item}>{item}</li>)}</ul>
          ) : null}
        </section>
      ) : null}
      {ai?.review ? (
        <section>
          <h2>Review</h2>
          <p>{ai.review.summary}</p>
          {ai.review.risks?.length ? <ul>{ai.review.risks.map((item) => <li key={item}>{item}</li>)}</ul> : null}
        </section>
      ) : null}
      {diagnostics.length ? (
        <section>
          <h2>Diagnostics</h2>
          <ul>{diagnostics.slice(0, 6).map((item) => <li key={`${item.code}-${item.message}`}>{item.message}</li>)}</ul>
        </section>
      ) : null}
    </aside>
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

function SourcePreviewModal({
  paperId,
  title,
  source,
  onClose,
}: {
  paperId: string
  title: string
  source: PaperSourceRegion
  onClose: () => void
}) {
  return (
    <div className={styles.previewBackdrop} role="dialog" aria-modal="true" aria-label="Source preview">
      <div className={styles.previewDialog}>
        <div className={styles.previewHeader}>
          <strong>{title}</strong>
          <button type="button" className={styles.iconButton} title="Close" onClick={onClose}>
            <X size={17} aria-hidden="true" />
          </button>
        </div>
        <Image
          src={paperSourcePreviewUrl(paperId, source)}
          alt={title}
          width={Math.max(1, Math.round((source.bbox.x1 - source.bbox.x0) * 4))}
          height={Math.max(1, Math.round((source.bbox.y1 - source.bbox.y0) * 4))}
          unoptimized
        />
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`${styles.statusBadge} ${status === "compiled" ? styles.statusCompiled : styles.statusPending}`}>{status}</span>
}
