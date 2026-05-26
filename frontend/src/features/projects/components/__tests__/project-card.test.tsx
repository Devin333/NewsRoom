import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ProjectCard } from "@/features/projects/components/project-card"
import type { ProjectItem } from "@/types/projects"

const project: ProjectItem = {
  id: "codex",
  slug: "openai-codex",
  name: "codex",
  description: "A coding agent that runs in your terminal.",
  repoUrl: "https://github.com/openai/codex",
  owner: "openai",
  language: "TypeScript",
  stars: 12000,
  forks: 500,
  starGrowth7d: 320,
  qualityScore: 0.91,
  categoryRefs: [{ category: "agent", label: "Agent" }],
  tags: ["devtool"],
}

describe("ProjectCard", () => {
  it("renders real project links and project metadata", () => {
    render(<ProjectCard project={project} />)

    expect(screen.getByRole("link", { name: "codex" })).toHaveAttribute("href", "/projects/openai-codex")
    expect(screen.getByRole("link", { name: /GitHub/i })).toHaveAttribute("href", "https://github.com/openai/codex")
    expect(screen.getByText("TypeScript")).toBeInTheDocument()
    expect(screen.getByText("Agent")).toBeInTheDocument()
    expect(screen.getByText("devtool")).toBeInTheDocument()
    expect(screen.getByText("12K")).toBeInTheDocument()
  })
})
