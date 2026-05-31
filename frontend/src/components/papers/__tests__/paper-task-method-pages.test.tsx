import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MethodDetailPage } from "@/components/papers/methods/method-detail-page"
import { MethodsPage } from "@/components/papers/methods/methods-page"
import { TasksPage } from "@/components/papers/tasks/tasks-page"
import { fetchPaperMethodsResult, fetchPapers, fetchPaperTasksResult } from "@/lib/papers/api"
import type { Paper, PaperListResult, PaperMethod } from "@/lib/papers/types"

vi.mock("@/lib/papers/api", () => ({
  fetchPaperMethodsResult: vi.fn(),
  fetchPapers: vi.fn(),
  fetchPaperTasksResult: vi.fn()
}))

const paperResult: PaperListResult = {
  source: "api",
  query: "",
  period: "all",
  sort: "trending",
  paper_count: 1,
  total_count: 1,
  source_count: 1,
  limit: 1000,
  offset: 0,
  papers: [
    {
      id: "paper-1",
      slug: "paper-1",
      title: "Paper One",
      abstractSnippet: "A paper.",
      authors: ["A"],
      publishedAt: "2026-05-24T00:00:00Z",
      tags: [],
      taskRefs: [],
      methodRefs: [],
      paperUrl: "https://arxiv.org/abs/2605.00001",
      isPublished: true
    }
  ]
}

const apiTasks = [
  {
    id: "task-backend",
    slug: "backend-task",
    name: "Backend Task",
    group: "language-models",
    description: "Derived backend task.",
    paperCount: 1,
    benchmarkCount: 0,
    methodCount: 1,
    sisterTasks: [],
    commonMethods: []
  }
]

const apiMethods = [
  {
    id: "method-backend",
    slug: "backend-method",
    name: "Backend Method",
    description: "Derived backend method.",
    paperCount: 1,
    taskCount: 1,
    implementationCount: 0,
    area: "Transformers",
    relatedTasks: [],
    relatedMethods: []
  }
]

const methodDetail: PaperMethod = {
  id: "method-tool-use",
  slug: "tool-use",
  name: "Tool Use",
  description: "Uses external tools and environments.",
  paperCount: 2,
  taskCount: 1,
  implementationCount: 1,
  area: "Agents",
  relatedTasks: [],
  relatedMethods: [],
  commonBenchmarks: [
    {
      id: "benchmark-swe-bench",
      slug: "swe-bench",
      name: "SWE-bench",
      category: "software-engineering"
    }
  ]
}

const methodPapers: Paper[] = [
  {
    id: "paper-swe",
    slug: "paper-swe",
    title: "SWE-agent",
    abstractSnippet: "Agent-computer interfaces evaluated on software engineering tasks.",
    authors: ["A"],
    publishedAt: "2026-05-24T00:00:00Z",
    tags: ["agents"],
    taskRefs: [],
    methodRefs: [{ id: "method-tool-use", slug: "tool-use", name: "Tool Use" }],
    benchmarks: [
      {
        id: "benchmark-swe-bench",
        name: "SWE-bench",
        category: "software-engineering",
        metric: "resolved",
        value: "12.5%"
      }
    ],
    paperUrl: "https://arxiv.org/abs/2605.00001",
    isPublished: true
  }
]

describe("paper task and method pages", () => {
  beforeEach(() => {
    vi.mocked(fetchPaperMethodsResult).mockReset()
    vi.mocked(fetchPapers).mockReset()
    vi.mocked(fetchPaperTasksResult).mockReset()
  })

  it("renders API-backed tasks and visible task fallback", async () => {
    vi.mocked(fetchPaperTasksResult).mockResolvedValueOnce({ tasks: apiTasks, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPapers).mockResolvedValueOnce(paperResult)

    const { unmount } = render(<TasksPage locale="en" />)

    expect(await screen.findByText("Backend Task")).toBeInTheDocument()
    expect(screen.getByText("Language Models")).toBeInTheDocument()
    expect(screen.queryByText(/catalog fallback/i)).not.toBeInTheDocument()
    unmount()

    vi.mocked(fetchPaperTasksResult).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(fetchPapers).mockRejectedValueOnce(new Error("offline"))

    render(<TasksPage locale="en" />)

    expect(await screen.findByText("Paper task API is unavailable; showing taxonomy with real paper-derived counts.")).toBeInTheDocument()
  })

  it("renders API-backed methods and visible method fallback", async () => {
    vi.mocked(fetchPaperMethodsResult).mockResolvedValueOnce({ methods: apiMethods, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPaperTasksResult).mockResolvedValueOnce({ tasks: apiTasks, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPapers).mockResolvedValueOnce(paperResult)

    const { unmount } = render(<MethodsPage locale="en" />)

    expect(await screen.findByText("Backend Method")).toBeInTheDocument()
    expect(screen.getAllByText("Transformers").length).toBeGreaterThan(0)
    expect(screen.queryByText(/catalog fallback/i)).not.toBeInTheDocument()
    unmount()

    vi.mocked(fetchPaperMethodsResult).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(fetchPaperTasksResult).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(fetchPapers).mockRejectedValueOnce(new Error("offline"))

    render(<MethodsPage locale="en" />)

    expect(await screen.findByText("Paper method API is unavailable; showing taxonomy with real paper-derived counts.")).toBeInTheDocument()
  })

  it("opens benchmark evidence from method detail instead of placeholder copy", () => {
    render(<MethodDetailPage method={methodDetail} locale="en" papers={methodPapers} />)

    fireEvent.click(screen.getByRole("button", { name: /SWE-bench/ }))

    expect(screen.getByText("Benchmark Evidence")).toBeInTheDocument()
    expect(screen.getByText(/recorded benchmark fields/i)).toBeInTheDocument()
    expect(screen.getByText("resolved: 12.5%")).toBeInTheDocument()
    expect(screen.queryByText(/placeholder action/i)).not.toBeInTheDocument()
  })
})
