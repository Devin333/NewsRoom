import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperRow } from "@/components/papers/paper-row"
import type { Paper } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

const paper: Paper = {
  id: "paper-swe-agent",
  slug: "swe-agent-agent-computer-interfaces",
  title: "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering",
  abstractSnippet: "Language model agents can automate complex software engineering tasks.",
  authors: ["John Yang", "Carlos E. Jimenez"],
  publishedAt: "2024-05-06",
  venue: "arXiv",
  citationCount: 24,
  tags: ["agents"],
  taskRefs: [],
  methodRefs: [],
  githubStars: 19281,
  pdfUrl: "https://arxiv.org/pdf/2405.15793.pdf",
  repoUrl: "https://github.com/SWE-agent/SWE-agent",
  isPublished: true
}

describe("PaperRow", () => {
  beforeEach(() => {
    useUiStore.setState({ locale: "en" })
  })

  it("links PDF and GitHub actions to real destinations and avoids stars per hour copy", () => {
    render(<PaperRow paper={paper} locale="en" onPreview={vi.fn()} />)

    expect(screen.getAllByRole("link", { name: /open paper pdf/i })[0]).toHaveAttribute("href", "https://arxiv.org/pdf/2405.15793.pdf")
    expect(screen.getAllByRole("link", { name: /open github repository/i })[0]).toHaveAttribute("href", "https://github.com/SWE-agent/SWE-agent")
    expect(screen.getAllByText("24").length).toBeGreaterThan(0)
    expect(screen.getByText("CITES")).toBeInTheDocument()
    expect(screen.getAllByText("19.3K").length).toBeGreaterThan(0)
    expect(screen.getByText("STARS")).toBeInTheDocument()
    expect(screen.queryByText(/stars \/ hr/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/github momentum/i)).not.toBeInTheDocument()
  })

  it("does not render a GitHub root link", () => {
    render(<PaperRow paper={{ ...paper, repoUrl: "https://github.com/" }} locale="en" onPreview={vi.fn()} />)

    expect(screen.queryByRole("link", { name: /open github repository/i })).not.toBeInTheDocument()
  })

  it("shows user state badges when available", () => {
    render(
      <PaperRow
        paper={{
          ...paper,
          userState: {
            userId: "user-1",
            paperId: paper.id,
            favorite: true,
            subscribed: true,
            readingStatus: "reading",
            progressPercent: 35,
            updatedAt: "2026-05-24T00:00:00Z"
          }
        }}
        locale="en"
        onPreview={vi.fn()}
      />
    )

    expect(screen.getByText("Favorite")).toBeInTheDocument()
    expect(screen.getByText("Subscribed")).toBeInTheDocument()
  })
})
