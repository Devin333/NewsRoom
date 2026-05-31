import type { Locale, PaperReaderPayload, PaperSection } from "@/lib/papers/types"
import type {
  PaperInlineSpan,
  PaperSourceRegion,
} from "@/lib/paper-reader/types"
import type {
  ReaderEvent,
  ReaderEventType,
  ReaderMaterialSummary,
  ReaderParagraph,
  ReaderSelection,
  ReaderSelectionStatus,
  ReaderSettings,
  ReaderTocItem,
} from "./open-reader-types"

export const READER_SETTINGS_LAYOUT_VERSION = 2

export const DEFAULT_READER_SETTINGS: ReaderSettings = {
  fontSize: 21,
  contentWidth: 1180,
  theme: "warm",
  drawerWidth: 470,
  layoutVersion: READER_SETTINGS_LAYOUT_VERSION,
}

export function createId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function nowIso() {
  return new Date().toISOString()
}

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function storageKey(paperId: string, name: string) {
  return `newsroom:open-reader:${paperId}:${name}`
}

export function safeJsonParse<T>(value: string | null, fallback: T): T {
  if (!value) return fallback
  try {
    return JSON.parse(value) as T
  } catch {
    return fallback
  }
}

export function getSelectionStatus(selection: ReaderSelection): ReaderSelectionStatus {
  if (selection.confused) return "confused"
  if (selection.explained) return "explained"
  if (selection.exampled) return "exampled"
  if (selection.noteText.trim()) return "has_note"
  return "temp"
}

export function shouldKeepSelection(selection: ReaderSelection) {
  return Boolean(selection.noteText.trim() || selection.explained || selection.exampled || selection.confused)
}

export function createReaderEvent(
  type: ReaderEventType,
  paperId: string,
  payload: Partial<ReaderEvent> = {},
): ReaderEvent {
  return {
    id: createId("reader-event"),
    type,
    paperId,
    createdAt: nowIso(),
    ...payload,
  }
}

export function buildReaderParagraphs(reader: PaperReaderPayload, locale: Locale): ReaderParagraph[] {
  const paragraphs: ReaderParagraph[] = []
  const sourceSections = selectReaderSections(reader.sections ?? [])

  for (const section of sourceSections) {
    const parts = splitText(section.textExcerpt)
    const metadata = sectionMetadata(section)
    const blockIds = stringArray(metadata?.blockIds)
    const blockSources = sourceArray(metadata?.blockSources)
    const sourceOrders = numberArray(metadata?.sourceOrders)
    const blockInlineSpans = inlineSpanArrayArray(metadata?.blockInlineSpans)
    const sectionNumber = optionalString(metadata?.sectionNumber)
    const sectionLevel = usesFiniteLevel(section.level) ? section.level : 1
    for (let index = 0; index < parts.length; index += 1) {
      const fallbackSectionId = `${reader.paper.id}:pdf-text`
      const usesPdfFallback = isPageDumpSection(section)
      const blockId = blockIds[index]
      paragraphs.push({
        id: blockId || `${section.id}:p${index + 1}`,
        paperId: section.paperId,
        sectionId: usesPdfFallback ? fallbackSectionId : section.id,
        sectionTitle: usesPdfFallback ? pdfTextLabel(locale) : section.title || sectionTypeLabel(section.sectionType, locale),
        sectionType: usesPdfFallback ? "unknown" : section.sectionType,
        sectionLevel: usesPdfFallback ? 1 : sectionLevel,
        sectionNumber: usesPdfFallback ? undefined : sectionNumber,
        index,
        text: parts[index],
        summary: section.summary,
        pageStart: section.pageStart,
        pageEnd: section.pageEnd,
        blockId,
        source: blockSources[index],
        sourceOrder: sourceOrders[index],
        inlineSpans: blockInlineSpans[index],
      })
    }
  }

  if (!paragraphs.length && reader.paper.abstractSnippet) {
    paragraphs.push({
      id: `${reader.paper.id}:abstract:p1`,
      paperId: reader.paper.id,
      sectionId: `${reader.paper.id}:abstract`,
      sectionTitle: locale === "zh" ? "摘要" : "Abstract",
      sectionType: "abstract",
      sectionLevel: 1,
      index: 0,
      text: reader.paper.abstractSnippet,
    })
  }
  return paragraphs
}

function sectionMetadata(section: PaperSection) {
  const metadata = section.metadata
  return metadata && typeof metadata === "object" ? metadata : null
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : []
}

