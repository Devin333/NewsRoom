"use client"

import Link from "next/link"
import Image from "next/image"
import { ArrowLeft, Eye, X } from "lucide-react"
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react"
import { formatPaperDate, paperTitle } from "@/lib/papers/format"
import { askPaper, recordReaderEvent } from "@/lib/papers/api"
import type { Locale, PaperReaderAnswer } from "@/lib/papers/types"
import { paperAssetUrl, paperSourcePreviewUrl } from "@/lib/paper-reader/api"
import { targetForPaperBlock } from "@/lib/paper-reader/interactions"
import type { PaperInlineSpan, PaperReference, PaperSourceRegion } from "@/lib/paper-reader/types"
import type { DrawerState, NotePopoverState, OpenReaderPageProps, OpenReaderVisualBlock, ReaderAssistMode, ReaderParagraph, ReaderSelection, ReaderSettings, ReaderTocItem, SelectionMenuState } from "./open-reader-types"
import { buildReaderParagraphs, buildReaderToc, clamp, getSelectionOffsetsWithinElement, getSelectionStatus, makeMaterialSummary, safeJsonParse, storageKey } from "./open-reader-utils"
import { useOpenReaderSelections, useOpenReaderSettings } from "./open-reader-state"
import { EquationRenderer, InlineMathRenderer } from "./equation-renderer"
import styles from "./open-reader.module.css"

