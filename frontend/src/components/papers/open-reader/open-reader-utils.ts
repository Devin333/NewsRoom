import type { Locale, PaperReaderPayload, PaperSection } from "@/lib/papers/types"
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
    for (let index = 0; index < parts.length; index += 1) {
      const fallbackSectionId = `${reader.paper.id}:pdf-text`
      const usesPdfFallback = isPageDumpSection(section)
      paragraphs.push({
        id: `${section.id}:p${index + 1}`,
        paperId: section.paperId,
        sectionId: usesPdfFallback ? fallbackSectionId : section.id,
        sectionTitle: usesPdfFallback ? pdfTextLabel(locale) : section.title || sectionTypeLabel(section.sectionType, locale),
        sectionType: usesPdfFallback ? "unknown" : section.sectionType,
        index,
        text: parts[index],
        summary: section.summary,
        pageStart: section.pageStart,
        pageEnd: section.pageEnd,
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
      index: 0,
      text: reader.paper.abstractSnippet,
    })
  }
  return paragraphs
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

export function mockExplain(selection: ReaderSelection, question: string, locale: Locale) {
  if (locale === "zh") {
    const prefix = question.trim() ? `你补充的疑问是：“${question.trim()}”。` : "你没有补充具体疑问，所以系统使用默认解释。"
    return `${prefix}这段位于「${selection.sectionTitle}」。结合上下文看，它主要是在说明一个论文主张、方法步骤、实验结论或限制条件。当前上下文是：${selection.surroundingText}`
  }
  return `This selection appears in ${selection.sectionTitle}. In context, it likely states a claim, method step, experimental finding, or limitation. Context: ${selection.surroundingText}`
}

export function mockExample(selection: ReaderSelection, question: string, locale: Locale) {
  if (locale === "zh") {
    const prefix = question.trim() ? `你补充的举例需求是：“${question.trim()}”。` : "你没有指定例子类型，所以系统使用默认类比。"
    return `${prefix}可以把它想象成：一个学生读论文时，不能只凭印象说“这篇论文很强”，而要指出“作者声称 X”，再找到实验表格、方法段落或引用来证明 X。如果找不到证据，这个结论就应该暂时标记为不确定。`
  }
  return `Imagine a reader who cannot just say “this paper is strong”; they must state “the authors claim X” and find a table, method paragraph, or citation that supports X.`
}
