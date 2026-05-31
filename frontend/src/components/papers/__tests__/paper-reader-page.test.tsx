import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperReaderPage } from "@/components/papers/shared/paper-reader-page"
import { askPaper, fetchReaderMaterials, recordReaderEvent } from "@/lib/papers/api"
import type { PaperReaderPayload } from "@/lib/papers/types"

vi.mock("@/lib/papers/api", () => ({
  askPaper: vi.fn(),
  fetchReaderMaterials: vi.fn(),
  recordReaderEvent: vi.fn().mockResolvedValue({}),
}))

const reader: PaperReaderPayload = {
  paper: {
    id: "reader-paper",
    slug: "reader-paper",
    title: "Reader Paper",
    abstractSnippet: "The paper introduces grounded reader agents.",
    authors: ["A. Chen", "M. Torres"],
    publishedAt: "2026-05-24T00:00:00Z",
    venue: "arXiv",
    tags: [],
    taskRefs: [],
    methodRefs: [],
    paperUrl: "https://arxiv.org/abs/2605.00001",
    isPublished: true,
  },
  sections: [
    {
      id: "reader-paper:abstract",
      paperId: "reader-paper",
      title: "Abstract",
      level: 1,
      textExcerpt:
        "The paper introduces grounded reader agents that inspect claims before answering. The verifier checks claims against evidence.",
      sectionType: "abstract",
    },
    {
      id: "reader-paper:method",
      paperId: "reader-paper",
      title: "Method",
      level: 1,
      textExcerpt:
        "The method decomposes long-horizon reading into planning, retrieval, verification, and reader-card generation.",
      sectionType: "method",
    },
  ],
  aiSummary: null,
  readerNotes: [],
  relatedPapers: [],
  relatedProjects: [],
  relatedNews: [],
  quality: {
    paperId: "reader-paper",
    pdfAvailable: false,
    textExtracted: true,
    summaryAvailable: false,
    implementationVerified: false,
    benchmarkVerified: false,
    evidenceCoverage: 0,
    lastUpdatedAt: "2026-05-24T00:00:00Z",
  },
}

const pageDumpReader: PaperReaderPayload = {
  ...reader,
  sections: [
    {
      id: "reader-paper:page-1",
      paperId: "reader-paper",
      title: "Page 1",
      level: 1,
      textExcerpt: "Raw PDF page header, authors, and unrelated page text.",
      sectionType: "abstract",
    },
    {
      id: "reader-paper:page-2",
      paperId: "reader-paper",
      title: "Page 2",
      level: 1,
      textExcerpt: "Second raw PDF page dump with figure OCR text.",
      sectionType: "unknown",
    },
    {
      id: "reader-paper:semantic-abstract",
      paperId: "reader-paper",
      title: "Abstract",
      level: 1,
      textExcerpt: "Clean abstract text should be the first visible reader paragraph.",
      sectionType: "abstract",
    },
    {
      id: "reader-paper:semantic-method",
      paperId: "reader-paper",
      title: "Method",
      level: 1,
      textExcerpt: "Clean method text should remain in the table of contents.",
      sectionType: "method",
    },
  ],
}

const onlyPageDumpReader: PaperReaderPayload = {
  ...reader,
  sections: [
    {
      id: "reader-paper:page-1",
      paperId: "reader-paper",
      title: "Page 1",
      level: 1,
      textExcerpt: "Raw page one text remains readable in fallback mode.",
      sectionType: "unknown",
    },
    {
      id: "reader-paper:page-2",
      paperId: "reader-paper",
      title: "Page 2",
      level: 1,
      textExcerpt: "Raw page two text remains readable in fallback mode.",
      sectionType: "unknown",
    },
  ],
}