export function OpenReaderPage({ reader, locale, backHref = "/papers", visualLayer }: OpenReaderPageProps) {
  const paper = reader.paper
  const title = paperTitle(paper, locale)
  const paragraphs = useMemo(() => buildReaderParagraphs(reader, locale), [reader, locale])
  const toc = useMemo(
    () => mergeReaderToc(buildReaderToc(paragraphs), visualLayer?.outline ?? [], visualLayer?.blocks ?? []),
    [paragraphs, visualLayer],
  )
  const visualsBySection = useMemo(() => groupVisualsBySection(visualLayer?.blocks ?? []), [visualLayer])
  const references = visualLayer?.references ?? []
  const { settings, patchSettings } = useOpenReaderSettings(paper.id)
  const { selections, events, createTempSelection, discardAllTemp, updateNote, confirmExplain, confirmExample, toggleConfused } = useOpenReaderSelections(paper.id)
  const materials = useMemo(() => makeMaterialSummary(paper.id, selections, events), [paper.id, selections, events])

  const contentRef = useRef<HTMLElement | null>(null)
  const paragraphRefs = useRef(new Map<string, HTMLParagraphElement>())
  const sectionRefs = useRef(new Map<string, HTMLElement>())

  const [activeSectionId, setActiveSectionId] = useState<string | null>(toc[0]?.id ?? null)
  const [menu, setMenu] = useState<SelectionMenuState | null>(null)
  const [note, setNote] = useState<NotePopoverState | null>(null)
  const [drawer, setDrawer] = useState<DrawerState | null>(null)
  const [preview, setPreview] = useState<{
    title: string
    source?: PaperSourceRegion
    assetUrl?: string
    assetMimeType?: string
    width?: number
    height?: number
  } | null>(null)

  const menuSelection = menu ? selections.find((item) => item.id === menu.selectionId) : undefined
  const noteSelection = note ? selections.find((item) => item.id === note.selectionId) : undefined
  const drawerSelection = drawer?.selectionId ? selections.find((item) => item.id === drawer.selectionId) : undefined

  useEffect(() => {
    function onClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null
      if (!target) return
      if (target.closest("[data-open-reader-keep-open]")) return
      setMenu(null)
      setNote(null)
      if (drawer) setDrawer(null)
      discardAllTemp()
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return
      setMenu(null)
      setNote(null)
      setDrawer(null)
      discardAllTemp()
    }

    document.addEventListener("click", onClick)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("click", onClick)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [discardAllTemp, drawer])

  useEffect(() => {
    function onScroll() {
      let active = toc[0]?.id ?? null
      for (const item of toc) {
        const node = sectionRefs.current.get(item.id)
        if (node && node.getBoundingClientRect().top < 120) active = item.id
      }
      setActiveSectionId(active)
      const max = document.documentElement.scrollHeight - window.innerHeight
      const progress = max > 0 ? Math.min(100, Math.max(14, (window.scrollY / max) * 100)) : 14
      document.documentElement.style.setProperty("--open-reader-progress", `${progress}%`)
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener("scroll", onScroll)
  }, [toc])

  function bindParagraph(id: string) {
    return (node: HTMLParagraphElement | null) => {
      if (node) paragraphRefs.current.set(id, node)
      else paragraphRefs.current.delete(id)
    }
  }

  function bindSection(id: string) {
    return (node: HTMLElement | null) => {
      if (node) sectionRefs.current.set(id, node)
      else sectionRefs.current.delete(id)
    }
  }

  function handleMouseUp() {
    window.setTimeout(() => {
      const selection = window.getSelection()
      if (!selection || selection.isCollapsed || !selection.rangeCount) return
      const range = selection.getRangeAt(0)
      const paragraphEl = closestParagraph(range.commonAncestorContainer)
      if (!paragraphEl || !contentRef.current?.contains(paragraphEl)) return
      const paragraphId = paragraphEl.dataset.paragraphId
      const paragraph = paragraphs.find((item) => item.id === paragraphId)
      if (!paragraph) return
      const offsets = getSelectionOffsetsWithinElement(paragraphEl, range)
      if (!offsets) return
      const selectedText = paragraph.text.slice(offsets.startOffset, offsets.endOffset).trim()
      if (selectedText.length < 2) return

      discardAllTemp()
      const selectionId = createTempSelection({ paragraph, selectedText, startOffset: offsets.startOffset, endOffset: offsets.endOffset })
      const rect = range.getBoundingClientRect()
      setMenu({ selectionId, x: rect.left, y: rect.bottom + 8 })
      selection.removeAllRanges()
    }, 0)
  }

  function closestParagraph(node: Node) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node as HTMLElement
    return element?.closest?.("[data-paragraph-id]") as HTMLParagraphElement | null
  }

  function openSelectionMenu(selection: ReaderSelection, rect: DOMRect) {
    setMenu({ selectionId: selection.id, x: rect.left, y: rect.bottom + 8 })
  }

  function openMaterials() {
    setMenu(null)
    setNote(null)
    setDrawer({ mode: "materials" })
  }

  function openSourcePreview(visual: OpenReaderVisualBlock) {
    if (!visual.source && !visual.asset) return
    const useAssetPreview = visual.asset?.metadata?.sourceProvider === "arxiv-source" && visual.asset.kind !== "page"
    setPreview({
      title: visual.block.label || visual.block.caption || visual.asset?.caption || `Page ${visual.source?.pageNumber ?? visual.asset?.pageNumber ?? 1}`,
      source: useAssetPreview ? undefined : visual.source,
      assetUrl: useAssetPreview && visual.asset ? paperAssetUrl(paper.id, visual.asset.assetId) : undefined,
      assetMimeType: useAssetPreview ? visual.asset?.mimeType : undefined,
      width: visual.asset?.width,
      height: visual.asset?.height,
    })
    void recordReaderEvent(paper.id, {
      type: visual.block.type === "table"
        ? "table_explanation_requested"
        : visual.block.type === "figure"
          ? "figure_explanation_requested"
          : "reader_progress_sampled",
      target: targetForPaperBlock(visual.block),
      payload: { action: "source_preview_opened" },
    }).catch(() => undefined)
  }

  const themeClass = settings.theme === "dark" ? styles.darkTheme : settings.theme === "light" ? styles.lightTheme : styles.warmTheme

  return (
    <main
      className={`${styles.openReader} ${themeClass}`}
      style={{ ["--reader-font-size" as string]: `${settings.fontSize}px`, ["--reader-content-width" as string]: `${settings.contentWidth}px` }}
    >
      <Link className={styles.readerBackButton} href={backHref} aria-label="返回论文列表">
        <ArrowLeft aria-hidden="true" className={styles.readerMarkIcon} />
      </Link>

      <ReaderSettingsDock settings={settings} onChange={patchSettings} />

      <article className={styles.readerLayout}>
        <section className={styles.titleBlock}>
          <div className={styles.kicker}>Open Reader</div>
          <h1>{title}</h1>
          <p>{paper.authors?.join(", ")} / {paper.venue ?? "Paper"} / {formatPaperDate(paper.publishedAt, locale)}</p>
        </section>

        <section ref={contentRef} className={styles.paperCard} aria-label="Open reader paper body" data-open-reader-body onMouseUp={handleMouseUp}>
          {toc.map((section) => {
            const sectionParagraphs = paragraphs.filter((paragraph) => paragraph.sectionId === section.id)
            const sectionVisuals = visualsBySection.get(section.id) ?? []
            const sectionItems = buildSectionItems(sectionParagraphs, sectionVisuals)
            return (
              <section key={section.id} ref={bindSection(section.id)} className={styles.readerSection}>
                <SectionHeading section={section} />
                {sectionItems.map((item) => item.type === "paragraph" ? (
                    <ReaderParagraphView
                      key={item.paragraph.id}
                      paragraph={item.paragraph}
                      paragraphRef={bindParagraph(item.paragraph.id)}
                      selections={selections.filter((selection) => selection.paragraphId === item.paragraph.id)}
                      onOpenSelectionMenu={openSelectionMenu}
                    />
                  ) : (
                    <OpenReaderVisualBlockView
                      key={item.visual.id}
                      visual={item.visual}
                      paperId={paper.id}
                      onPreview={openSourcePreview}
                    />
                  ))}
              </section>
            )
          })}
          <ReferencesSection references={references} />
        </section>
      </article>

      <FloatingToc paperId={paper.id} items={toc} activeSectionId={activeSectionId} materialCount={materials.selections.length} onNavigate={(id) => sectionRefs.current.get(id)?.scrollIntoView({ behavior: "smooth", block: "start" })} onOpenMaterials={openMaterials} />

      {menu && menuSelection ? (
        <SelectionActionMenu
          selection={menuSelection}
          x={menu.x}
          y={menu.y}
          onNote={() => { setMenu(null); setNote({ selectionId: menuSelection.id, x: menu.x, y: menu.y }) }}
          onExplain={() => { setMenu(null); setDrawer({ mode: "explain", selectionId: menuSelection.id }) }}
          onExample={() => { setMenu(null); setDrawer({ mode: "example", selectionId: menuSelection.id }) }}
          onToggleConfused={() => { toggleConfused(menuSelection.id); setMenu(null) }}
        />
      ) : null}

      {note && noteSelection ? (
        <ReaderNotePopover selection={noteSelection} x={note.x} y={note.y} onChange={(value) => updateNote(noteSelection.id, value)} />
      ) : null}

      {drawer ? (
        <ReaderAssistDrawer
          drawer={drawer}
          selection={drawerSelection}
          materialSummary={materials}
          locale={locale}
          drawerWidth={settings.drawerWidth}
          onWidthChange={(drawerWidth) => patchSettings({ drawerWidth })}
          onClose={() => { setDrawer(null); discardAllTemp() }}
          onConfirmExplain={(selectionId, question) => confirmExplain(selectionId, question)}
          onConfirmExample={(selectionId, question) => confirmExample(selectionId, question)}
        />
      ) : null}

      {preview ? (
        <SourcePreviewModal
          paperId={paper.id}
          title={preview.title}
          source={preview.source}
          assetUrl={preview.assetUrl}
          assetMimeType={preview.assetMimeType}
          width={preview.width}
          height={preview.height}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </main>
  )
}

type SectionContentItem =
  | { type: "paragraph"; order: number; paragraph: ReaderParagraph }
  | { type: "visual"; order: number; visual: OpenReaderVisualBlock }

function mergeReaderToc(paragraphToc: ReaderTocItem[], outline: ReaderTocItem[], visualBlocks: OpenReaderVisualBlock[]) {
  const paragraphCounts = new Map(paragraphToc.map((item) => [item.id, item.paragraphCount]))
  const next = (outline.length ? outline : paragraphToc).map((item, index) => ({
    ...item,
    level: normalizeTocLevel(item.level),
    sourceOrder: item.sourceOrder ?? index,
    paragraphCount: paragraphCounts.get(item.id) ?? item.paragraphCount,
  }))
  const seen = new Set(next.map((item) => item.id))

  for (const item of paragraphToc) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    next.push({
      ...item,
      level: normalizeTocLevel(item.level),
      sourceOrder: item.sourceOrder ?? next.length,
    })
  }

  for (const visual of visualBlocks) {
    if (seen.has(visual.sectionId)) continue
    seen.add(visual.sectionId)
    next.push({
      id: visual.sectionId,
      title: visual.sectionTitle,
      sectionType: visual.sectionType,
      level: normalizeTocLevel(visual.sectionLevel),
      sectionNumber: visual.sectionNumber,
      sourceOrder: visual.order,
      paragraphCount: 0,
    })
  }
  return next.sort((left, right) => {
    const leftOrder = left.sourceOrder ?? Number.MAX_SAFE_INTEGER
    const rightOrder = right.sourceOrder ?? Number.MAX_SAFE_INTEGER
    return leftOrder === rightOrder ? left.id.localeCompare(right.id) : leftOrder - rightOrder
  })
}

function normalizeTocLevel(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.min(6, Math.max(1, Math.round(value))) : 1
}

function groupVisualsBySection(visuals: OpenReaderVisualBlock[]) {
  const grouped = new Map<string, OpenReaderVisualBlock[]>()
  for (const visual of visuals) {
    const sectionVisuals = grouped.get(visual.sectionId) ?? []
    sectionVisuals.push(visual)
    grouped.set(visual.sectionId, sectionVisuals)
  }
  for (const sectionVisuals of grouped.values()) {
    sectionVisuals.sort((left, right) => left.order - right.order)
  }
  return grouped
}

function buildSectionItems(paragraphs: ReaderParagraph[], visuals: OpenReaderVisualBlock[]): SectionContentItem[] {
  return [
    ...paragraphs.map((paragraph) => ({
      type: "paragraph" as const,
      order: paragraph.sourceOrder ?? paragraph.index * 1000,
      paragraph,
    })),
    ...visuals.map((visual) => ({
      type: "visual" as const,
      order: visual.order,
      visual,
    })),
  ].sort((left, right) => left.order - right.order)
}

function SectionHeading({ section }: { section: ReaderTocItem }) {
  const level = normalizeTocLevel(section.level)
  const HeadingTag = (`h${Math.min(6, Math.max(2, level + 1))}` as keyof JSX.IntrinsicElements)
  return (
    <HeadingTag className={styles.sectionHeading}>
      {section.sectionNumber ? <span className={styles.sectionNumber}>{section.sectionNumber}</span> : null}
      {section.sectionNumber ? " " : null}
      {section.title}
    </HeadingTag>
  )
}

function ReaderParagraphView({ paragraph, selections, paragraphRef, onOpenSelectionMenu }: {
  paragraph: ReaderParagraph
  selections: ReaderSelection[]
  paragraphRef: (node: HTMLParagraphElement | null) => void
  onOpenSelectionMenu: (selection: ReaderSelection, rect: DOMRect) => void
}) {
  const segments = buildParagraphSegments(paragraph, selections)
  return (
    <p ref={paragraphRef} className={styles.paragraph} data-paragraph-id={paragraph.id}>
      {segments.map((segment, index) => segment.selection ? (
        <mark
          key={segment.selection.id}
          data-selection-id={segment.selection.id}
          className={`${styles.selectionMark} ${styles[`selection_${getSelectionStatus(segment.selection)}`]}`}
          onClick={(event) => { event.stopPropagation(); onOpenSelectionMenu(segment.selection!, event.currentTarget.getBoundingClientRect()) }}
          onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); onOpenSelectionMenu(segment.selection!, event.currentTarget.getBoundingClientRect()) }}
        >
          {renderParagraphSegment(segment, index)}
        </mark>
      ) : <span key={index}>{renderParagraphSegment(segment, index)}</span>)}
    </p>
  )
}