function numberArray(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is number => typeof item === "number" && Number.isFinite(item)) : []
}

function optionalString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined
}

function usesFiniteLevel(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
}

function sourceArray(value: unknown): Array<PaperSourceRegion | undefined> {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!item || typeof item !== "object") return undefined
    const source = item as Partial<PaperSourceRegion>
    return typeof source.pageNumber === "number" && source.bbox ? source as PaperSourceRegion : undefined
  })
}

function inlineSpanArrayArray(value: unknown): Array<PaperInlineSpan[] | undefined> {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (!Array.isArray(item)) return undefined
    const spans = item.filter(isInlineSpan)
    return spans.length ? spans : undefined
  })
}

function isInlineSpan(value: unknown): value is PaperInlineSpan {
  if (!value || typeof value !== "object") return false
  const span = value as Partial<PaperInlineSpan>
  return typeof span.type === "string"
    && typeof span.text === "string"
    && typeof span.start === "number"
    && typeof span.end === "number"
}

function selectReaderSections(sections: PaperSection[]) {
  const semanticSections = sections.filter((section) => !isPageDumpSection(section))
  return semanticSections.length ? semanticSections : sections
}

function isPageDumpSection(section: PaperSection) {
  return /^page\s+\d+$/i.test(section.title.trim())
}

function pdfTextLabel(locale: Locale) {
  return locale === "zh" ? "PDF 文本" : "PDF Text"
}

function splitText(value: string) {
  const cleaned = (value ?? "").replace(/\r\n/g, "\n").trim()
  if (!cleaned) return []
  const parts = cleaned.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean)
  return parts.length ? parts : [cleaned]
}

function sectionTypeLabel(sectionType: string, locale: Locale) {
  if (locale === "zh") {
    const labels: Record<string, string> = {
      abstract: "摘要",
      introduction: "引言",
      method: "方法",
      experiment: "实验",
      result: "结果",
      limitation: "局限",
      implementation: "实现",
      benchmark: "基准评测",
      evidence: "证据",
      conclusion: "结论",
    }
    return labels[sectionType] ?? "正文"
  }
  return sectionType.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ")
}

export function buildReaderToc(paragraphs: ReaderParagraph[]): ReaderTocItem[] {
  const map = new Map<string, ReaderTocItem>()
  for (const paragraph of paragraphs) {
    const existing = map.get(paragraph.sectionId)
    if (existing) existing.paragraphCount += 1
    else {
      map.set(paragraph.sectionId, {
        id: paragraph.sectionId,
        title: paragraph.sectionTitle,
        sectionType: paragraph.sectionType,
        level: paragraph.sectionLevel,
        sectionNumber: paragraph.sectionNumber,
        sourceOrder: paragraph.sourceOrder,
        paragraphCount: 1,
      })
    }
  }
  return Array.from(map.values())
}

export function getSelectionOffsetsWithinElement(container: HTMLElement, range: Range) {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  let offset = 0
  let startOffset: number | null = null
  let endOffset: number | null = null

  while (walker.nextNode()) {
    const node = walker.currentNode
    const length = node.textContent?.length ?? 0
    if (node === range.startContainer) startOffset = offset + range.startOffset
    if (node === range.endContainer) endOffset = offset + range.endOffset
    offset += length
  }

  if (startOffset == null || endOffset == null) return null
  if (startOffset > endOffset) [startOffset, endOffset] = [endOffset, startOffset]
  if (startOffset === endOffset) return null
  return { startOffset, endOffset }
}

export function getSurroundingText(text: string, startOffset: number, endOffset: number) {
  const before = text.slice(Math.max(0, startOffset - 220), startOffset).trim()
  const selected = text.slice(startOffset, endOffset).trim()
  const after = text.slice(endOffset, endOffset + 220).trim()
  return [before, selected, after].filter(Boolean).join(" ")
}

export function makeMaterialSummary(paperId: string, selections: ReaderSelection[], events: ReaderEvent[]): ReaderMaterialSummary {
  const kept = selections.filter(shouldKeepSelection)
  return {
    paperId,
    selections: kept,
    events,
    stats: {
      noteCount: kept.filter((item) => item.noteText.trim()).length,
      explainedCount: kept.filter((item) => item.explained).length,
      exampledCount: kept.filter((item) => item.exampled).length,
      confusedCount: kept.filter((item) => item.confused).length,
    },
  }
}
