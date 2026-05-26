import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ProjectDetailDrawer } from "@/features/projects/components/project-detail-drawer"
import { fetchProjectDetail } from "@/lib/projects/api"
import type { ProjectItem } from "@/types/projects"

vi.mock("@/lib/projects/api", () => ({
  fetchProjectDetail: vi.fn(),
}))

const project: ProjectItem = {
  id: "codex",
  slug: "openai-codex",
  name: "codex",
  fullName: "openai/codex",
  description: "A coding agent that runs in your terminal.",
  repoUrl: "https://github.com/openai/codex",
  owner: "openai",
  language: "TypeScript",
  stars: 12000,
  forks: 500,
  openIssues: 42,
  starGrowth7d: 320,
  scores: { trendScore: 88, activityScore: 60, evidenceScore: 2 },
  categoryRefs: [{ category: "agent_framework", label: "Agent Framework" }],
  categories: ["agent_framework"],
  tags: ["devtool"],
  topics: ["Agent Framework", "devtool"],
  maturity: "rising",
  relationCounts: { papers: 0, news: 1, community: 1 },
  relatedNews: [{ title: "Codex launch", url: "https://example.com/news", sourceName: "Example" }],
  relatedCommunityTopics: [{ title: "HN discussion", url: "https://news.ycombinator.com/item?id=1", sourceName: "Hacker News" }],
}

describe("ProjectDetailDrawer", () => {
  beforeEach(() => {
    vi.mocked(fetchProjectDetail).mockReset()
    vi.mocked(fetchProjectDetail).mockResolvedValue(project)
  })

  it("loads project detail by slug and renders real project metadata", async () => {
    render(<ProjectDetailDrawer projectSlug="openai-codex" open closeHref="/tech/repos" onOpenChange={vi.fn()} />)

    expect(await screen.findByRole("dialog", { name: /project detail/i })).toBeInTheDocument()
    expect(await screen.findByRole("heading", { name: "codex" })).toBeInTheDocument()
    expect(screen.getAllByText("openai/codex").length).toBeGreaterThan(0)
    expect(screen.getByRole("link", { name: /open repo/i })).toHaveAttribute("href", "https://github.com/openai/codex")
    expect(screen.getByText("Related news")).toBeInTheDocument()
    expect(fetchProjectDetail).toHaveBeenCalledWith("openai-codex")
  })

  it("notifies when dismissed", async () => {
    const onOpenChange = vi.fn()
    render(<ProjectDetailDrawer projectSlug="openai-codex" open closeHref="/tech/repos" onOpenChange={onOpenChange} />)

    fireEvent.click(await screen.findByRole("button", { name: /close project detail/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
