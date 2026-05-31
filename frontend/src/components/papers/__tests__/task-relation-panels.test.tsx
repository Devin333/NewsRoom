import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CommonMethodsPanel } from "@/components/papers/tasks/common-methods-panel"
import { SisterTasksPanel } from "@/components/papers/tasks/sister-tasks-panel"
import type { MethodRef, Paper, TaskRef } from "@/lib/papers/types"

const agents: TaskRef = { id: "task-agents", slug: "agents", name: "Agents" }
const reasoning: TaskRef = { id: "task-reasoning", slug: "reasoning", name: "Reasoning" }
const planning: MethodRef = { id: "method-planning", slug: "planning", name: "Planning" }
const memory: MethodRef = { id: "method-memory", slug: "agent-memory", name: "Agent Memory" }

describe("task relation panels", () => {
  it("counts related tasks and methods from visible real paper records", () => {
    const papers = [
      paper("one", [agents], [planning]),
      paper("two", [agents, reasoning], [planning, memory]),
      paper("draft", [agents, reasoning], [memory], false)
    ]

    render(
      <>
        <SisterTasksPanel tasks={[agents, reasoning]} papers={papers} locale="en" />
        <CommonMethodsPanel methods={[planning, memory]} papers={papers} locale="en" />
      </>
    )

    expect(screen.getByRole("link", { name: /Agents\s*2/i })).toHaveAttribute("href", "/papers/tasks/agents")
    expect(screen.getByRole("link", { name: /Reasoning\s*1/i })).toHaveAttribute("href", "/papers/tasks/reasoning")
    expect(screen.getByRole("link", { name: /Planning\s*2/i })).toHaveAttribute("href", "/papers/methods/planning")
    expect(screen.getByRole("link", { name: /Agent Memory\s*1/i })).toHaveAttribute("href", "/papers/methods/agent-memory")
  })

  it("hides related task and method entries without visible paper evidence", () => {
    render(
      <>
        <SisterTasksPanel tasks={[agents, reasoning]} papers={[paper("draft-task", [agents], [planning], false)]} locale="en" />
        <CommonMethodsPanel methods={[planning, memory]} papers={[paper("unrelated", [agents], [], true)]} locale="en" />
      </>
    )

    expect(screen.queryByText("Sister Tasks")).not.toBeInTheDocument()
    expect(screen.queryByText("Common Methods")).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Agents/i })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Planning/i })).not.toBeInTheDocument()
  })
})

function paper(id: string, taskRefs: TaskRef[], methodRefs: MethodRef[], isPublished = true): Paper {
  return {
    id,
    slug: id,
    title: id,
    abstractSnippet: id,
    authors: ["NewsRoom"],
    publishedAt: "2026-05-01T00:00:00Z",
    tags: [],
    taskRefs,
    methodRefs,
    isPublished
  }
}
