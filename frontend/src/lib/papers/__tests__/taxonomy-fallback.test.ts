import { describe, expect, it } from "vitest"
import { deriveMethodsFromPapers, deriveTasksFromPapers } from "@/lib/papers/taxonomy-fallback"
import type { MethodRef, Paper, PaperMethod, PaperTask, TaskRef } from "@/lib/papers/types"

const agents: TaskRef = { id: "task-agents", slug: "agents", name: "Agents" }
const reasoning: TaskRef = { id: "task-reasoning", slug: "reasoning", name: "Reasoning" }
const toolUse: MethodRef = { id: "method-tool-use", slug: "tool-use", name: "Tool Use", area: "Agents" }
const planning: MethodRef = { id: "method-planning", slug: "planning", name: "Planning", area: "Agents" }

describe("paper taxonomy fallbacks", () => {
  it("derives task counts from published paper refs and deduplicated real repositories", () => {
    const [derivedAgents, derivedReasoning] = deriveTasksFromPapers([task("agents"), task("reasoning")], [
      paper("new-agent", [agents], [toolUse], {
        publishedAt: "2026-05-20T00:00:00Z",
        repoUrl: "https://github.com/Owner/Repo",
        implementations: [{ id: "impl-duplicate", name: "Owner/Repo", repoUrl: "https://github.com/owner/repo.git" }],
        benchmarks: [{ id: "bench-swe", name: "SWE-bench" }]
      }),
      paper("old-agent", [agents], [planning], {
        publishedAt: "2026-05-01T00:00:00Z",
        implementations: [{ id: "impl-other", name: "Owner/Other", repoUrl: "https://github.com/owner/other" }],
        benchmarks: [{ id: "bench-swe", name: "SWE-bench" }, { id: "bench-web", name: "WebArena" }]
      }),
      paper("draft-agent", [agents], [toolUse], {
        isPublished: false,
        repoUrl: "https://github.com/owner/draft",
        benchmarks: [{ id: "bench-draft", name: "DraftBench" }]
      })
    ])

    expect(derivedAgents).toMatchObject({
      paperCount: 2,
      benchmarkCount: 2,
      methodCount: 2,
      latestPaperIds: ["new-agent", "old-agent"],
      implementationCount: 2
    })
    expect(derivedReasoning.paperCount).toBe(0)
  })

  it("derives method counts from published paper refs and keeps latest ids stable with invalid dates", () => {
    const [derivedToolUse] = deriveMethodsFromPapers([method("tool-use")], [
      paper("invalid-date", [agents], [toolUse], {
        publishedAt: "not-a-date",
        repoUrl: "https://github.com/owner/invalid"
      }),
      paper("newer", [agents, reasoning], [toolUse], {
        publishedAt: "2026-05-21T00:00:00Z",
        repoUrl: "owner/newer"
      }),
      paper("unrelated", [agents], [planning], {
        publishedAt: "2026-05-22T00:00:00Z",
        repoUrl: "https://github.com/owner/unrelated"
      })
    ])

    expect(derivedToolUse).toMatchObject({
      paperCount: 2,
      taskCount: 2,
      implementationCount: 2,
      representativePaperIds: ["newer", "invalid-date"]
    })
  })
})

function task(slug: string): PaperTask {
  return {
    id: `task-${slug}`,
    slug,
    name: slug,
    group: "agents",
    description: slug,
    paperCount: 99,
    benchmarkCount: 99,
    methodCount: 99,
    sisterTasks: [],
    commonMethods: []
  }
}

function method(slug: string): PaperMethod {
  return {
    id: `method-${slug}`,
    slug,
    name: slug,
    description: slug,
    paperCount: 99,
    taskCount: 99,
    implementationCount: 99,
    area: "Agents",
    relatedTasks: [],
    relatedMethods: []
  }
}

function paper(id: string, taskRefs: TaskRef[], methodRefs: MethodRef[], overrides: Partial<Paper> = {}): Paper {
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
    isPublished: true,
    ...overrides
  }
}