function OpenReaderVisualBlockView({
  visual,
  paperId,
  onPreview,
}: {
  visual: OpenReaderVisualBlock
  paperId: string
  onPreview: (visual: OpenReaderVisualBlock) => void
}) {
  const block = visual.block
  const asset = visual.asset
  const label = block.label || asset?.label || block.type
  const caption = block.caption || asset?.caption || block.text
  const equationText = block.text || block.caption || label
  const isEquation = block.type === "equation"
  const tableModel = isPaperTableModel(block.metadata?.tableModel) ? block.metadata?.tableModel : undefined
  const tableHtml = typeof block.metadata?.tableHtml === "string" ? block.metadata.tableHtml : undefined
  const canPreview = Boolean(visual.source || asset)

  return (
    <figure id={block.id} className={`${styles.visualBlock} ${styles[`visual_${block.type}`]}`} data-block-id={block.id} data-asset-id={asset?.assetId}>
      {canPreview ? (
        <button type="button" className={styles.visualPreviewButton} title="Open source preview" onClick={() => onPreview(visual)}>
          <Eye size={16} aria-hidden="true" />
        </button>
      ) : null}
      {isEquation ? (
        <EquationRenderer value={equationText} />
      ) : tableModel ? (
        <PaperTable model={tableModel} label={label} />
      ) : tableHtml ? (
        <div className={styles.paperTableScroll} dangerouslySetInnerHTML={{ __html: tableHtml }} />
      ) : asset ? (
        <Image
          src={paperAssetUrl(paperId, asset.assetId)}
          alt={caption || label}
          className={styles.visualImage}
          loading="lazy"
          width={asset.width}
          height={asset.height}
          unoptimized
        />
      ) : (
        <div className={styles.assetMissing}>Asset unavailable</div>
      )}
      {caption && (!isEquation || caption !== equationText) ? <figcaption><strong>{label}.</strong> {stripLeadingLabel(caption, label)}</figcaption> : null}
    </figure>
  )
}

