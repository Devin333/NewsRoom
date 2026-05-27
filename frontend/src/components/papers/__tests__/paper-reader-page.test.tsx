import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { beforeEach, describe, expect, it } from "vitest"
import { PaperReaderPage } from "@/components/papers/shared/paper-reader-page"
import type { PaperReaderPayload } from "@/lib/papers/types"

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

describe("PaperReaderPage Open Reader", () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.style.removeProperty("--open-reader-progress")
    Element.prototype.scrollIntoView = function scrollIntoView() {}
  })

  it("renders the quiet Open Reader instead of the old PDF and assistant panels", () => {
    render(<PaperReaderPage reader={reader} locale="en" />)

    expect(screen.getByRole("heading", { name: "Reader Paper" })).toBeInTheDocument()
    expect(screen.getByText("Open Reader")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "阅读设置" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "目" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Ask" })).not.toBeInTheDocument()
    expect(screen.queryByText(/PDF viewer/i)).not.toBeInTheDocument()
  })

  it("persists reading settings to localStorage", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    const sliders = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="range"]'))
    fireEvent.change(sliders[0], { target: { value: "28" } })
    fireEvent.change(sliders[1], { target: { value: "960" } })
    fireEvent.click(screen.getByRole("button", { name: "深色" }))

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:settings") ?? "{}")
      expect(stored).toMatchObject({ fontSize: 28, contentWidth: 960, theme: "dark" })
    })
  })

  it("shows only the action menu after selecting text", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)

    expect(await screen.findByRole("button", { name: "笔记" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "解释选中内容" })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/写下你的理解/)).not.toBeInTheDocument()
    expect(screen.queryByText("解释选中内容", { selector: "strong" })).not.toBeInTheDocument()
  })

  it("keeps note highlights only after note text is entered", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "笔记" }))
    fireEvent.change(await screen.findByPlaceholderText(/写下你的理解/), { target: { value: "Important reader-agent claim." } })

    await waitFor(() => {
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        noteText: "Important reader-agent claim.",
        selectedText: "grounded reader agents",
      })
    })

    fireEvent.click(document.body)
    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      expect(screen.queryByPlaceholderText(/写下你的理解/)).not.toBeInTheDocument()
    })
  })

  it("removes empty note selections and removes cleared notes without other material", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "笔记" }))
    fireEvent.click(document.body)

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")).toEqual([])
    })

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "笔记" }))
    fireEvent.change(await screen.findByPlaceholderText(/写下你的理解/), { target: { value: "Check the evidence path." } })
    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({ noteText: "Check the evidence path." })
    })

    const mark = container.querySelector<HTMLElement>("[data-selection-id]")!
    fireEvent.click(mark)
    fireEvent.click(await screen.findByRole("button", { name: "笔记" }))
    fireEvent.change(await screen.findByPlaceholderText(/写下你的理解/), { target: { value: "" } })

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      expect(JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")).toEqual([])
    })
  })

  it("does not keep a highlight when an explain drawer is closed before generation", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "解释选中内容" }))
    expect(await screen.findByText("等待生成")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "关闭" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("closes an unconfirmed drawer on outside click and clears its temporary highlight", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "解释选中内容" }))
    expect(await screen.findByText("等待生成")).toBeInTheDocument()

    fireEvent.click(document.body)

    await waitFor(() => {
      expect(screen.queryByText("等待生成")).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("keeps a highlight and records material only after explanation is generated", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    fireEvent.click(await screen.findByRole("button", { name: "解释选中内容" }))
    fireEvent.click(await screen.findByRole("button", { name: "使用默认" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({ explained: true, selectedText: "verifier checks claims" })
    })
  })

  it("keeps a highlight and records material only after an example is generated", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "long-horizon reading")
    fireEvent.mouseUp(container.querySelectorAll("[data-paragraph-id]")[1])
    fireEvent.click(await screen.findByRole("button", { name: "举例说明" }))
    fireEvent.change(await screen.findByPlaceholderText(/用工程实现举例/), { target: { value: "Use an engineering example." } })
    fireEvent.click(await screen.findByRole("button", { name: "生成例子" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).not.toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections[0]).toMatchObject({
        exampled: true,
        exampleQuestion: "Use an engineering example.",
        selectedText: "long-horizon reading",
      })
    })
  })

  it("toggles confusion marks and removes the highlight when no other material remains", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "planning, retrieval")
    fireEvent.mouseUp(container.querySelectorAll("[data-paragraph-id]")[1])
    fireEvent.click(await screen.findByRole("button", { name: "标记为不懂" }))

    const mark = await waitFor(() => {
      const current = container.querySelector<HTMLElement>("[data-selection-id]")
      expect(current).not.toBeNull()
      return current!
    })
    fireEvent.click(mark)
    fireEvent.click(await screen.findByRole("button", { name: "取消标记为不懂" }))

    await waitFor(() => {
      expect(container.querySelector("[data-selection-id]")).toBeNull()
      const selections = JSON.parse(window.localStorage.getItem("newsroom:open-reader:reader-paper:selections") ?? "[]")
      expect(selections).toEqual([])
    })
  })

  it("cleans temporary UI with outside click and Escape", async () => {
    const { container } = render(<PaperReaderPage reader={reader} locale="en" />)

    selectParagraphText(container, "grounded reader agents")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    expect(await screen.findByRole("button", { name: "笔记" })).toBeInTheDocument()

    fireEvent.click(document.body)
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "笔记" })).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })

    selectParagraphText(container, "verifier checks claims")
    fireEvent.mouseUp(container.querySelector("[data-paragraph-id]")!)
    expect(await screen.findByRole("button", { name: "笔记" })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: "Escape" })
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "笔记" })).not.toBeInTheDocument()
      expect(container.querySelector("[data-selection-id]")).toBeNull()
    })
  })

  it("keeps dark theme highlight text tied to the reader ink token", () => {
    const css = readFileSync(join(process.cwd(), "src/components/papers/open-reader/open-reader.module.css"), "utf-8")

    expect(css).toContain(".selectionMark")
    expect(css).toContain("color:var(--reader-ink)")
    expect(css).toContain("-webkit-text-fill-color:var(--reader-ink)")
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
