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
  },
  {
    id: "paper-reasoning",
    slug: "paper-reasoning",
    title: "Reasoning Paper",
    abstractSnippet: "A paper about reasoning.",
    authors: ["B"],
    publishedAt: "2026-05-25T00:00:00Z",
    citationCount: 11,
    tags: ["reasoning"],
    taskRefs: [{ id: "task-reasoning", slug: "reasoning", name: "Reasoning" }],
    methodRefs: [],
    pdfUrl: "https://arxiv.org/pdf/2605.00002.pdf",
    implementations: [
      {
        id: "impl-reasoning",
        name: "owner/reasoning-paper",
        repoUrl: "https://github.com/owner/reasoning-paper",
        provider: "github"
      }
    ],
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
      paper_count: 2,
      total_count: 2,
      source_count: 1,
      limit: 5000,
      offset: 0,
      papers
    })
    vi.mocked(requestPaperSummary).mockRejectedValue(new Error("summary unavailable"))
  })

  it("syncs period interactions to the URL without rendering page search", async () => {
    render(<TrendingPapersPage locale="en" papers={papers} />)

    await waitFor(() => expect(fetchPapers).toHaveBeenCalledWith({ q: "", period: "all", sort: "trending", limit: 15, offset: 0 }))
    expect(fetchPapers).toHaveBeenCalledWith({ q: "", period: "all", sort: "trending", limit: 5000 })
    expect(screen.getByRole("navigation", { name: /research breadcrumb/i })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/papers")
    expect(screen.getByLabelText(/papers: 2/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/tasks: 2/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/repos(?:itories)?: 2/i)).toBeInTheDocument()
    expect(screen.getByText(/frontend user view/i).closest("span")).not.toHaveAttribute("style")
    expect(screen.getByLabelText("Paper period")).not.toHaveAttribute("style")
    expect(screen.getByLabelText("Paper sort")).not.toHaveAttribute("style")
    expect(screen.getAllByRole("link", { name: /Agents/i })[0]).not.toHaveAttribute("style")
    expect(screen.queryByRole("textbox", { name: /search papers/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Weekly" }))
    expect(replace).toHaveBeenCalledWith("/papers?period=weekly", { scroll: false })
  })

  it("keeps URL query filtering after hiding page search", async () => {
    query = "q=agent"
    render(<TrendingPapersPage locale="en" papers={papers} />)

    await waitFor(() => expect(fetchPapers).toHaveBeenCalledWith({ q: "agent", period: "all", sort: "trending", limit: 15, offset: 0 }))
    expect(fetchPapers).toHaveBeenCalledWith({ q: "agent", period: "all", sort: "trending", limit: 5000 })
    expect(screen.queryByRole("textbox", { name: /search papers/i })).not.toBeInTheDocument()
  })

  it("does not flash unpublished papers while the first list request is pending", () => {
    vi.mocked(fetchPapers).mockReturnValue(new Promise(() => undefined))

    render(
      <TrendingPapersPage
        locale="en"
        papers={[
          ...papers,
          {
            ...papers[0],
            id: "paper-draft",
            slug: "paper-draft",
            title: "Draft Paper",
            isPublished: false
          }
        ]}
      />
    )

    expect(screen.getByText("Agent Paper")).toBeInTheDocument()
    expect(screen.queryByText("Draft Paper")).not.toBeInTheDocument()
    expect(screen.getByLabelText(/papers: 2/i)).toBeInTheDocument()
  })

  it("filters unpublished papers returned by list and dashboard requests", async () => {
    const draftPaper: Paper = {
      ...papers[0],
      id: "paper-draft",
      slug: "paper-draft",
      title: "Draft Paper",
      isPublished: false
    }
    vi.mocked(fetchPapers).mockResolvedValue({
      source: "test",
      query: "",
      period: "all",
      sort: "trending",
      paper_count: 2,
      total_count: 2,
      source_count: 1,
      limit: 5000,
      offset: 0,
      papers: [papers[0], draftPaper]
    })

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("Agent Paper")).toBeInTheDocument()
    expect(screen.queryByText("Draft Paper")).not.toBeInTheDocument()
    expect(screen.getByLabelText(/papers: 1/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Agents\s*1/i })).toBeInTheDocument()
  })

  it("keeps the backend page when the dashboard request fails", async () => {
    vi.mocked(fetchPapers)
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 1,
        total_count: 1,
        source_count: 1,
        limit: 15,
        offset: 0,
        papers: [papers[0]]
      })
      .mockRejectedValueOnce(new Error("dashboard offline"))

    render(<TrendingPapersPage locale="en" papers={papers} />)

    expect(await screen.findByText("Agent Paper")).toBeInTheDocument()
    expect(screen.queryByText("Reasoning Paper")).not.toBeInTheDocument()
    expect(screen.getByText(/API unavailable; showing real cached papers/i)).toBeInTheDocument()
    expect(screen.queryByText(/dashboard offline/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/tasks: 2/i)).toBeInTheDocument()
  })

  it("keeps backend pagination totals when only the dashboard request fails", async () => {
    const pagedPapers = Array.from({ length: 45 }, (_, index): Paper => ({
      id: `paper-${index + 1}`,
      slug: `paper-${index + 1}`,
      title: `Dashboard Offline Paper ${index + 1}`,
      abstractSnippet: `Paper ${index + 1}.`,
      authors: ["A"],
      publishedAt: "2026-05-24T00:00:00Z",
      tags: ["agents"],
      taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
      methodRefs: [],
      pdfUrl: `https://arxiv.org/pdf/2605.${String(index + 1).padStart(5, "0")}.pdf`,
      repoUrl: "https://github.com/owner/paged-paper",
      isPublished: true
    }))
    vi.mocked(fetchPapers)
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 15,
        total_count: pagedPapers.length,
        source_count: 1,
        limit: 15,
        offset: 0,
        papers: pagedPapers.slice(0, 15)
      })
      .mockRejectedValueOnce(new Error("dashboard offline"))

    render(<TrendingPapersPage locale="en" papers={pagedPapers} />)

    expect(await screen.findByText("Dashboard Offline Paper 1")).toBeInTheDocument()
    expect(screen.getByText("1-15 of 45 papers")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Next page" }))
    expect(replace).toHaveBeenCalledWith("/papers?page=2", { scroll: false })
  })

  it("keeps pagination totals at least as large as the current public page", async () => {
    vi.mocked(fetchPapers)
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 2,
        total_count: 0,
        source_count: 1,
        limit: 15,
        offset: 0,
        papers
      })
      .mockRejectedValueOnce(new Error("dashboard offline"))

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("Agent Paper")).toBeInTheDocument()
    expect(screen.getByLabelText(/papers: 2/i)).toBeInTheDocument()
    expect(screen.queryByText(/of 0 papers/i)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument()
  })

  it("preserves backend totals when the dashboard paper window is truncated", async () => {
    const dashboardPapers = Array.from({ length: 5000 }, (_, index): Paper => ({
      id: `paper-${index + 1}`,
      slug: `paper-${index + 1}`,
      title: `Large Catalog Paper ${index + 1}`,
      abstractSnippet: `Paper ${index + 1}.`,
      authors: ["A"],
      publishedAt: "2026-05-24T00:00:00Z",
      tags: ["agents"],
      taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
      methodRefs: [],
      pdfUrl: `https://arxiv.org/pdf/2605.${String(index + 1).padStart(5, "0")}.pdf`,
      repoUrl: "https://github.com/owner/large-catalog-paper",
      isPublished: true
    }))
    vi.mocked(fetchPapers)
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 15,
        total_count: 5015,
        source_count: 1,
        limit: 15,
        offset: 0,
        papers: dashboardPapers.slice(0, 15)
      })
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 5000,
        total_count: 5015,
        source_count: 1,
        limit: 5000,
        offset: 0,
        papers: dashboardPapers
      })

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("Large Catalog Paper 1")).toBeInTheDocument()
    expect(screen.getByText("1-15 of 5015 papers")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Next page" }))
    expect(replace).toHaveBeenCalledWith("/papers?page=2", { scroll: false })
  })

  it("recovers the visible page from dashboard data when the page request fails", async () => {
    vi.mocked(fetchPapers)
      .mockRejectedValueOnce(new Error("page offline"))
      .mockResolvedValueOnce({
        source: "test",
        query: "",
        period: "all",
        sort: "trending",
        paper_count: 2,
        total_count: 2,
        source_count: 1,
        limit: 5000,
        offset: 0,
        papers
      })

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("Agent Paper")).toBeInTheDocument()
    expect(screen.getAllByText("Reasoning Paper").length).toBeGreaterThan(0)
    expect(screen.getByText(/Page request failed; list recovered from available dashboard data/i)).toBeInTheDocument()
    expect(screen.getByText(/page offline/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/papers: 2/i)).toBeInTheDocument()
  })

  it("shows an actionable empty state when no local paper data is available", async () => {
    vi.mocked(fetchPapers).mockResolvedValue({
      source: "empty",
      query: "",
      period: "all",
      sort: "trending",
      paper_count: 0,
      total_count: 0,
      source_count: 0,
      limit: 5000,
      offset: 0,
      dataState: "empty",
      notices: ["No backend, tracked cache, or artifact papers are available."],
      papers: []
    })

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("No verified papers yet")).toBeInTheDocument()
    expect(screen.getByText("Run paper ingest, or set NEWSROOM_PAPERS_DATA_PATH to a real papers cache, then refresh.")).toBeInTheDocument()
  })

  it("keeps search empty state separate from missing data guidance", async () => {
    query = "q=missing"
    vi.mocked(fetchPapers).mockResolvedValue({
      source: "test",
      query: "missing",
      period: "all",
      sort: "trending",
      paper_count: 0,
      total_count: 0,
      source_count: 1,
      limit: 5000,
      offset: 0,
      dataState: "ready",
      notices: [],
      papers: []
    })

    render(<TrendingPapersPage locale="en" papers={[]} />)

    expect(await screen.findByText("No verified papers yet")).toBeInTheDocument()
    expect(screen.getByText("No public papers match the current search or filters. Clear the search, or retry after paper ingest finishes.")).toBeInTheDocument()
    expect(screen.queryByText(/NEWSROOM_PAPERS_DATA_PATH/)).not.toBeInTheDocument()
  })

  it("loads paginated paper pages from the URL", async () => {
    query = "page=2"
    const pagedPapers = Array.from({ length: 60 }, (_, index): Paper => {
      const number = index + 1
      return {
        id: `paper-${number}`,
        slug: `paper-${number}`,
        title: `Paged Paper ${number}`,
        abstractSnippet: `Paper ${number}.`,
        authors: ["A"],
        publishedAt: "2026-05-24T00:00:00Z",
        tags: ["agents"],
        taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
        methodRefs: [],
        pdfUrl: `https://arxiv.org/pdf/2605.${String(number).padStart(5, "0")}.pdf`,
        repoUrl: "https://github.com/owner/paged-paper",
        isPublished: true
      }
    })
    vi.mocked(fetchPapers).mockImplementation(async (params) => {
      const limit = params.limit ?? 15
      const offset = params.offset ?? 0
      const resultPapers = limit === 5000 ? pagedPapers : pagedPapers.slice(offset, offset + limit)
      return {
        source: "test",
        query: params.q ?? "",
        period: params.period ?? "all",
        sort: params.sort ?? "trending",
        paper_count: resultPapers.length,
        total_count: pagedPapers.length,
        source_count: 1,
        limit,
        offset,
        papers: resultPapers
      }
    })

    render(<TrendingPapersPage locale="en" papers={pagedPapers} />)

    expect(await screen.findByText("Paged Paper 16")).toBeInTheDocument()
    expect(fetchPapers).toHaveBeenCalledWith({ q: "", period: "all", sort: "trending", limit: 15, offset: 15 })
    expect(screen.getByText("16-30 of 60 papers")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }))
    expect(replace).toHaveBeenCalledWith("/papers", { scroll: false })
  })

  it("writes the next page to the URL", async () => {
    const pagedPapers = Array.from({ length: 60 }, (_, index): Paper => ({
      id: `paper-${index + 1}`,
      slug: `paper-${index + 1}`,
      title: `Paged Paper ${index + 1}`,
      abstractSnippet: `Paper ${index + 1}.`,
      authors: ["A"],
      publishedAt: "2026-05-24T00:00:00Z",
      tags: ["agents"],
      taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
      methodRefs: [],
      pdfUrl: `https://arxiv.org/pdf/2605.${String(index + 1).padStart(5, "0")}.pdf`,
      repoUrl: "https://github.com/owner/paged-paper",
      isPublished: true
    }))
    vi.mocked(fetchPapers).mockImplementation(async (params) => {
      const limit = params.limit ?? 15
      const offset = params.offset ?? 0
      const resultPapers = limit === 5000 ? pagedPapers : pagedPapers.slice(offset, offset + limit)
      return {
        source: "test",
        query: params.q ?? "",
        period: params.period ?? "all",
        sort: params.sort ?? "trending",
        paper_count: resultPapers.length,
        total_count: pagedPapers.length,
        source_count: 1,
        limit,
        offset,
        papers: resultPapers
      }
    })

    render(<TrendingPapersPage locale="en" papers={pagedPapers} />)

    expect(await screen.findByText("1-15 of 60 papers")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Next page" }))
    expect(replace).toHaveBeenCalledWith("/papers?page=2", { scroll: false })
  })

  it("opens paper drawer via deep-link query", async () => {
    query = "paper=paper-agent"
    render(<TrendingPapersPage locale="en" papers={papers} />)

    expect(await screen.findByRole("dialog", { name: /paper detail/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }))
    expect(replace).toHaveBeenCalledWith("/papers", { scroll: false })
  })
})
