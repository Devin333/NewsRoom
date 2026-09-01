import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ProjectLabSessionPage } from "@/features/projects/components/projects-detail-pages"
import { fetchProjectLabSession, saveProjectLabSession } from "@/lib/projects/api"
import type { ProjectsLabSession } from "@/types/projects"

vi.mock("@/lib/projects/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/projects/api")>()
  return {
    ...actual,
    fetchProjectLabSession: vi.fn(),
    saveProjectLabSession: vi.fn(),
  }
})

describe("ProjectLabSessionPage", () => {
  afterEach(() => {
    vi.mocked(fetchProjectLabSession).mockReset()
    vi.mocked(saveProjectLabSession).mockReset()
  })

  it("offers retry after a save failure and focuses the success announcement", async () => {
    vi.mocked(fetchProjectLabSession).mockResolvedValue({ session: session("solution_generated") })
    vi.mocked(saveProjectLabSession)
      .mockRejectedValueOnce(new Error("Save service unavailable"))
      .mockResolvedValueOnce({ session: session("solution_saved") })

    renderWithQueryClient(<ProjectLabSessionPage sessionId="lab-session-save" />)

    const saveButton = await screen.findByRole("button", { name: "Save Session" })
    expect(saveButton).toBeEnabled()
    fireEvent.click(saveButton)

    expect(await screen.findByRole("alert")).toHaveTextContent("Save service unavailable")
    fireEvent.click(screen.getByRole("button", { name: "Retry Save" }))

    await waitFor(() => expect(saveProjectLabSession).toHaveBeenCalledTimes(2))
    const success = await screen.findByText("Session saved.")
    expect(success).toHaveAttribute("tabindex", "-1")
    expect(document.activeElement).toBe(success)
    expect(saveButton).toHaveAttribute("aria-busy", "false")
  })
})

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function session(stage: ProjectsLabSession["current_stage"]): ProjectsLabSession {
  return {
    id: "lab-session-save",
    user_problem: "Need a durable research workflow",
    selected_case_ids: ["case-1"],
    current_stage: stage,
    next_action: stage === "solution_generated" ? "review_solution" : "none",
    can_generate_solution: false,
    unanswered_question_ids: [],
    questions: [],
    generated_solution: "Use a durable workflow boundary.",
    solution_json: { module: "workflow", data_policy: "real-only" },
    requirement_profile: { goal: "durability" },
    graph_state: { nodes: [], edges: [] },
  }
}
