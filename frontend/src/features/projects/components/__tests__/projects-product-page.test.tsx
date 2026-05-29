import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ProjectsProductPage } from "@/features/projects/components/projects-product-page"
import { fetchProjectProductSection, fetchProjectsHome } from "@/lib/projects/api"

vi.mock("@/lib/projects/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/projects/api")>()
  return {
    ...actual,
    fetchProjectProductSection: vi.fn(),
    fetchProjectsHome: vi.fn(),
  }
})

describe("ProjectsProductPage", () => {
  afterEach(() => {
    vi.mocked(fetchProjectsHome).mockReset()
    vi.mocked(fetchProjectProductSection).mockReset()
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