function SourcePreviewModal({
  paperId,
  title,
  source,
  assetUrl,
  assetMimeType,
  width,
  height,
  onClose,
}: {
  paperId: string
  title: string
  source?: PaperSourceRegion
  assetUrl?: string
  assetMimeType?: string
  width?: number
  height?: number
  onClose: () => void
}) {
  const isHtmlAsset = assetMimeType?.toLowerCase().includes("html")
  return (
    <div className={styles.previewBackdrop} role="dialog" aria-modal="true" aria-label="Source preview" data-open-reader-keep-open>
      <div className={styles.previewDialog}>
        <div className={styles.previewHeader}>
          <strong>{title}</strong>
          <button type="button" className={styles.iconButton} title="Close" onClick={onClose}>
            <X size={17} aria-hidden="true" />
          </button>
        </div>
        {assetUrl && isHtmlAsset ? (
          <iframe
            className={styles.previewFrame}
            src={assetUrl}
            title={title}
            width={width ?? 900}
            height={height ?? 640}
          />
        ) : assetUrl ? (
          <Image src={assetUrl} alt={title} width={width ?? 900} height={height ?? 640} unoptimized />
        ) : source ? (
          <Image
            src={paperSourcePreviewUrl(paperId, source)}
            alt={title}
            width={Math.max(1, Math.round((source.bbox.x1 - source.bbox.x0) * 4))}
            height={Math.max(1, Math.round((source.bbox.y1 - source.bbox.y0) * 4))}
            unoptimized
          />
        ) : null}
      </div>
    </div>
  )
}

type PaperTableModel = {
  alignments?: string[]
  rows: Array<{
    cells: Array<{
      text?: string
      html?: string
      colspan?: number
      rowspan?: number
      align?: string
      classes?: string[]
    }>
    rulesBefore?: string[]
    rowColor?: string | null
    zebra?: string | null
  }>
}

function isPaperTableModel(value: unknown): value is PaperTableModel {
  return Boolean(value && typeof value === "object" && Array.isArray((value as PaperTableModel).rows))
}

