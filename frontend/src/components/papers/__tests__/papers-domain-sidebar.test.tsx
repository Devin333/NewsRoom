import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { PapersDomainSidebar, countPapersForTask } from "@/components/papers/papers-domain-sidebar"
import type { MethodAreaDomain } from "@/lib/papers/metrics"
import type { Paper, TaskRef } from "@/lib/papers/types"

const agents: TaskRef = { id: "task-agents", slug: "agents", name: "Agents" }
const reasoning: TaskRef = { id: "task-reasoning", slug: "reasoning", name: "Reasoning" }
const methods: MethodAreaDomain[] = [
  { slug: "fine-tuning", name: "Fine-Tuning", count: 20 }
]

const papers: Paper[] = [
  paper("one", [agents, reasoning]),
  paper("two", [agents]),
  paper("draft", [agents], false)
]

describe("PapersDomainSidebar", () => {
  it("counts visible domain values from the real public paper stream", () => {
    render(
      <PapersDomainSidebar
        methodAreas={methods}
        topTasks={[agents, reasoning]}
        dashboardPapers={papers}
        locale="en"
      />
    )

    expect(screen.getByRole("link", { name: /Fine-Tuning\s*20/i })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Agents\s*2/i })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Reasoning\s*1/i })).toBeInTheDocument()
    expect(screen.queryByText("33,503")).not.toBeInTheDocument()
    expect(screen.queryByText("1.5x")).not.toBeInTheDocument()
  })

  it("ignores unpublished papers when counting tasks", () => {
    expect(countPapersForTask(papers, "agents")).toBe(2)
  })
})

function paper(id: string, taskRefs: TaskRef[], isPublished = true): Paper {
  return {
    id,
    slug: id,
    title: id,
    abstractSnippet: id,
    authors: ["NewsRoom"],
    publishedAt: "2024-01-01",
    tags: [],
    taskRefs,
    methodRefs: [],
    isPublished
  }
}
