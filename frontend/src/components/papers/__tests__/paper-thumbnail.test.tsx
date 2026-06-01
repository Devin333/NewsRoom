import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { PaperThumbnail } from "@/components/papers/paper-thumbnail"
import type { Paper } from "@/lib/papers/types"

describe("PaperThumbnail", () => {
  it("uses cached thumbnailUrl before browser PDF rendering", () => {
    const paper: Paper = {
      id: "paper-1",
      slug: "paper-1",
      title: "Cached Thumbnail Paper",
      abstractSnippet: "A paper with a cached first-page thumbnail.",
      authors: ["A"],
      publishedAt: "2026-05-27",
      tags: [],
      taskRefs: [],
      methodRefs: [],
      paperUrl: "https://arxiv.org/abs/2605.00001",
      pdfUrl: "https://arxiv.org/pdf/2605.00001.pdf",
      thumbnailUrl: "/api/papers/assets/thumbnails/paper-1.png",
      isPublished: true,
    }

    const { container } = render(<PaperThumbnail paper={paper} locale="en" />)

    const thumbnail = container.firstElementChild
    expect(thumbnail).toHaveStyle({
      backgroundImage: "url(/api/papers/assets/thumbnails/paper-1.png)"
    })
  })

  it("can defer browser PDF rendering behind a lightweight placeholder", () => {
    const paper: Paper = {
      id: "paper-2",
      slug: "paper-2",
      title: "Deferred PDF Paper",
      abstractSnippet: "A paper with a PDF.",
      authors: ["A"],
      publishedAt: "2026-05-27",
      tags: [],
      taskRefs: [],
      methodRefs: [],
      pdfUrl: "https://arxiv.org/pdf/2605.00002.pdf",
      isPublished: true,
    }

    render(<PaperThumbnail paper={paper} locale="en" renderPdfPreview={false} />)

    expect(screen.getByText("PDF preview deferred")).toBeInTheDocument()
  })
})
