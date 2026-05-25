import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { TrendingPapersPage } from "@/components/papers/trending-papers-page"
import { fetchPapers, requestPaperSummary } from "@/lib/papers/api"
import type { Paper } from "@/lib/papers/types"

const replace = vi.fn()
let query = ""

vi.mock("next/navigation", () => ({
  usePathname: () => "/papers",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(query)
}))

vi.mock("@/lib/papers/api", () => ({
  fetchPapers: vi.fn(),
  fetchPaperDetail: vi.fn(),
  requestPaperSummary: vi.fn()
}))

const papers: Paper[] = [
  {
    id: "paper-agent",
    slug: "paper-agent",
    title: "Agent Paper",
    abstractSnippet: "A paper about agents.",
    authors: ["A"],
    publishedAt: "2026-05-24T00:00:00Z",
    citationCount: 7,
    tags: ["agents"],
    taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
    methodRefs: [],
    pdfUrl: "https://arxiv.org/pdf/2605.00001.pdf",
    repoUrl: "https://github.com/owner/agent-paper",
    isPublished: true
  }
]

describe("TrendingPapersPage", () => {
  beforeEach(() => {
    query = ""
    replace.mockReset()
    vi.mocked(fetchPapers).mockReset()
    vi.mocked(requestPaperSummary).mockReset()
    vi.mocked(fetchPapers).mockResolvedValue({
      source: "test",
      query: "",
      period: "all",
      sort: "trending",
      paper_count: 1,
      total_count: 1,
      source_count: 1,
      limit: 1000,
      offset: 0,
      papers
    })
    vi.mocked(requestPaperSummary).mockRejectedValue(new Error("summary unavailable"))
  })

  it("syncs search and period interactions to the URL", async () => {
    render(<TrendingPapersPage locale="en" papers={papers} />)

    await waitFor(() => expect(fetchPapers).toHaveBeenCalledWith({ q: "", period: "all", sort: "trending", limit: 1000 }))

    fireEvent.click(screen.getByRole("button", { name: "Weekly" }))
    expect(replace).toHaveBeenCalledWith("/papers?period=weekly", { scroll: false })

    fireEvent.change(screen.getByRole("textbox", { name: /search papers/i }), { target: { value: "agent" } })
    fireEvent.click(screen.getByRole("button", { name: "Search" }))
    expect(replace).toHaveBeenLastCalledWith("/papers?q=agent", { scroll: false })
  })

  it("opens paper drawer via deep-link query", async () => {
    query = "paper=paper-agent"
    render(<TrendingPapersPage locale="en" papers={papers} />)

    expect(await screen.findByRole("dialog", { name: /paper detail/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(replace).toHaveBeenCalledWith("/papers", { scroll: false })
  })
})
