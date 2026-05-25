import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperReaderPage } from "@/components/papers/shared/paper-reader-page"
import { askPaper, fetchPaperUserState, patchPaperUserState } from "@/lib/papers/api"
import type { PaperReaderPayload } from "@/lib/papers/types"

vi.mock("@/lib/papers/api", () => ({
  askPaper: vi.fn(),
  fetchPaperUserState: vi.fn(),
  patchPaperUserState: vi.fn()
}))

vi.mock("@/components/papers/shared/paper-pdf-viewer", () => ({
  PaperPdfViewer: ({
    pdfUrl,
    title,
    onPageChange,
  }: {
    pdfUrl: string
    title: string
    onPageChange?: (pageNumber: number, numPages: number) => void
  }) => (
    <div data-testid="paper-pdf-viewer" data-pdf-url={pdfUrl}>
      {title} PDF viewer
      <button type="button" onClick={() => onPageChange?.(2, 4)}>
        mock page 2
      </button>
    </div>
  )
}))

const reader: PaperReaderPayload = {
  paper: {
    id: "reader-paper",
    slug: "reader-paper",
    title: "Reader Paper",
    abstractSnippet: "The paper introduces grounded reader agents.",
    authors: ["A"],
    publishedAt: "2026-05-24T00:00:00Z",
    venue: "arXiv",
    tags: [],
    taskRefs: [],
    methodRefs: [],
    paperUrl: "https://arxiv.org/abs/2605.00001",
    isPublished: true
  },
  sections: [
    {
      id: "reader-paper:abstract",
      paperId: "reader-paper",
      title: "Abstract",
      level: 1,
      textExcerpt: "The paper introduces grounded reader agents.",
      sectionType: "abstract"
    },
    {
      id: "reader-paper:method",
      paperId: "reader-paper",
      title: "Method and Task Signals",
      level: 1,
      textExcerpt: "Methods: Retrieval Augmented Generation.",
      sectionType: "method"
    },
    {
      id: "reader-paper:benchmark",
      paperId: "reader-paper",
      title: "Benchmark Results",
      level: 1,
      textExcerpt: "MMLU / accuracy / 91.2",
      sectionType: "benchmark"
    }
  ],
  aiSummary: null,
  readerNotes: [],
  relatedPapers: [],
  relatedProjects: [],
  relatedNews: [],
  quality: {
    paperId: "reader-paper",
    pdfAvailable: false,
    textExtracted: false,
    summaryAvailable: false,
    implementationVerified: false,
    benchmarkVerified: false,
    evidenceCoverage: 0,
    lastUpdatedAt: "2026-05-24T00:00:00Z"
  }
}

