import type { OpenReaderVisualLayer } from "@/components/papers/open-reader/open-reader-types"
import type { PaperReaderPayload, PaperSection } from "@/lib/papers/types"
import type { PaperBlock, PaperDocumentResponse } from "@/lib/paper-reader/types"

type MutableSection = PaperSection & {
  textParts: string[]
  blockIds: string[]
  blockSources: unknown[]
  sourceOrders: number[]
}

export function paperDocumentToOpenReader(payload: PaperDocumentResponse): {
  reader: PaperReaderPayload
  visualLayer: OpenReaderVisualLayer
} {
  const document = payload.document
  const manifest = payload.manifest
  if (!document || !manifest || payload.status.status !== "compiled") {
    return {
      reader: emptyReaderPayload(payload),
      visualLayer: { blocks: [] },
    }
  }

  const assetsById = new Map(manifest.assets.map((asset) => [asset.assetId, asset]))
  const sections = new Map<string, MutableSection>()
  let currentSectionId = `${payload.paper.id}:compiled-body`
  let currentSectionTitle = document.title || payload.paper.title
  let currentSectionType: PaperSection["sectionType"] = "unknown"
  const visualBlocks: OpenReaderVisualLayer["blocks"] = []

  for (let order = 0; order < document.blocks.length; order += 1) {
    const block = document.blocks[order]
    if (block.type === "heading") {
      currentSectionId = block.sectionId || block.id
      currentSectionTitle = block.text || document.title || payload.paper.title
      currentSectionType = sectionTypeFromTitle(currentSectionTitle)
      ensureSection(sections, payload.paper.id, currentSectionId, currentSectionTitle, block.level ?? 1, currentSectionType, block.pageNumber)
      continue
    }

    if (block.type === "paragraph") {
      const section = ensureSection(
        sections,
        payload.paper.id,
        block.sectionId || currentSectionId,
        currentSectionTitle,
        1,
        currentSectionType,
        block.pageNumber,
      )
      if (block.text?.trim()) {
        section.textParts.push(block.text.trim())
        section.blockIds.push(block.id)
        section.blockSources.push(block.source ?? null)
        section.sourceOrders.push(order)
        section.pageStart = minNumber(section.pageStart, block.pageNumber)
        section.pageEnd = maxNumber(section.pageEnd, block.pageNumber)
      }
      continue
    }

    if (isVisualBlock(block)) {
      const section = ensureSection(
        sections,
        payload.paper.id,
        block.sectionId || currentSectionId,
        currentSectionTitle,
        1,
        currentSectionType,
        block.pageNumber,
      )
      section.pageStart = minNumber(section.pageStart, block.pageNumber)
      section.pageEnd = maxNumber(section.pageEnd, block.pageNumber)
      visualBlocks.push({
        id: block.id,
        paperId: block.paperId,
        sectionId: section.id,
        sectionTitle: section.title,
        sectionType: section.sectionType,
        order,
        block,
        asset: block.assetId ? assetsById.get(block.assetId) : undefined,
        source: block.source,
      })
    }
  }

  const readerSections = Array.from(sections.values())
    .map(finalizeSection)
    .filter((section) => section.textExcerpt.trim() || visualBlocks.some((block) => block.sectionId === section.id))

  return {
    reader: {
      paper: payload.paper,
      sections: readerSections,
      aiSummary: payload.ai?.summary ?? payload.paper.aiSummary ?? null,
      readerNotes: [],
      relatedPapers: [],
      relatedProjects: [],
      relatedNews: [],
      quality: {
        paperId: payload.paper.id,
        pdfAvailable: Boolean(payload.paper.pdfUrl || payload.paper.paperUrl || payload.paper.arxivUrl),
        textExtracted: readerSections.some((section) => section.textExcerpt.trim()),
        summaryAvailable: Boolean(payload.ai?.summary ?? payload.paper.aiSummary),
        implementationVerified: Boolean(payload.paper.implementations?.length),
        benchmarkVerified: Boolean(payload.paper.benchmarks?.length),
        evidenceCoverage: payload.paper.evidenceRefs?.length ? 1 : 0,
        lastUpdatedAt: payload.status.updatedAt,
      },
    },
    visualLayer: { blocks: visualBlocks },
  }
}

function emptyReaderPayload(payload: PaperDocumentResponse): PaperReaderPayload {
  return {
    paper: payload.paper,
    sections: [],
    aiSummary: payload.ai?.summary ?? payload.paper.aiSummary ?? null,
    readerNotes: [],
    relatedPapers: [],
    relatedProjects: [],
    relatedNews: [],
    quality: {
      paperId: payload.paper.id,
      pdfAvailable: Boolean(payload.paper.pdfUrl || payload.paper.paperUrl || payload.paper.arxivUrl),
      textExtracted: false,
      summaryAvailable: Boolean(payload.ai?.summary ?? payload.paper.aiSummary),
      implementationVerified: Boolean(payload.paper.implementations?.length),
      benchmarkVerified: Boolean(payload.paper.benchmarks?.length),
      evidenceCoverage: payload.paper.evidenceRefs?.length ? 1 : 0,
      lastUpdatedAt: payload.status.updatedAt,
    },
  }
}

function ensureSection(
  sections: Map<string, MutableSection>,
  paperId: string,
  id: string,
  title: string,
  level: number,
  sectionType: PaperSection["sectionType"],
  pageNumber?: number,
) {
  const existing = sections.get(id)
  if (existing) {
    return existing
  }
  const section: MutableSection = {
    id,
    paperId,
    title: title || "Paper Body",
    level,
    pageStart: pageNumber,
    pageEnd: pageNumber,
    textExcerpt: "",
    sectionType,
    textParts: [],
    blockIds: [],
    blockSources: [],
    sourceOrders: [],
  }
  sections.set(id, section)
  return section
}

function finalizeSection(section: MutableSection): PaperSection {
  return {
    id: section.id,
    paperId: section.paperId,
    title: section.title,
    level: section.level,
    pageStart: section.pageStart,
    pageEnd: section.pageEnd,
    textExcerpt: section.textParts.join("\n\n"),
    sectionType: section.sectionType,
    metadata: {
      blockIds: section.blockIds,
      blockSources: section.blockSources,
      sourceOrders: section.sourceOrders,
    },
  }
}

function isVisualBlock(block: PaperBlock) {
  return block.type === "figure" || block.type === "table" || block.type === "equation"
}

function sectionTypeFromTitle(title: string): PaperSection["sectionType"] {
  const normalized = title.toLowerCase()
  if (normalized.includes("abstract")) return "abstract"
  if (normalized.includes("introduction")) return "introduction"
  if (normalized.includes("related")) return "related_work"
  if (normalized.includes("method") || normalized.includes("approach")) return "method"
  if (normalized.includes("experiment") || normalized.includes("evaluation")) return "experiment"
  if (normalized.includes("result")) return "result"
  if (normalized.includes("limitation")) return "limitation"
  if (normalized.includes("conclusion")) return "conclusion"
  if (normalized.includes("appendix")) return "appendix"
  return "unknown"
}

function minNumber(left: number | undefined, right: number | undefined) {
  if (right === undefined) return left
  if (left === undefined) return right
  return Math.min(left, right)
}

function maxNumber(left: number | undefined, right: number | undefined) {
  if (right === undefined) return left
  if (left === undefined) return right
  return Math.max(left, right)
}
