import { fireEvent, render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { PaperDocumentReaderPage } from "@/components/papers/paper-reader"
import { targetForPaperBlock } from "@/lib/paper-reader/interactions"
import type { PaperDocumentResponse } from "@/lib/paper-reader/types"

vi.mock("@/lib/papers/api", () => ({
  recordReaderEvent: vi.fn().mockResolvedValue({}),
}))

describe("PaperDocumentReaderPage", () => {
  it("renders compiled PaperDocument blocks through the Open Reader and keeps AI summary out of the body", () => {
    render(<PaperDocumentReaderPage payload={compiledPayload} locale="en" />)

    expect(screen.getByText("Open Reader")).toBeInTheDocument()
    const article = screen.getByLabelText("Open reader paper body")
    expect(within(article).getByText("This is real PDF paragraph text.")).toBeInTheDocument()
    expect(within(article).getByText("Figure 1: Real figure from the PDF.")).toBeInTheDocument()
    expect(within(article).queryByText("AI generated summary must stay in the panel.")).not.toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Figure 1: Real figure from the PDF." })).toHaveAttribute(
      "src",
      "/api/papers/visual-paper/assets/asset-figure-1",
    )
  })

  it("blocks article rendering for non-compiled documents", () => {
    render(<PaperDocumentReaderPage payload={needsReviewPayload} locale="en" />)

    expect(screen.getByText("Compiled document is not published")).toBeInTheDocument()
    expect(screen.getByText("visual asset is missing")).toBeInTheDocument()
    expect(screen.queryByLabelText("Open reader paper body")).not.toBeInTheDocument()
    expect(screen.queryByText("This legacy section must never become body text.")).not.toBeInTheDocument()
  })

  it("opens source preview from visual blocks with source coordinates", () => {
    render(<PaperDocumentReaderPage payload={compiledPayload} locale="en" />)

    fireEvent.click(screen.getAllByTitle("Open source preview").at(-1)!)

    const preview = screen.getByRole("dialog", { name: "Source preview" })
    const image = within(preview).getByRole("img", { name: "Figure 1" })
    expect(image).toHaveAttribute(
      "src",
      expect.stringContaining("/api/papers/visual-paper/source-preview?page=1&bbox="),
    )
  })

  it("builds reader interaction targets for visual assets", () => {
    const target = targetForPaperBlock(compiledPayload.document!.blocks[2])

    expect(target).toMatchObject({
      targetType: "figure",
      blockId: "block-figure-1",
      assetId: "asset-figure-1",
      pageNumber: 1,
      sourceBox: { x0: 100, y0: 230, x1: 500, y1: 460 },
    })
  })
})

const compiledPayload: PaperDocumentResponse = {
  paper: {
    id: "visual-paper",
    slug: "visual-paper",
    title: "Visual Paper",
    abstractSnippet: "Abstract belongs in metadata.",
    authors: ["A"],
    publishedAt: "2026-05-24T00:00:00Z",
    venue: "arXiv",
    tags: [],
    taskRefs: [],
    methodRefs: [],
    paperUrl: "https://arxiv.org/abs/2605.00001",
    isPublished: true,
    aiSummary: {
      paperId: "visual-paper",
      locale: "en",
      modelRoute: "writer-primary",
      abstractHash: "hash",
      summary: "AI generated summary must stay in the panel.",
      keyInsights: ["Panel only"],
      limitations: [],
      generatedAt: "2026-05-28T00:00:00Z",
      cached: true,
    },
  },
  status: {
    paperId: "visual-paper",
    status: "compiled",
    updatedAt: "2026-05-28T00:00:00Z",
    diagnostics: [],
  },
  document: {
    paperId: "visual-paper",
    schemaVersion: "paper_document_v1",
    status: "compiled",
    title: "Visual Paper",
    compiledAt: "2026-05-28T00:00:00Z",
    sourceHash: "hash",
    paper: { id: "visual-paper", title: "Visual Paper" },
    outline: [{ id: "block-heading-1", blockId: "block-heading-1", title: "Introduction", level: 1, pageNumber: 1 }],
    auxiliary: { aiSummary: "AI generated summary must stay in the panel." },
    blocks: [
      {
        id: "block-heading-1",
        paperId: "visual-paper",
        type: "heading",
        text: "Introduction",
        level: 1,
        pageNumber: 1,
        source: { pageNumber: 1, bbox: { x0: 72, y0: 110, x1: 240, y1: 132 } },
      },
      {
        id: "block-paragraph-1",
        paperId: "visual-paper",
        type: "paragraph",
        text: "This is real PDF paragraph text.",
        pageNumber: 1,
        sectionId: "block-heading-1",
        source: { pageNumber: 1, bbox: { x0: 72, y0: 142, x1: 540, y1: 200 } },
      },
      {
        id: "block-figure-1",
        paperId: "visual-paper",
        type: "figure",
        text: "Figure 1: Real figure from the PDF.",
        pageNumber: 1,
        sectionId: "block-heading-1",
        assetId: "asset-figure-1",
        label: "Figure 1",
        caption: "Figure 1: Real figure from the PDF.",
        source: { pageNumber: 1, bbox: { x0: 100, y0: 230, x1: 500, y1: 460 } },
      },
    ],
  },
  manifest: {
    paperId: "visual-paper",
    schemaVersion: "paper_document_v1",
    createdAt: "2026-05-28T00:00:00Z",
    sourceHash: "hash",
    assets: [
      {
        assetId: "asset-figure-1",
        paperId: "visual-paper",
        kind: "figure",
        fileName: "assets/asset-figure-1.png",
        mimeType: "image/png",
        width: 600,
        height: 320,
        checksum: "checksum",
        pageNumber: 1,
        label: "Figure 1",
        caption: "Figure 1: Real figure from the PDF.",
        source: { pageNumber: 1, bbox: { x0: 100, y0: 230, x1: 500, y1: 460 } },
      },
    ],
  },
  ai: {
    summary: {
      paperId: "visual-paper",
      locale: "en",
      modelRoute: "writer-primary",
      abstractHash: "hash",
      summary: "AI generated summary must stay in the panel.",
      keyInsights: ["Panel only"],
      limitations: [],
      generatedAt: "2026-05-28T00:00:00Z",
      cached: true,
    },
    diagnostics: [],
  },
}

const needsReviewPayload: PaperDocumentResponse = {
  ...compiledPayload,
  status: {
    paperId: "visual-paper",
    status: "needs_review",
    updatedAt: "2026-05-28T00:00:00Z",
    diagnostics: [{ severity: "error", code: "asset_file_missing", message: "visual asset is missing" }],
  },
  document: null,
  manifest: null,
  ai: {
    diagnostics: [{ severity: "error", code: "asset_file_missing", message: "visual asset is missing" }],
  },
}
