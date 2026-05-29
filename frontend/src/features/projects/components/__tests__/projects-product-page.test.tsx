import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ProjectsProductPage } from "@/features/projects/components/projects-product-page"
import {
  addProjectWatchlistItem,
  answerProjectLabQuestion,
  fetchProjectProductSection,
  fetchProjectsHome,
  generateProjectLabSolution,
  startProjectLabSession,
} from "@/lib/projects/api"

vi.mock("@/lib/projects/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/projects/api")>()
  return {
    ...actual,
    addProjectWatchlistItem: vi.fn(),
    answerProjectLabQuestion: vi.fn(),
    fetchProjectProductSection: vi.fn(),
    fetchProjectsHome: vi.fn(),
    generateProjectLabSolution: vi.fn(),
    startProjectLabSession: vi.fn(),
  }
})

describe("ProjectsProductPage", () => {
  afterEach(() => {
    vi.mocked(addProjectWatchlistItem).mockReset()
    vi.mocked(answerProjectLabQuestion).mockReset()
    vi.mocked(fetchProjectsHome).mockReset()
    vi.mocked(fetchProjectProductSection).mockReset()
    vi.mocked(generateProjectLabSolution).mockReset()
    vi.mocked(startProjectLabSession).mockReset()
  })

  it("renders the Projects product home from API v1 data", async () => {
    vi.mocked(fetchProjectsHome).mockResolvedValueOnce({
      hot: [project("p1", "AgentKit")],
      rising: [],
      tools: [],
      cases: [{ id: "case-1", project_id: "p1", title: "Agent workflow case", business_domain: "engineering", module_type: "workflow" }],
      collections: [{ id: "collection-1", slug: "agents", title: "Agent Projects", description: "Real projects.", item_count: 1 }],
      watchlist: [],
      recommendations: [],
      meta: { source: "artifact", source_run_id: "run-project-radar", data_state: "ready", notices: [] },
      metrics: [],
    })

    renderWithQueryClient(<ProjectsProductPage route="home" />)

    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument()
    expect(screen.getAllByText("AgentKit").length).toBeGreaterThan(0)
    expect(screen.getByText("Agent workflow case")).toBeInTheDocument()
    expect(fetchProjectsHome).toHaveBeenCalledWith({ limit: 6 })
  })

  it("renders explicit empty state when no real Project Radar data exists", async () => {
    vi.mocked(fetchProjectProductSection).mockResolvedValueOnce({
      items: [],
      page: { page: 1, page_size: 18, total: 0, has_next: false },
      meta: { source: "none", data_state: "empty", notices: ["No real Project Radar artifacts were found."] },
      metrics: [],
    })

    renderWithQueryClient(<ProjectsProductPage route="hot" />)

    await waitFor(() => expect(fetchProjectProductSection).toHaveBeenCalled())
    expect(await screen.findByText("No Real Project Radar Data")).toBeInTheDocument()
    expect(screen.getAllByText(/will not substitute fake projects/i).length).toBeGreaterThan(0)
  })

  it("starts a Lab session, answers a question, and renders the generated solution", async () => {
    vi.mocked(fetchProjectProductSection).mockResolvedValueOnce({
      hot: [project("p1", "AgentKit")],
      rising: [],
      tools: [],
      cases: [
        { id: "case-1", project_id: "p1", title: "Agent workflow case", business_domain: "engineering", module_type: "workflow" },
        { id: "case-2", project_id: "p1", title: "Retrieval case", business_domain: "research", module_type: "rag" },
        { id: "case-3", project_id: "p1", title: "Ops case", business_domain: "operations", module_type: "monitoring" },
        { id: "case-4", project_id: "p1", title: "Extra case", business_domain: "support", module_type: "workflow" },
      ],
      collections: [],
      watchlist: [],
      recommendations: [],
      meta: readyMeta(),
      metrics: [],
    })
    vi.mocked(startProjectLabSession).mockResolvedValueOnce({
      session: {
        id: "lab-session-1",
        user_problem: "Need a newsroom workflow module",
        selected_case_ids: ["case-1", "case-2", "case-3"],
        current_stage: "clarifying",
        questions: [
          { id: "q-context", question: "Which workflow stage needs the most help?" },
          { id: "q-deploy", question: "What deployment constraint matters most?" },
        ],
      },
    })
    vi.mocked(answerProjectLabQuestion).mockResolvedValueOnce({
      session: {
        id: "lab-session-1",
        user_problem: "Need a newsroom workflow module",
        selected_case_ids: ["case-1", "case-2", "case-3"],
        current_stage: "ready_to_generate",
        questions: [
          { id: "q-context", question: "Which workflow stage needs the most help?", answered_value: "Batch ingestion" },
          { id: "q-deploy", question: "What deployment constraint matters most?" },
        ],
      },
    })
    vi.mocked(generateProjectLabSolution).mockResolvedValueOnce({
      session: {
        id: "lab-session-1",
        user_problem: "Need a newsroom workflow module",
        selected_case_ids: ["case-1", "case-2", "case-3"],
        current_stage: "solution_generated",
        questions: [
          { id: "q-context", question: "Which workflow stage needs the most help?", answered_value: "Batch ingestion" },
          { id: "q-deploy", question: "What deployment constraint matters most?" },
        ],
        generated_solution: "Use AgentKit as the orchestration layer.",
      },
      solution: {
        module: "workflow automation",
        candidate_projects: ["AgentKit"],
      },
    })

    renderWithQueryClient(<ProjectsProductPage route="lab" />)

    const startButton = await screen.findByRole("button", { name: "Start Session" })
    expect(startButton).toBeDisabled()

    fireEvent.change(screen.getByPlaceholderText("Describe the module or product problem"), {
      target: { value: "  Need a newsroom workflow module  " },
    })
    expect(startButton).toBeEnabled()
    fireEvent.click(startButton)

    await waitFor(() =>
      expect(startProjectLabSession).toHaveBeenCalledWith({
        user_problem: "Need a newsroom workflow module",
        selected_case_ids: ["case-1", "case-2", "case-3"],
      })
    )
    expect(await screen.findByText("clarifying")).toBeInTheDocument()
    expect(screen.getByText("Which workflow stage needs the most help?")).toBeInTheDocument()

    const answerButton = screen.getByRole("button", { name: "Answer" })
    expect(answerButton).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText("Answer clarification"), { target: { value: "  Batch ingestion  " } })
    expect(answerButton).toBeEnabled()
    fireEvent.click(answerButton)

    await waitFor(() =>
      expect(answerProjectLabQuestion).toHaveBeenCalledWith("lab-session-1", {
        question_id: "q-context",
        answer: "Batch ingestion",
      })
    )
    expect(await screen.findByText("ready_to_generate")).toBeInTheDocument()
    expect(screen.getByText("What deployment constraint matters most?")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("Answer clarification")).toHaveValue("")

    fireEvent.click(screen.getByRole("button", { name: "Generate Solution" }))

    await waitFor(() => expect(generateProjectLabSolution).toHaveBeenCalledWith("lab-session-1"))
    expect(await screen.findByText(/workflow automation/)).toBeInTheDocument()
    expect(screen.getByText(/candidate_projects/)).toBeInTheDocument()
  })

  it("adds a Watchlist item and refreshes the list after a successful save", async () => {
    const savedItem = {
      id: "watch-1",
      project_id: "project-watch-1",
      watch_reason: "Track release cadence",
      priority: "high" as const,
      status: "active" as const,
    }
    vi.mocked(fetchProjectProductSection)
      .mockResolvedValueOnce({
        items: [],
        meta: readyMeta(),
      })
      .mockResolvedValueOnce({
        items: [savedItem],
        meta: readyMeta(),
      })
    vi.mocked(addProjectWatchlistItem).mockResolvedValueOnce({ item: savedItem })

    renderWithQueryClient(<ProjectsProductPage route="watchlist" />)

    const watchButton = await screen.findByRole("button", { name: "Watch Project" })
    expect(watchButton).toBeDisabled()
    expect(screen.getByText("No Watchlist Items")).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText("Real project id"), { target: { value: "  project-watch-1  " } })
    fireEvent.change(screen.getByPlaceholderText("Watch reason"), { target: { value: "  Track release cadence  " } })
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "high" } })
    expect(watchButton).toBeEnabled()
    fireEvent.click(watchButton)

    await waitFor(() =>
      expect(addProjectWatchlistItem).toHaveBeenCalledWith({
        project_id: "project-watch-1",
        watch_reason: "Track release cadence",
        priority: "high",
      })
    )
    await waitFor(() => expect(fetchProjectProductSection).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("project-watch-1")).toBeInTheDocument()
    expect(screen.getByPlaceholderText("Real project id")).toHaveValue("")
    expect(screen.getByPlaceholderText("Watch reason")).toHaveValue("")
    expect(screen.getByRole("combobox")).toHaveValue("medium")
  })
})

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function project(id: string, name: string) {
  return {
    id,
    slug: id,
    name,
    description: "Real Project Radar project.",
    github_url: "https://github.com/acme/agentkit",
    project_type: "tool",
    tags: ["agent"],
    source_confidence: 0.9,
    hot_score: 0.8,
    metric_summary: { github_stars: 100, github_forks: 5, stars_delta_7d: 10 },
    capability_count: 1,
    case_count: 1,
    source_count: 1,
  }
}

function readyMeta() {
  return { source: "artifact" as const, source_run_id: "run-project-radar", data_state: "ready" as const, notices: [] }
}