describe("PaperReaderPage", () => {
  beforeEach(() => {
    vi.mocked(askPaper).mockReset()
    vi.mocked(fetchPaperUserState).mockReset()
    vi.mocked(patchPaperUserState).mockReset()
    vi.mocked(fetchPaperUserState).mockResolvedValue({
      userId: "user-1",
      paperId: "reader-paper",
      favorite: false,
      subscribed: false,
      readingStatus: "unread",
      progressPercent: 0,
      updatedAt: "2026-05-24T00:00:00Z"
    })
    vi.mocked(patchPaperUserState).mockImplementation(async (_paperId, patch) => ({
      userId: "user-1",
      paperId: "reader-paper",
      favorite: patch.favorite ?? false,
      subscribed: patch.subscribed ?? false,
      readingStatus: patch.readingStatus ?? "unread",
      currentPage: patch.currentPage ?? undefined,
      progressPercent: patch.progressPercent ?? 0,
      updatedAt: "2026-05-24T00:01:00Z"
    }))
  })

  it("renders derived reader sections in the text fallback", () => {
    const noPdfReader: PaperReaderPayload = {
      ...reader,
      paper: {
        ...reader.paper,
        paperUrl: undefined,
        arxivUrl: undefined,
        pdfUrl: undefined
      }
    }

    render(<PaperReaderPage reader={noPdfReader} locale="en" />)

    expect(screen.getByRole("heading", { name: "Method and Task Signals" })).toBeInTheDocument()
    expect(screen.getByText("Methods: Retrieval Augmented Generation.")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Benchmark Results" })).toBeInTheDocument()
    expect(screen.getByText("MMLU / accuracy / 91.2")).toBeInTheDocument()
    expect(screen.getByText("Benchmark")).toBeInTheDocument()
  })

  it("renders controlled PDF viewer when a PDF URL exists", () => {
    render(
      <PaperReaderPage
        reader={{
          ...reader,
          paper: {
            ...reader.paper,
            pdfUrl: "https://arxiv.org/pdf/2605.00001.pdf"
          },
          quality: {
            ...reader.quality,
            pdfAvailable: true
          }
        }}
        locale="en"
      />
    )

    expect(screen.getByTestId("paper-pdf-viewer")).toHaveAttribute(
      "data-pdf-url",
      "https://arxiv.org/pdf/2605.00001.pdf"
    )
    expect(screen.queryByTitle("Reader Paper")).not.toBeInTheDocument()
  })

  it("updates favorite, subscription, reading status, and PDF progress state", async () => {
    render(
      <PaperReaderPage
        reader={{
          ...reader,
          paper: {
            ...reader.paper,
            pdfUrl: "https://arxiv.org/pdf/2605.00001.pdf"
          },
          quality: {
            ...reader.quality,
            pdfAvailable: true
          }
        }}
        locale="en"
      />
    )

    fireEvent.click(await screen.findByRole("button", { name: /favorite/i }))
    await waitFor(() => {
      expect(patchPaperUserState).toHaveBeenNthCalledWith(1, "reader-paper", {
        favorite: true,
        subscribed: undefined,
        readingStatus: undefined,
        currentPage: undefined,
        progressPercent: undefined
      })
    })

    fireEvent.click(screen.getByRole("button", { name: /subscribe/i }))
    await waitFor(() => {
      expect(patchPaperUserState).toHaveBeenNthCalledWith(2, "reader-paper", {
        favorite: undefined,
        subscribed: true,
        readingStatus: undefined,
        currentPage: undefined,
        progressPercent: undefined
      })
    })

    fireEvent.click(screen.getByRole("button", { name: /unread/i }))
    await waitFor(() => {
      expect(patchPaperUserState).toHaveBeenNthCalledWith(3, "reader-paper", {
        favorite: undefined,
        subscribed: undefined,
        readingStatus: "finished",
        currentPage: undefined,
        progressPercent: 100
      })
    })

    fireEvent.click(screen.getByRole("button", { name: /mock page 2/i }))
    await waitFor(() => {
      expect(patchPaperUserState).toHaveBeenNthCalledWith(4, "reader-paper", {
        favorite: undefined,
        subscribed: undefined,
        readingStatus: "reading",
        currentPage: 2,
        progressPercent: 50
      })
    })
  })

  it("renders text extraction quality state", () => {
    const { rerender } = render(<PaperReaderPage reader={reader} locale="en" />)

    expect(screen.getByText(/text missing/i)).toBeInTheDocument()

    rerender(
      <PaperReaderPage
        reader={{
          ...reader,
          quality: {
            ...reader.quality,
            textExtracted: true
          }
        }}
        locale="en"
      />
    )

    expect(screen.getByText(/text extracted/i)).toBeInTheDocument()
  })

  it("renders structured AI summary v2 fields and preserves legacy fallback", () => {
    const legacyReader: PaperReaderPayload = {
      ...reader,
      aiSummary: {
        paperId: "reader-paper",
        locale: "en",
        modelRoute: "writer-primary",
        abstractHash: "abc",
        summary: "Legacy summary still renders.",
        keyInsights: ["Legacy insight"],
        limitations: ["Legacy limitation"],
        generatedAt: "2026-05-24T00:00:00Z",
        cached: true
      }
    }
    const { rerender } = render(<PaperReaderPage reader={legacyReader} locale="en" />)

    expect(screen.getByText("Legacy summary still renders.")).toBeInTheDocument()
    expect(screen.getByText("Legacy insight")).toBeInTheDocument()
    expect(screen.queryByText("Engineering Relevance")).not.toBeInTheDocument()

    rerender(
      <PaperReaderPage
        reader={{
          ...legacyReader,
          aiSummary: {
            ...legacyReader.aiSummary!,
            summary: "Structured summary renders richer reader context.",
            contributions: ["Adds structured reader summaries."],
            methodSummary: "Uses retrieval over public paper sections.",
            experimentSummary: "Reports benchmark signals when available.",
            engineeringRelevance: "Useful for teams comparing implementations.",
            readingDifficulty: "medium",
            recommendedAudience: ["engineer", "researcher"],
            summarySchemaVersion: "v2"
          }
        }}
        locale="en"
      />
    )

    expect(screen.getByText("Adds structured reader summaries.")).toBeInTheDocument()
    expect(screen.getByText("Uses retrieval over public paper sections.")).toBeInTheDocument()
    expect(screen.getByText("Reports benchmark signals when available.")).toBeInTheDocument()
    expect(screen.getByText("Useful for teams comparing implementations.")).toBeInTheDocument()
    expect(screen.getByText("Difficulty: Medium")).toBeInTheDocument()
    expect(screen.getByText("Engineer")).toBeInTheDocument()
    expect(screen.getByText("Researcher")).toBeInTheDocument()
  })

  it("renders related entity empty and ready states", () => {
    const { rerender } = render(<PaperReaderPage reader={reader} locale="en" />)

    expect(screen.getByText("No related paper, project, or news signals are available yet.")).toBeInTheDocument()

    const relatedReader: PaperReaderPayload = {
      ...reader,
      relatedPapers: [
        {
          id: "related-paper",
          title: "Related Reader Paper",
          slug: "related-reader-paper",
          relationReason: "Shared methods: Retrieval Augmented Generation",
          score: 8
        }
      ],
      relatedProjects: [
        {
          id: "project-repo",
          name: "owner/repo",
          url: "https://github.com/owner/repo",
          sourceType: "implementation",
          relationReason: "Verified implementation repository",
          score: 90
        },
        {
          id: "project-note",
          name: "Offline project note",
          sourceType: "project",
          relationReason: "Project page linked by the paper",
          score: 30
        }
      ],
      relatedNews: [
        {
          id: "news-source",
          title: "Release note",
          url: "https://example.com/news/release",
          sourceType: "official_blog",
          relationReason: "Evidence source",
          score: 70,
          summary: "Public source context."
        }
      ]
    }

    rerender(<PaperReaderPage reader={relatedReader} locale="en" />)

    expect(screen.getByRole("link", { name: /Related Reader Paper/ })).toHaveAttribute("href", "/papers/related-reader-paper")
    expect(screen.getByRole("link", { name: /owner\/repo/ })).toHaveAttribute("href", "https://github.com/owner/repo")
    expect(screen.getByText("Offline project note").closest("a")).toBeNull()
    expect(screen.getByRole("link", { name: /Release note/ })).toHaveAttribute("href", "https://example.com/news/release")
    expect(screen.getByText("Public source context.")).toBeInTheDocument()
  })

  it("asks the paper and renders answer citations", async () => {
    vi.mocked(askPaper).mockResolvedValue({
      paperId: "reader-paper",
      locale: "en",
      question: "What does it introduce?",
      answer: "It introduces grounded reader agents.",
      citations: [
        {
          id: "section-1",
          label: "Abstract",
          sourceType: "section",
          sectionId: "reader-paper:abstract",
          textExcerpt: "The paper introduces grounded reader agents."
        }
      ],
      confidence: 0.82,
      generatedAt: "2026-05-24T00:00:00Z",
      cached: true
    })

    render(<PaperReaderPage reader={reader} locale="en" />)
    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: "What does it introduce?" } })
    fireEvent.click(screen.getByRole("button", { name: "Ask" }))

    expect(await screen.findByText("It introduces grounded reader agents.")).toBeInTheDocument()
    expect(screen.getByText("Abstract / section")).toBeInTheDocument()
    expect(screen.getByText("cached")).toBeInTheDocument()
    expect(askPaper).toHaveBeenCalledWith("reader-paper", "What does it introduce?", "en")
  })

  it("keeps reader visible when ask fails", async () => {
    vi.mocked(askPaper).mockRejectedValue(new Error("agent unavailable"))

    render(<PaperReaderPage reader={reader} locale="en" />)
    fireEvent.change(screen.getByPlaceholderText(/ask a question/i), { target: { value: "Why?" } })
    fireEvent.click(screen.getByRole("button", { name: "Ask" }))

    expect(await screen.findByText("agent unavailable")).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Reader Paper" })).toBeInTheDocument()
  })
})