describe("PaperReaderPage Open Reader", () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.style.removeProperty("--open-reader-progress")
    Element.prototype.scrollIntoView = function scrollIntoView() {}
    vi.mocked(askPaper).mockReset()
    vi.mocked(fetchReaderMaterials).mockReset()
    vi.mocked(fetchReaderMaterials).mockResolvedValue({
      paperId: "reader-paper",
      userId: "reader-user",
      selections: [],
      events: [],
      stats: {
        noteCount: 0,
        explainedCount: 0,
        exampledCount: 0,
        confusedCount: 0,
        materialCount: 0,
      },
    })
    vi.mocked(recordReaderEvent).mockReset()
    vi.mocked(recordReaderEvent).mockResolvedValue({} as Awaited<ReturnType<typeof recordReaderEvent>>)
    vi.mocked(askPaper).mockResolvedValue({
      paperId: "reader-paper",
      locale: "en",
      question: "generated question",
      answer: "The reader agent checks the selected claim against public paper sections.",
      citations: [
        {
          id: "section-reader-paper-abstract",
          label: "Abstract",
          sourceType: "section",
          sectionId: "reader-paper:abstract",
          textExcerpt: "The verifier checks claims against evidence.",
        },
      ],
      confidence: 0.82,
      generatedAt: "2026-05-24T00:00:00Z",
      cached: false,
    })
  })

  it("renders the quiet Open Reader instead of the old PDF and assistant panels", () => {
    render(<PaperReaderPage reader={reader} locale="en" />)

    expect(screen.getByRole("heading", { name: "Reader Paper" })).toBeInTheDocument()
    expect(screen.getByText("Open Reader")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Back to papers" })).toHaveAttribute("href", "/papers")
    expect(screen.getByRole("button", { name: "Reader settings" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Table of contents" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Ask" })).not.toBeInTheDocument()
    expect(screen.queryByText(/PDF viewer/i)).not.toBeInTheDocument()
  })

  it("renders clean semantic sections before PDF page dumps", () => {
    render(<PaperReaderPage reader={pageDumpReader} locale="en" />)

    expect(screen.getByText("Clean abstract text should be the first visible reader paragraph.")).toBeInTheDocument()
    expect(screen.getByText("Clean method text should remain in the table of contents.")).toBeInTheDocument()
    expect(screen.queryByText("Raw PDF page header, authors, and unrelated page text.")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Page 1/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Abstract/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Method/ })).toBeInTheDocument()
  })

  it("collapses pure PDF page dumps into a single fallback TOC section", () => {
    render(<PaperReaderPage reader={onlyPageDumpReader} locale="en" />)

    expect(screen.getByText("Raw page one text remains readable in fallback mode.")).toBeInTheDocument()
    expect(screen.getByText("Raw page two text remains readable in fallback mode.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Page 1/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Page 2/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /PDF Text/ })).toBeInTheDocument()
  })

  it("persists reading settings to localStorage", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    const sliders = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="range"]'))
    fireEvent.change(sliders[0], { target: { value: "28" } })
    fireEvent.change(sliders[1], { target: { value: "960" } })
    fireEvent.click(screen.getByRole("button", { name: "Dark" }))

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:settings") ?? "{}")
      expect(stored).toMatchObject({ fontSize: 28, contentWidth: 960, theme: "dark" })
    })
  })

  it("loads existing v2 reading settings without overwriting them on mount", async () => {
    window.localStorage.setItem("newsroom:open-reader:reader-paper:settings", JSON.stringify({
      fontSize: 24,
      contentWidth: 960,
      theme: "light",
      drawerWidth: 520,
      layoutVersion: 2,
    }))

    render(<PaperReaderPage reader={reader} locale="en" />)

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:settings") ?? "{}")
      expect(stored).toMatchObject({ fontSize: 24, contentWidth: 960, theme: "light", drawerWidth: 520, layoutVersion: 2 })
    })
  })

  it("upgrades old narrow reader settings to the wider layout while preserving theme", async () => {
    window.localStorage.setItem("newsroom:open-reader:reader-paper:settings", JSON.stringify({
      fontSize: 21,
      contentWidth: 960,
      theme: "light",
      drawerWidth: 470,
    }))

    render(<PaperReaderPage reader={reader} locale="en" />)

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:settings") ?? "{}")
      expect(stored).toMatchObject({ contentWidth: 1180, theme: "light", layoutVersion: 2 })
    })
  })

  it("persists the floating TOC drag position to localStorage", async () => {
    render(<PaperReaderPage reader={reader} locale="en" />)

    fireEvent.mouseDown(screen.getByRole("button", { name: "Table of contents" }), { clientX: 28, clientY: 800 })
    fireEvent.mouseMove(window, { clientX: 180, clientY: 860 })
    fireEvent.mouseUp(window)

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:toc-position") ?? "{}")
      expect(stored).toMatchObject({ x: 152, y: 60 })
    })
  })

  it("shows only the action menu after selecting text", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)

    expect(await screen.findByRole("button", { name: "Note" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Explain selection" })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Write your understanding/)).not.toBeInTheDocument()
    expect(screen.queryByText("Explain selection", { selector: "strong" })).not.toBeInTheDocument()
  })

  it("keeps note highlights only after note text is entered", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.change(await screen.findByPlaceholderText(/Write your understanding/), { target: { value: "Important reader-agent claim." } })

    await waitFor(() => {
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        noteText: "Important reader-agent claim.",
        selectedText: "grounded reader agents",
      })
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "note_updated",
        sectionId: "reader-paper:abstract",
        paragraphId: "reader-paper:abstract:p1",
        selectedText: "grounded reader agents",
        payload: expect.objectContaining({
          sectionTitle: "Abstract",
          noteText: "Important reader-agent claim.",
        }),
      }))
    })

    fireEvent.click(document.body)
    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      expect(screen.queryByPlaceholderText(/Write your understanding/)).not.toBeInTheDocument()
    })
  })

  it("keeps note text when the reader clicks away immediately after typing", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.change(await screen.findByPlaceholderText(/Write your understanding/), { target: { value: "Saved before closing." } })
    fireEvent.click(document.body)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        noteText: "Saved before closing.",
        selectedText: "grounded reader agents",
      })
    })
    expect(screen.queryByPlaceholderText(/Write your understanding/)).not.toBeInTheDocument()
  })

  it("loads existing reading material without writing an empty selection set first", async () => {
    const selectionsKey = "newsroom:open-reader:reader-paper:selections"
    const eventsKey = "newsroom:open-reader:reader-paper:events"
    window.localStorage.setItem(selectionsKey, JSON.stringify([
      {
        id: "selection-existing-note",
        paperId: "reader-paper",
        sectionId: "reader-paper:abstract",
        sectionTitle: "Abstract",
        paragraphId: "reader-paper:abstract:p1",
        selectedText: "grounded reader agents",
        surroundingText: "The paper introduces grounded reader agents that inspect claims before answering.",
        startOffset: 21,
        endOffset: 43,
        noteText: "Persisted note from the previous reading session.",
        explainQuestion: "",
        explainAnswer: "",
        exampleQuestion: "",
        exampleAnswer: "",
        explained: false,
        exampled: false,
        confused: false,
        createdAt: "2026-05-24T00:00:00Z",
        updatedAt: "2026-05-24T00:00:00Z",
      }
    ]))
    window.localStorage.setItem(eventsKey, JSON.stringify([]))
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem")

    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id='selection-existing-note']")).not.toBeNull()
    })
    expect(setItemSpy).not.toHaveBeenCalledWith(selectionsKey, "[]")
    expect(JSON.parse(window.localStorage.getItem(selectionsKey) ?? "[]")).toEqual([
      expect.objectContaining({
        id: "selection-existing-note",
        noteText: "Persisted note from the previous reading session.",
      })
    ])
    fireEvent.click(screen.getByRole("button", { name: /Reading materials/ }))
    expect(await screen.findByText(/Persisted note from the previous reading session/)).toBeInTheDocument()
    setItemSpy.mockRestore()
  })

  it("merges backend reader materials into the local Open Reader state", async () => {
    vi.mocked(fetchReaderMaterials).mockResolvedValueOnce({
      paperId: "reader-paper",
      userId: "reader-user",
      selections: [
        {
          selectionId: "selection-remote-note",
          id: "selection-remote-note",
          userId: "reader-user",
          paperId: "reader-paper",
          target: {
            targetType: "text_selection",
            sectionId: "reader-paper:abstract",
            paragraphId: "reader-paper:abstract:p1",
          },
          sectionId: "reader-paper:abstract",
          sectionTitle: "Abstract",
          paragraphId: "reader-paper:abstract:p1",
          selectedText: "grounded reader agents",
          surroundingText: "The paper introduces grounded reader agents that inspect claims before answering.",
          noteText: "Remote backend note.",
          explainQuestion: "Why is this important?",
          exampleQuestion: undefined,
          explained: true,
          exampled: false,
          confused: false,
          status: "explained",
          createdAt: "2026-05-24T00:00:00Z",
          updatedAt: "2026-05-24T00:10:00Z",
        }
      ],
      events: [
        {
          eventId: "event-remote-explanation",
          type: "explanation_generated",
          eventType: "explanation_generated",
          userId: "reader-user",
          paperId: "reader-paper",
          selectionId: "selection-remote-note",
          target: {
            targetType: "text_selection",
            sectionId: "reader-paper:abstract",
            paragraphId: "reader-paper:abstract:p1",
          },
          sectionId: "reader-paper:abstract",
          paragraphId: "reader-paper:abstract:p1",
          selectedText: "grounded reader agents",
          surroundingText: "The paper introduces grounded reader agents that inspect claims before answering.",
          payload: {
            sectionTitle: "Abstract",
            startOffset: 21,
            endOffset: 43,
            question: "Why is this important?",
            answer: "The reader agent claim explains the paper's evidence-first framing.",
          },
          createdAt: "2026-05-24T00:10:00Z",
        }
      ],
      stats: {
        noteCount: 1,
        explainedCount: 1,
        exampledCount: 0,
        confusedCount: 0,
        materialCount: 1,
      },
    })

    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id='selection-remote-note']")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        id: "selection-remote-note",
        noteText: "Remote backend note.",
        explainAnswer: "The reader agent claim explains the paper's evidence-first framing.",
        startOffset: 21,
        endOffset: 43,
      })
    })

    fireEvent.click(screen.getByRole("button", { name: /Reading materials/ }))
    expect(await screen.findByText(/Remote backend note/)).toBeInTheDocument()
    expect(screen.getByText(/The reader agent claim explains the paper's evidence-first framing/)).toBeInTheDocument()
  })

  it("drops stale temporary selections from localStorage on load", async () => {
    const selectionsKey = "newsroom:open-reader:reader-paper:selections"
    const eventsKey = "newsroom:open-reader:reader-paper:events"
    window.localStorage.setItem(selectionsKey, JSON.stringify([
      {
        id: "selection-stale-temp",
        paperId: "reader-paper",
        sectionId: "reader-paper:abstract",
        sectionTitle: "Abstract",
        paragraphId: "reader-paper:abstract:p1",
        selectedText: "grounded reader agents",
        surroundingText: "The paper introduces grounded reader agents that inspect claims before answering.",
        startOffset: 21,
        endOffset: 43,
        noteText: "",
        explainQuestion: "",
        explainAnswer: "",
        exampleQuestion: "",
        exampleAnswer: "",
        explained: false,
        exampled: false,
        confused: false,
        createdAt: "2026-05-24T00:00:00Z",
        updatedAt: "2026-05-24T00:00:00Z",
      }
    ]))
    window.localStorage.setItem(eventsKey, JSON.stringify([
      {
        id: "event-stale-temp",
        type: "selection_created",
        paperId: "reader-paper",
        selectionId: "selection-stale-temp",
        paragraphId: "reader-paper:abstract:p1",
        sectionId: "reader-paper:abstract",
        selectedText: "grounded reader agents",
        createdAt: "2026-05-24T00:00:00Z",
      }
    ]))

    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id='selection-stale-temp']")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem(selectionsKey) ?? "[]")).toEqual([])
      expect(JSON.parse(window.localStorage.getItem(eventsKey) ?? "[]")).toEqual([])
    })
    fireEvent.click(screen.getByRole("button", { name: /Reading materials/ }))
    expect(await screen.findByText("No materials yet.")).toBeInTheDocument()
  })

  it("removes empty note selections and removes cleared notes without other material", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.click(document.body)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")).toEqual([])
    })

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.change(await screen.findByPlaceholderText(/Write your understanding/), { target: { value: "Check the evidence path." } })
    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({ noteText: "Check the evidence path." })
    })

    const mark = container.querySelector<HTMLElement>("[data-selection-id]")!
    fireEvent.click(mark)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.change(await screen.findByPlaceholderText(/Write your understanding/), { target: { value: "" } })

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")).toEqual([])
    })
  })

  it("does not keep a highlight when an explain drawer is closed before generation", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Explain selection" }))
    expect(await screen.findByText("Waiting to generate")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Close" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("closes an unconfirmed drawer on outside click and clears its temporary highlight", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Explain selection" }))
    expect(await screen.findByText("Waiting to generate")).toBeInTheDocument()

    fireEvent.click(document.body)

    await waitFor(() => {
      expect(screen.queryByText("Waiting to generate")).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("keeps a highlight and records material only after explanation is generated", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Explain selection" }))
    fireEvent.click(await screen.findByRole("button", { name: "Use selection" }))

    expect(await screen.findByText("The reader agent checks the selected claim against public paper sections.")).toBeInTheDocument()
    expect(screen.getByText(/Abstract: The verifier checks claims against evidence/)).toBeInTheDocument()
    expect(vi.mocked(askPaper).mock.calls[0][1]).toContain("Selected text: verifier checks claims")
    await waitFor(() => {
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "explanation_generated",
        selectionId: expect.any(String),
        sectionId: "reader-paper:abstract",
        paragraphId: "reader-paper:abstract:p1",
        selectedText: "verifier checks claims",
        payload: expect.objectContaining({
          answer: "The reader agent checks the selected claim against public paper sections.",
          confidence: 0.82,
          cached: false
        })
      }))
    })

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        explained: true,
        selectedText: "verifier checks claims",
        explainAnswer: "The reader agent checks the selected claim against public paper sections."
      })
    })

    fireEvent.click(screen.getByRole("button", { name: "Close" }))
    fireEvent.click(screen.getByRole("button", { name: /Reading materials/ }))
    expect(await screen.findByText(/Explanation answer:/)).toBeInTheDocument()
    expect(screen.getByText(/The reader agent checks the selected claim against public paper sections/)).toBeInTheDocument()
  })

  it("keeps a highlight and records material only after an example is generated", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "long-horizon reading")
    fireEvent.mouseUp(container.querySelectorAll("[data-paragraph-id]")[1])
    fireEvent.click(await screen.findByRole("button", { name: "Show example" }))
    fireEvent.change(await screen.findByPlaceholderText(/implementation-oriented example/), { target: { value: "Use an engineering example." } })
    fireEvent.click(await screen.findByRole("button", { name: "Generate example" }))

    expect(await screen.findByText("The reader agent checks the selected claim against public paper sections.")).toBeInTheDocument()
    expect(vi.mocked(askPaper).mock.calls[0][1]).toContain("Reader question: Use an engineering example.")
    await waitFor(() => {
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "example_generated",
        selectedText: "long-horizon reading",
        payload: expect.objectContaining({
          question: "Use an engineering example.",
          answer: "The reader agent checks the selected claim against public paper sections."
        })
      }))
    })

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        exampled: true,
        exampleQuestion: "Use an engineering example.",
        exampleAnswer: "The reader agent checks the selected claim against public paper sections.",
        selectedText: "long-horizon reading",
      })
    })
  })

  it("keeps local generated material when backend reader event sync fails", async () => {
    vi.mocked(recordReaderEvent).mockRejectedValueOnce(new Error("event stream unavailable"))
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Explain selection" }))
    fireEvent.click(await screen.findByRole("button", { name: "Use selection" }))

    expect(await screen.findByText("The reader agent checks the selected claim against public paper sections.")).toBeInTheDocument()
    expect(await screen.findByText("The answer was saved to local reading materials, but it has not synced to the backend event stream yet.")).toBeInTheDocument()

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        explained: true,
        explainAnswer: "The reader agent checks the selected claim against public paper sections."
      })
    })
  })

  it("keeps local notes when backend note sync fails", async () => {
    vi.mocked(recordReaderEvent).mockRejectedValueOnce(new Error("event stream unavailable"))
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Note" }))
    fireEvent.change(await screen.findByPlaceholderText(/Write your understanding/), { target: { value: "Local note remains available." } })

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        noteText: "Local note remains available.",
        selectedText: "grounded reader agents",
      })
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "note_updated",
        payload: expect.objectContaining({ noteText: "Local note remains available." }),
      }))
    })
  })

  it("does not keep a highlight when generated explanation fails", async () => {
    vi.mocked(askPaper).mockRejectedValueOnce(new Error("reader backend unavailable"))
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "Explain selection" }))
    fireEvent.click(await screen.findByRole("button", { name: "Use selection" }))

    expect(await screen.findByText("reader backend unavailable")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Close" }))
    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")).toEqual([])
    })
  })

  it("toggles confusion marks and removes the highlight when no other material remains", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "planning, retrieval")
    fireEvent.mouseUp(container.querySelectorAll("[data-paragraph-id]")[1])
    fireEvent.click(await screen.findByRole("button", { name: "Mark as unclear" }))

    const mark = await waitFor(() => {
      const current = container.querySelector<HTMLElement>("[data-selection-id]")
      expect(current).not.toBeNull()
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "confusion_marked",
        sectionId: "reader-paper:method",
        paragraphId: "reader-paper:method:p1",
        selectedText: "planning, retrieval",
        payload: expect.objectContaining({ sectionTitle: "Method" }),
      }))
      return current!
    })
    fireEvent.click(mark)
    fireEvent.click(await screen.findByRole("button", { name: "Clear unclear mark" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections).toEqual([])
      expect(recordReaderEvent).toHaveBeenCalledWith("reader-paper", expect.objectContaining({
        type: "confusion_unmarked",
        selectedText: "planning, retrieval",
      }))
    })
  })

  it("cleans temporary UI with outside click and Escape", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    expect(await screen.findByRole("button", { name: "Note" })).toBeInTheDocument()

    fireEvent.click(document.body)
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Note" })).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    expect(await screen.findByRole("button", { name: "Note" })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Note" })).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("keeps dark theme highlight text tied to the reader ink token", () => {
    const css = readFileSync(join(process.cwd(), "src/components/papers/open-reader/open-reader.module.css"), "utf-8")

    expect(css).toContain(".selectionMark")
    expect(css).toMatch(/color:\s*var\(--reader-ink\)/)
    expect(css).toMatch(/-webkit-text-fill-color:\s*var\(--reader-ink\)/)
  })

  it("keeps the floating TOC bounded and scrollable", () => {
    const css = readFileSync(join(process.cwd(), "src/components/papers/open-reader/open-reader.module.css"), "utf-8")

    expect(css).toContain(".tocPanel")
    expect(css).toContain("max-height: min(520px, calc(100vh - 116px))")
    expect(css).toContain("overflow-y: auto")
  })
})

function selectParagraphText(container: HTMLElement, text: string) {
  const textNode = findTextNode(container, text)
  if (!textNode) {
    throw new Error(`Could not find text node containing: ${text}`)
  }
  const fullText = textNode.textContent ?? ""
  const start = fullText.indexOf(text)
  const range = document.createRange()
  range.setStart(textNode, start)
  range.setEnd(textNode, start + text.length)
  range.getBoundingClientRect = () => ({
    x: 12,
    y: 24,
    width: 120,
    height: 22,
    top: 24,
    right: 132,
    bottom: 46,
    left: 12,
    toJSON: () => ({}),
  })
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

function findTextNode(root: Node, text: string): Text | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const node = walker.currentNode
    if (node.textContent?.includes(text)) {
      return node as Text
    }
  }
  return null
}