function PaperTable({ model, label }: { model: PaperTableModel; label: string }) {
  return (
    <div className={styles.paperTableScroll}>
      <table className={styles.paperCompiledTable} aria-label={label}>
        <tbody>
          {model.rows.map((row, rowIndex) => {
            const rowClasses = [
              styles.paperTableRow,
              ...(row.rulesBefore ?? []).map(tableRuleClass).filter(Boolean),
              tableClass(row.rowColor ?? row.zebra),
            ].filter(Boolean).join(" ")
            return (
              <tr key={rowIndex} className={rowClasses}>
                {row.cells.map((cell, cellIndex) => {
                  const Tag = rowIndex === 0 ? "th" : "td"
                  const align = cell.align || model.alignments?.[cellIndex]
                  const className = [
                    styles.paperTableCell,
                    align === "left" ? styles.alignLeft : align === "right" ? styles.alignRight : styles.alignCenter,
                    ...(cell.classes ?? []).map(tableClass).filter(Boolean),
                  ].join(" ")
                  return (
                    <Tag
                      key={cellIndex}
                      className={className}
                      colSpan={Math.max(1, cell.colspan ?? 1)}
                      rowSpan={Math.max(1, cell.rowspan ?? 1)}
                      dangerouslySetInnerHTML={{ __html: cell.html || escapeHtml(cell.text || "") }}
                    />
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ReferencesSection({ references }: { references: PaperReference[] }) {
  if (!references.length) return null
  return (
    <section id="references" className={`${styles.readerSection} ${styles.referencesSection}`}>
      <h2>References</h2>
      <ol className={styles.referenceList}>
        {references.map((reference) => (
          <li key={reference.id} id={reference.id} className={styles.referenceItem}>
            <span className={styles.referenceLabel}>{reference.label}</span>
            <span>{reference.text}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function tableClass(value?: string | null) {
  if (!value) return ""
  const map: Record<string, string> = {
    paperTableColorRed: styles.paperTableColorRed,
    paperTableColorBlue: styles.paperTableColorBlue,
    paperTableColorGray: styles.paperTableColorGray,
    paperTableColorNeutral: styles.paperTableColorNeutral,
  }
  return map[value] ?? ""
}

function tableRuleClass(value?: string | null) {
  if (!value) return ""
  const map: Record<string, string> = {
    toprule: styles.rule_toprule,
    midrule: styles.rule_midrule,
    bottomrule: styles.rule_bottomrule,
    cmidrule: styles.rule_cmidrule,
    hline: styles.rule_midrule,
  }
  return map[value] ?? ""
}

function stripLeadingLabel(caption: string, label: string) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return caption.replace(new RegExp(`^${escaped}\\s*[:.]?\\s*`, "i"), "").trim()
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

type ParagraphSegment = {
  text: string
  inlineSpan?: PaperInlineSpan
  selection?: ReaderSelection
}

function buildParagraphSegments(paragraph: ReaderParagraph, selections: ReaderSelection[]): ParagraphSegment[] {
  const spans = normalizeParagraphInlineSpans(paragraph)
  if (!spans.length) return applySelectionSegments([{ text: paragraph.text }], selections)
  const segments: ParagraphSegment[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) {
      segments.push({ text: paragraph.text.slice(cursor, span.start) })
    }
    segments.push({ text: paragraph.text.slice(span.start, span.end) || span.text, inlineSpan: span })
    cursor = Math.max(cursor, span.end)
  }
  if (cursor < paragraph.text.length) {
    segments.push({ text: paragraph.text.slice(cursor) })
  }
  return applySelectionSegments(segments, selections)
}

function normalizeParagraphInlineSpans(paragraph: ReaderParagraph) {
  const spans = paragraph.inlineSpans ?? []
  return spans
    .filter((span) => span.start >= 0 && span.end <= paragraph.text.length && span.start < span.end)
    .sort((left, right) => left.start - right.start)
}

function applySelectionSegments(baseSegments: ParagraphSegment[], selections: ReaderSelection[]) {
  const text = baseSegments.map((segment) => segment.text).join("")
  const sorted = selections
    .filter((selection) => selection.startOffset >= 0 && selection.endOffset <= text.length && selection.startOffset < selection.endOffset)
    .sort((a, b) => a.startOffset - b.startOffset)
  const segments: ParagraphSegment[] = []
  let cursor = 0
  for (const selection of sorted) {
    if (selection.startOffset < cursor) continue
    if (selection.startOffset > cursor) segments.push(...sliceParagraphSegments(baseSegments, cursor, selection.startOffset))
    segments.push(...sliceParagraphSegments(baseSegments, selection.startOffset, selection.endOffset).map((segment) => ({ ...segment, selection })))
    cursor = selection.endOffset
  }
  if (cursor < text.length) segments.push(...sliceParagraphSegments(baseSegments, cursor, text.length))
  return segments.length ? segments : [{ text }]
}

function sliceParagraphSegments(segments: ParagraphSegment[], start: number, end: number) {
  const sliced: ParagraphSegment[] = []
  let cursor = 0
  for (const segment of segments) {
    const segmentStart = cursor
    const segmentEnd = cursor + segment.text.length
    cursor = segmentEnd
    if (segmentEnd <= start || segmentStart >= end) continue
    const localStart = Math.max(0, start - segmentStart)
    const localEnd = Math.min(segment.text.length, end - segmentStart)
    sliced.push({ ...segment, text: segment.text.slice(localStart, localEnd) })
  }
  return sliced
}

function renderParagraphSegment(segment: ParagraphSegment, index: number) {
  const span = segment.inlineSpan
  if (!span) return segment.text
  if (span.type === "math") {
    return <InlineMathRenderer key={index} value={span.latex} fallback={segment.text || span.text} />
  }
  if (span.type === "ref") {
    return (
      <button
        key={index}
        type="button"
        className={styles.inlineRefLink}
        onClick={(event) => {
          event.stopPropagation()
          const targetId = span.targetBlockId || span.sectionId
          if (targetId) scrollToReaderTarget(targetId)
        }}
      >
        {segment.text || span.text}
      </button>
    )
  }
  if (span.type === "citation") {
    return (
      <span key={index} className={styles.inlineCitationGroup}>
        {renderCitationLinks(span, segment.text || span.text)}
      </span>
    )
  }
  return segment.text
}

function renderCitationLinks(span: Extract<PaperInlineSpan, { type: "citation" }>, fallback: string) {
  const citations = span.citations ?? []
  const validCitations = citations.filter((citation) => citation.referenceId && citation.number)
  if (!validCitations.length) return fallback || "[?]"
  const citationByNumber = new Map(validCitations.map((citation) => [citation.number, citation]))
  const display = fallback || span.text
  return display.split(/(\d+)/).map((token, index) => {
    const number = Number(token)
    const citation = Number.isFinite(number) ? citationByNumber.get(number) : undefined
    if (!citation) return <span key={`${token}-${index}`}>{token}</span>
    return (
      <button
        key={`${citation.referenceId}-${index}`}
        type="button"
        className={styles.inlineCitationLink}
        aria-label={`Reference [${citation.number}]`}
        onClick={(event) => {
          event.stopPropagation()
          if (citation.referenceId) scrollToReaderTarget(citation.referenceId)
        }}
      >
        {token}
      </button>
    )
  })
}

function scrollToReaderTarget(id: string) {
  if (typeof document === "undefined") return
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })
}

function ReaderSettingsDock({ settings, onChange }: { settings: ReaderSettings; onChange: (patch: Partial<ReaderSettings>) => void }) {
  return (
    <aside className={styles.settingsDock} data-open-reader-keep-open>
      <button type="button" className={styles.settingsOrb} aria-label="阅读设置">Aa</button>
      <div className={styles.settingsPanel}>
        <div className={styles.settingsTitle}>阅读设置</div>
        <div className={styles.settingRow}><label>字体大小</label><input type="range" min={12} max={38} value={settings.fontSize} onChange={(event) => onChange({ fontSize: Number(event.target.value) })} /></div>
        <div className={styles.settingRow}><label>文本宽度</label><input type="range" min={520} max={2000} value={settings.contentWidth} onChange={(event) => onChange({ contentWidth: Number(event.target.value) })} /></div>
        <div className={styles.themeRow}>{(["light", "warm", "dark"] as const).map((theme) => <button key={theme} type="button" className={`${styles.themeButton} ${settings.theme === theme ? styles.activeTheme : ""}`} onClick={() => onChange({ theme })}>{theme === "light" ? "浅色" : theme === "warm" ? "暖色" : "深色"}</button>)}</div>
      </div>
    </aside>
  )
}

function FloatingToc({ paperId, items, activeSectionId, materialCount, onNavigate, onOpenMaterials }: { paperId: string; items: ReaderTocItem[]; activeSectionId: string | null; materialCount: number; onNavigate: (id: string) => void; onOpenMaterials: () => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [side, setSide] = useState<"left" | "right">("left")
  const [dragging, setDragging] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const offsetRef = useRef({ x: 0, y: 0 })
  const positionRef = useRef<{ x: number; y: number } | null>(null)
  const positionKey = useMemo(() => storageKey(paperId, "toc-position"), [paperId])

  useEffect(() => {
    if (typeof window === "undefined") return
    const saved = safeJsonParse<{ x: number; y: number } | null>(window.localStorage.getItem(positionKey), null)
    if (!saved || !Number.isFinite(saved.x) || !Number.isFinite(saved.y)) return
    const next = {
      x: clamp(saved.x, 8, window.innerWidth - 62),
      y: clamp(saved.y, 58, window.innerHeight - 66),
    }
    positionRef.current = next
    setPosition(next)
    setSide(next.x + 31 > window.innerWidth / 2 ? "right" : "left")
  }, [positionKey])

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragging) return
      const x = Math.max(8, Math.min(window.innerWidth - 62, event.clientX - offsetRef.current.x))
      const y = Math.max(58, Math.min(window.innerHeight - 66, event.clientY - offsetRef.current.y))
      const next = { x, y }
      positionRef.current = next
      setPosition(next)
      setSide(x + 31 > window.innerWidth / 2 ? "right" : "left")
    }
    function onUp() {
      setDragging(false)
      if (positionRef.current) {
        window.localStorage.setItem(positionKey, JSON.stringify(positionRef.current))
      }
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [dragging, positionKey])

  return (
    <div ref={rootRef} className={`${styles.floatingToc} ${side === "right" ? styles.sideRight : styles.sideLeft}`} style={position ? { left: position.x, top: position.y, bottom: "auto" } : undefined} data-open-reader-keep-open>
      <button type="button" className={styles.tocOrb} onMouseDown={(event) => { const rect = rootRef.current?.getBoundingClientRect(); if (rect) { offsetRef.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }; setDragging(true); event.preventDefault() } }}>目</button>
      <nav className={styles.tocPanel}>
        <div className={styles.tocPanelTitle}>悬浮目录 · 可拖动</div>
        {items.map((item) => {
          const level = normalizeTocLevel(item.level)
          const depth = Math.max(0, level - 1)
          return (
            <button
              key={item.id}
              type="button"
              className={`${styles.tocLink} ${activeSectionId === item.id ? styles.activeTocLink : ""}`}
              data-level={level}
              style={{ ["--toc-indent" as string]: `${depth * 14}px` }}
              onClick={() => onNavigate(item.id)}
            >
              <span className={styles.tocLinkText}>
                {item.sectionNumber ? <span className={styles.tocNumber}>{item.sectionNumber}</span> : null}
                {item.sectionNumber ? " " : null}
                <span className={styles.tocTitle}>{item.title}</span>
              </span>
              <small>{item.paragraphCount} 段</small>
            </button>
          )
        })}
        <button type="button" className={styles.tocLink} onClick={onOpenMaterials}><span>阅读素材</span><small>{materialCount}</small></button>
      </nav>
    </div>
  )
}

function SelectionActionMenu({ selection, x, y, onNote, onExplain, onExample, onToggleConfused }: { selection: ReaderSelection; x: number; y: number; onNote: () => void; onExplain: () => void; onExample: () => void; onToggleConfused: () => void }) {
  return (
    <div className={styles.selectionMenu} style={floatingLayerStyle(x, y, 230, 190, 10)} data-open-reader-keep-open>
      <button type="button" className={styles.menuItem} onClick={onNote}>笔记</button>
      <button type="button" className={styles.menuItem} onClick={onExplain}>解释选中内容</button>
      <button type="button" className={styles.menuItem} onClick={onExample}>举例说明</button>
      <button type="button" className={`${styles.menuItem} ${selection.confused ? styles.dangerMenuItem : ""}`} onClick={onToggleConfused}>{selection.confused ? "取消标记为不懂" : "标记为不懂"}</button>
    </div>
  )
}

function ReaderNotePopover({ selection, x, y, onChange }: { selection: ReaderSelection; x: number; y: number; onChange: (value: string) => void }) {
  const [value, setValue] = useState(selection.noteText)
  useEffect(() => { setValue(selection.noteText) }, [selection.id, selection.noteText])
  useEffect(() => {
    if (value === selection.noteText) return
    const timer = window.setTimeout(() => onChange(value), 360)
    return () => window.clearTimeout(timer)
  }, [onChange, selection.noteText, value])
  return (
    <div className={styles.notePopover} style={floatingLayerStyle(x, y, 410, 250, 14)} data-open-reader-keep-open>
      <div className={styles.noteHead}><strong>笔记</strong><span>{selection.sectionTitle}</span></div>
      <div className={styles.selectedPreview}>{selection.selectedText}</div>
      <textarea autoFocus value={value} placeholder="写下你的理解、疑问或复现想法。输入后自动保存。" onChange={(event) => setValue(event.target.value)} />
    </div>
  )
}

type AssistAnswerState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; answer: PaperReaderAnswer }
  | { status: "error"; message: string }

function ReaderAssistDrawer({ drawer, selection, materialSummary, locale, drawerWidth, onWidthChange, onClose, onConfirmExplain, onConfirmExample }: { drawer: DrawerState; selection?: ReaderSelection; materialSummary: ReturnType<typeof makeMaterialSummary>; locale: Locale; drawerWidth: number; onWidthChange: (width: number) => void; onClose: () => void; onConfirmExplain: (id: string, question: string) => void; onConfirmExample: (id: string, question: string) => void }) {
  const [question, setQuestion] = useState("")
  const [answerState, setAnswerState] = useState<AssistAnswerState>({ status: "idle" })
  const resizingRef = useRef(false)
  useEffect(() => { setQuestion(""); setAnswerState({ status: "idle" }) }, [drawer.mode, drawer.selectionId])
  useEffect(() => {
    function onMove(event: MouseEvent) { if (!resizingRef.current) return; onWidthChange(Math.max(360, Math.min(Math.min(window.innerWidth - 80, 920), window.innerWidth - event.clientX - 22))) }
    function onUp() { resizingRef.current = false; document.body.classList.remove(styles.drawerResizingBody) }
    window.addEventListener("mousemove", onMove); window.addEventListener("mouseup", onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [onWidthChange])
  const title = drawer.mode === "materials" ? "阅读素材汇总" : drawer.mode === "example" ? "举例说明" : "解释选中内容"
  async function confirm(useDefault: boolean) {
    if (!selection) return
    const q = useDefault ? "" : question.trim()
    const mode = drawer.mode
    if (mode !== "explain" && mode !== "example") return
    setAnswerState({ status: "loading" })
    try {
      const answer = await askPaper(selection.paperId, buildAssistQuestion(selection, q, mode, locale), locale)
      if (mode === "explain") onConfirmExplain(selection.id, q)
      if (mode === "example") onConfirmExample(selection.id, q)
      setAnswerState({ status: "ready", answer })
    } catch (error) {
      setAnswerState({
        status: "error",
        message: error instanceof Error && error.message ? error.message : "Reader assistant is temporarily unavailable.",
      })
    }
  }
  return (
    <aside className={styles.assistDrawer} style={{ width: `min(${drawerWidth}px, calc(100vw - 44px))` }} data-open-reader-keep-open>
      <div className={styles.drawerResizeHandle} onMouseDown={(event) => { resizingRef.current = true; document.body.classList.add(styles.drawerResizingBody); event.preventDefault(); event.stopPropagation() }} />
      <div className={styles.drawerHead}><strong>{title}</strong><button type="button" className={styles.drawerClose} onClick={onClose}>关闭</button></div>
      <div className={styles.drawerBody}>{drawer.mode === "materials" ? <MaterialSummary summary={materialSummary} /> : selection ? <>
        <div className={styles.drawerCard}><h3>选中内容</h3><p>{selection.selectedText}</p></div>
        <div className={styles.drawerCard}><h3>{drawer.mode === "example" ? "你想要哪种例子？" : "你具体不懂哪里？"}</h3><textarea value={question} placeholder={drawer.mode === "example" ? "可选：比如“用工程实现举例”。不填则基于选中内容生成例子。" : "可选：比如“这句话和上一句有什么关系？” 不填则基于选中内容解释。"} onChange={(event) => setQuestion(event.target.value)} /><div className={styles.drawerActions}><button className={`${styles.smallButton} ${styles.primaryButton}`} disabled={answerState.status === "loading"} onClick={() => void confirm(false)}>{answerState.status === "loading" ? "生成中" : drawer.mode === "example" ? "生成例子" : "生成解释"}</button><button className={styles.smallButton} disabled={answerState.status === "loading"} onClick={() => void confirm(true)}>使用选中内容</button></div><div className={styles.actionHint}>生成成功后才会保留高亮并记录到阅读素材；失败不会留下伪答案。</div></div>
        <AssistAnswerCard state={answerState} mode={drawer.mode} />
      </> : null}</div>
    </aside>
  )
}

function buildAssistQuestion(selection: ReaderSelection, question: string, mode: "explain" | "example", locale: Locale) {
  const intent = mode === "example"
    ? locale === "zh" ? "请基于论文公开 section，为选中内容给出一个贴近论文语境的例子。" : "Use the public paper sections to give a concrete example for the selected passage."
    : locale === "zh" ? "请基于论文公开 section，解释选中内容在论文中的含义。" : "Use the public paper sections to explain what the selected passage means in this paper."
  const userQuestion = question.trim()
  return [
    intent,
    `Section: ${selection.sectionTitle}`,
    `Selected text: ${selection.selectedText}`,
    `Local context: ${selection.surroundingText}`,
    userQuestion ? `Reader question: ${userQuestion}` : null,
  ].filter(Boolean).join("\n")
}

function AssistAnswerCard({ state, mode }: { state: AssistAnswerState; mode: ReaderAssistMode }) {
  const heading = mode === "example" ? "举例说明" : "解释"
  if (state.status === "loading") {
    return <div className={styles.drawerCard}><h3>正在生成</h3><p>正在调用论文问答接口，并基于当前论文公开 section 生成回答。</p></div>
  }
  if (state.status === "error") {
    return <div className={styles.drawerCard}><h3>生成失败</h3><p>{state.message}</p></div>
  }
  if (state.status === "ready") {
    return (
      <div className={styles.drawerCard}>
        <h3>{heading}</h3>
        <p>{state.answer.answer}</p>
        {state.answer.citations.length ? (
          <ul>
            {state.answer.citations.map((citation) => (
              <li key={citation.id}>{citation.label}{citation.textExcerpt ? `: ${citation.textExcerpt}` : ""}</li>
            ))}
          </ul>
        ) : null}
        <p className={styles.actionHint}>置信度：{Math.round(state.answer.confidence * 100)}%{state.answer.cached ? " / 缓存结果" : ""}</p>
      </div>
    )
  }
  return <div className={styles.drawerCard}><h3>等待生成</h3><p>你可以补充自己的疑问，也可以直接使用选中内容。未生成前，这次选择不会被保留为高亮。</p></div>
}

function MaterialSummary({ summary }: { summary: ReturnType<typeof makeMaterialSummary> }) {
  return <>
    <div className={styles.drawerCard}><h3>给后台 Agent 的素材</h3><p>笔记、解释请求、举例请求、标记不懂都会记录。后续后台 Agent 可以基于这些素材生成完整笔记、困惑点列表和个性化复习建议。</p></div>
    <div className={styles.drawerCard}><h3>统计</h3><ul><li>笔记：{summary.stats.noteCount}</li><li>解释：{summary.stats.explainedCount}</li><li>举例：{summary.stats.exampledCount}</li><li>不懂：{summary.stats.confusedCount}</li></ul></div>
    <div className={styles.drawerCard}><h3>选中内容与读者输入</h3>{summary.selections.length ? summary.selections.slice().reverse().map((selection) => <article key={selection.id} className={`${styles.materialItem} ${selection.confused ? styles.confusedItem : selection.explained ? styles.explainItem : selection.exampled ? styles.exampleItem : ""}`}><small>{selection.sectionTitle} / {selection.paragraphId}{selection.noteText.trim() ? " · 笔记" : ""}{selection.explained ? " · 请求解释" : ""}{selection.exampled ? " · 请求举例" : ""}{selection.confused ? " · 标记不懂" : ""}</small><p><b>原文：</b>{selection.selectedText}</p>{selection.noteText.trim() ? <p><b>笔记：</b>{selection.noteText}</p> : null}{selection.explainQuestion.trim() ? <p><b>解释疑问：</b>{selection.explainQuestion}</p> : null}{selection.exampleQuestion.trim() ? <p><b>举例需求：</b>{selection.exampleQuestion}</p> : null}</article>) : <p className={styles.mutedText}>还没有素材。</p>}</div>
  </>
}

function floatingLayerStyle(x: number, y: number, width: number, height: number, padding: number): CSSProperties {
  if (typeof window === "undefined") {
    return { left: Math.max(padding, x), top: Math.max(padding, y) }
  }
  return {
    left: clamp(x, padding, window.innerWidth - width),
    top: clamp(y, padding, window.innerHeight - height),
  }
}
