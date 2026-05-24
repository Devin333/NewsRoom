import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import type { Paper } from "@/lib/papers/types"

const paper: Paper = {
  id: "paper-segment-anything",
  slug: "segment-anything",
  title: "Segment Anything",
  abstractSnippet: "We introduce the Segment Anything project: a new task, model, and dataset for image segmentation.",
  authors: ["Alexander Kirillov", "Eric Mintun"],
  publishedAt: "2023-10-01",
  venue: "ICCV",
  citationCount: 8800,
  tags: ["segmentation"],
  taskRefs: [{ id: "task-vqa", slug: "visual-question-answering", name: "Visual QA" }],
  methodRefs: [{ id: "method-tool-use", slug: "tool-use", name: "Tool Use" }],
  githubStars: 54200,
  arxivUrl: "https://arxiv.org/abs/2304.02643",
  pdfUrl: "https://arxiv.org/pdf/2304.02643.pdf",
  repoUrl: "https://github.com/facebookresearch/segment-anything",
  paperUrl: "https://openaccess.thecvf.com/content/ICCV2023/html/Kirillov_Segment_Anything_ICCV_2023_paper.html",
  isPublished: true
}

describe("PaperDetailDrawer", () => {
  it("renders paper detail sections and real actions", () => {
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(screen.getByRole("dialog", { name: /paper detail/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Segment Anything" })).toBeInTheDocument()
    expect(screen.getByText("TL;DR")).toBeInTheDocument()
    expect(screen.getByText("Abstract")).toBeInTheDocument()
    expect(screen.getByText("Tasks")).toBeInTheDocument()
    expect(screen.getByText("Methods")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /view pdf/i })).toHaveAttribute("href", "https://arxiv.org/pdf/2304.02643.pdf")
    expect(screen.getByRole("link", { name: /code/i })).toHaveAttribute("href", "https://github.com/facebookresearch/segment-anything")
  })

  it("notifies when dismissed", () => {
    const onOpenChange = vi.fn()
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={onOpenChange} />)

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
