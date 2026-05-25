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
