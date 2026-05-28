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
    expect(within(article).getByText("Real figure from the PDF.")).toBeInTheDocument()
    expect(within(article).getByLabelText("y = Wx + b (1)")).toBeInTheDocument()
    expect(within(article).getByRole("table", { name: "Table 1" })).toBeInTheDocument()
    expect(within(article).getByText("0.99")).toBeInTheDocument()
    expect(within(article).queryByText("UNKNOWN")).not.toBeInTheDocument()
    expect(within(article).queryByText("unknown")).not.toBeInTheDocument()
    expect(screen.queryByText("Figure 1", { selector: "span" })).not.toBeInTheDocument()
    expect(within(article).queryByText("Asset unavailable")).not.toBeInTheDocument()
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

    fireEvent.click(screen.getAllByTitle("Open source preview")[0])

    const preview = screen.getByRole("dialog", { name: "Source preview" })
    const image = within(preview).getByRole("img", { name: "Figure 1" })
    expect(image).toHaveAttribute(
      "src",
      expect.stringContaining("/api/papers/visual-paper/source-preview?page=1&bbox="),
    )
  })

  it("uses the asset itself for source-first visual previews when PDF page crops are unavailable", () => {
    render(<PaperDocumentReaderPage payload={compiledPayload} locale="en" />)

    const tableBlock = document.querySelector<HTMLElement>('[data-block-id="block-table-1"]')
    if (!tableBlock) throw new Error("Expected table block to be rendered")
    fireEvent.click(within(tableBlock).getByTitle("Open source preview"))

    const preview = screen.getByRole("dialog", { name: "Source preview" })
    const frame = within(preview).getByTitle("Table 1")
    expect(frame).toHaveAttribute("src", "/api/papers/visual-paper/assets/asset-table-1")
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

  it("builds reader interaction targets for generated equation blocks", () => {
    const target = targetForPaperBlock(compiledPayload.document!.blocks[3])

    expect(target).toMatchObject({
      targetType: "equation",
      blockId: "block-equation-1",
      assetId: undefined,
      pageNumber: 1,
      sourceBox: { x0: 150, y0: 500, x1: 320, y1: 526 },
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
      {
        id: "block-equation-1",
        paperId: "visual-paper",
        type: "equation",
        text: "y = Wx + b (1)",
        pageNumber: 1,
        sectionId: "block-heading-1",
        label: "Equation 1",
        caption: "y = Wx + b (1)",
        source: { pageNumber: 1, bbox: { x0: 150, y0: 500, x1: 320, y1: 526 } },
      },
      {
        id: "block-table-1",
        paperId: "visual-paper",
        type: "table",
        text: "Table 1: Real table from the TeX source.",
        pageNumber: 1,
        sectionId: "block-heading-1",
        assetId: "asset-table-1",
        label: "Table 1",
        caption: "Table 1: Real table from the TeX source.",
        source: { pageNumber: 1, bbox: { x0: 0, y0: 0, x1: 420, y1: 150 } },
        metadata: {
          sourceProvider: "arxiv-source",
          tableModel: {
            version: 1,
            alignments: ["left", "center"],
            rows: [
              {
                rulesBefore: ["toprule"],
                cells: [
                  { text: "Method", html: "<strong>Method</strong>" },
                  { text: "Score", html: "<strong>Score</strong>" },
                ],
              },
              {
                rulesBefore: ["midrule"],
                cells: [
                  { text: "Ours", html: "Ours", classes: ["paperTableColorGray"] },
                  { text: "0.99", html: "<strong>0.99</strong>", classes: ["paperTableColorBlue"] },
                ],
              },
            ],
          },
        },
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
      {
        assetId: "asset-table-1",
        paperId: "visual-paper",
        kind: "table",
        fileName: "assets/asset-table-1.html",
        mimeType: "text/html; charset=utf-8",
        width: 420,
        height: 150,
        checksum: "checksum-table",
        pageNumber: 1,
        label: "Table 1",
        caption: "Table 1: Real table from the TeX source.",
        source: { pageNumber: 1, bbox: { x0: 0, y0: 0, x1: 420, y1: 150 } },
        metadata: { sourceProvider: "arxiv-source", sourceKind: "tex-table-html" },
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
