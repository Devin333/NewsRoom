import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperReaderPage } from "@/components/papers/shared/paper-reader-page"
import { askPaper } from "@/lib/papers/api"
import type { PaperReaderPayload } from "@/lib/papers/types"

vi.mock("@/lib/papers/api", () => ({
  askPaper: vi.fn()
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
