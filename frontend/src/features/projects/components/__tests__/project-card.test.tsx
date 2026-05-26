import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ProjectCard } from "@/features/projects/components/project-card"
import type { ProjectItem } from "@/types/projects"

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
  starGrowth7d: 320,
  qualityScore: 0.91,
  scores: { qualityScore: 0.91, starVelocityScore: 320 },
  categoryRefs: [{ category: "agent_framework", label: "Agent Framework" }],
  categories: ["agent_framework"],
  tags: ["devtool"],
  topics: ["devtool"],
  relationCounts: { papers: 0, news: 0, community: 0 },
}

describe("ProjectCard", () => {
  it("renders real project links and project metadata", () => {
    render(<ProjectCard project={project} />)

    expect(screen.getByRole("link", { name: "codex" })).toHaveAttribute("href", "/tech/repos?project=openai-codex")
    expect(screen.getByRole("link", { name: /open repo/i })).toHaveAttribute("href", "https://github.com/openai/codex")
    expect(screen.getByText("TypeScript")).toBeInTheDocument()
    expect(screen.getByText("Agent Framework")).toBeInTheDocument()
    expect(screen.getByText("devtool")).toBeInTheDocument()
    expect(screen.getByText("12K")).toBeInTheDocument()
  })
})
