import { fireEvent, render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MethodDetailPage } from "@/components/papers/methods/method-detail-page"
import { MethodsPage } from "@/components/papers/methods/methods-page"
import { BenchmarkEvidencePanel } from "@/components/papers/shared/benchmark-evidence-panel"
import { TaskDetailPage } from "@/components/papers/tasks/task-detail-page"
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

const fallbackPaperResult: PaperListResult = {
  ...paperResult,
  papers: [
    {
      id: "paper-derived-agent",
      slug: "paper-derived-agent",
      title: "Derived Agent Paper",
      abstractSnippet: "A paper used to derive fallback taxonomy counts.",
      authors: ["A"],
      publishedAt: "2026-05-24T00:00:00Z",
      tags: ["agents"],
      taskRefs: [{ id: "task-agents", slug: "agents", name: "Agents" }],
      methodRefs: [{ id: "method-tool-use", slug: "tool-use", name: "Tool Use", area: "Agents" }],
      benchmarks: [
        {
          id: "benchmark-derived",
          name: "Derived Bench",
          category: "agents",
          metric: "score",
          value: "72"
        }
      ],
      repoUrl: "https://github.com/owner/derived-agent",
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
    taskRefs: [{ id: "task-coding", slug: "coding-agents", name: "Coding Agents" }],
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

const taskDetail = {
  id: "task-coding",
  slug: "coding-agents",
  name: "Coding Agents",
  group: "code-ai",
  description: "Agents that solve software engineering tasks.",
  paperCount: 1,
  benchmarkCount: 1,
  methodCount: 1,
  sisterTasks: [],
  commonMethods: []
}

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

  it("derives task fallback counts from the live paper list when task API fails", async () => {
    vi.mocked(fetchPaperTasksResult).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(fetchPapers).mockResolvedValueOnce(fallbackPaperResult)

    render(<TasksPage locale="en" />)

    expect(await screen.findByText("Paper task API is unavailable; showing taxonomy with real paper-derived counts.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Agents\s+1 Papers/i })).toBeInTheDocument()
  })

  it("keeps API-backed tasks visible when only paper totals fail", async () => {
    vi.mocked(fetchPaperTasksResult).mockResolvedValueOnce({ tasks: apiTasks, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPapers).mockRejectedValueOnce(new Error("paper list offline"))

    render(<TasksPage locale="en" />)

    expect(await screen.findByText("Backend Task")).toBeInTheDocument()
    expect(screen.getByText("Paper list API is unavailable; task taxonomy remains live, but paper totals are temporarily unavailable.")).toBeInTheDocument()
    expect(screen.queryByText("Paper task API is unavailable; showing taxonomy with real paper-derived counts.")).not.toBeInTheDocument()
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

  it("derives method fallback counts from the live paper list when method API fails", async () => {
    vi.mocked(fetchPaperMethodsResult).mockRejectedValueOnce(new Error("offline"))
    vi.mocked(fetchPaperTasksResult).mockResolvedValueOnce({ tasks: apiTasks, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPapers).mockResolvedValueOnce(fallbackPaperResult)

    render(<MethodsPage locale="en" />)

    expect(await screen.findByText("Paper method API is unavailable; showing taxonomy with real paper-derived counts.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Tool Use.*1 Papers.*1 Tasks/i })).toBeInTheDocument()
  })

  it("keeps API-backed methods visible when task taxonomy is temporarily unavailable", async () => {
    vi.mocked(fetchPaperMethodsResult).mockResolvedValueOnce({ methods: apiMethods, dataState: "ready", source: "backend", notices: [] })
    vi.mocked(fetchPaperTasksResult).mockRejectedValueOnce(new Error("tasks offline"))
    vi.mocked(fetchPapers).mockResolvedValueOnce(paperResult)

    render(<MethodsPage locale="en" />)

    expect(await screen.findByText("Backend Method")).toBeInTheDocument()
    expect(screen.getByText("Task taxonomy API is unavailable; method taxonomy remains live, but task totals are temporarily unavailable.")).toBeInTheDocument()
    expect(screen.queryByText("Paper method API is unavailable; showing taxonomy with real paper-derived counts.")).not.toBeInTheDocument()
  })

  it("opens benchmark evidence from method detail instead of placeholder copy", () => {
    render(<MethodDetailPage method={methodDetail} locale="en" papers={methodPapers} />)

    expect(screen.getByLabelText(/papers: 1/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/tasks: 1/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/implementations: 0/i)).toBeInTheDocument()
    expect(screen.queryByText("Related Tasks")).not.toBeInTheDocument()
    expect(screen.queryByText("Related Methods")).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /SWE-bench/ }))

    expect(screen.getByText("Benchmark Evidence")).toBeInTheDocument()
    expect(screen.getByText(/recorded benchmark fields/i)).toBeInTheDocument()
    expect(screen.getByText("resolved: 12.5%")).toBeInTheDocument()
    expect(screen.queryByText(/placeholder action/i)).not.toBeInTheDocument()
  })

  it("shows benchmark evidence entries from current matching papers", () => {
    render(
      <BenchmarkEvidencePanel
        benchmark={{
          id: "benchmark-swe-bench",
          slug: "swe-bench",
          name: "SWE-bench",
          category: "software-engineering",
          taskSlug: "coding-agents",
          entryCount: 99
        }}
        context={{ type: "method", method: methodDetail }}
        papers={methodPapers}
        locale="en"
        onClose={vi.fn()}
        onPreviewPaper={vi.fn()}
      />
    )

    expect(screen.getByText("Entries").nextElementSibling).toHaveTextContent("1")
    expect(screen.getByText("resolved: 12.5%")).toBeInTheDocument()
  })

  it("does not render empty method relation panels", () => {
    render(
      <MethodDetailPage
        method={{
          ...methodDetail,
          id: "method-empty",
          slug: "method-empty",
          name: "Empty Method",
          commonBenchmarks: [],
          relatedMethods: [],
          relatedTasks: []
        }}
        locale="en"
        papers={[]}
      />
    )

    expect(screen.queryByText("Related Tasks")).not.toBeInTheDocument()
    expect(screen.queryByText("Related Methods")).not.toBeInTheDocument()
    expect(screen.queryByText("Common Benchmarks")).not.toBeInTheDocument()
  })

  it("opens benchmark evidence from task detail instead of placeholder copy", () => {
    render(<TaskDetailPage task={taskDetail} locale="en" papers={methodPapers} />)

    fireEvent.click(screen.getByRole("button", { name: /SWE-bench/ }))

    expect(screen.getByText("Benchmark Evidence")).toBeInTheDocument()
    expect(screen.getByText(/recorded benchmark fields on papers in this task/i)).toBeInTheDocument()
    expect(screen.getByText("resolved: 12.5%")).toBeInTheDocument()
    expect(screen.queryByText(/placeholder action/i)).not.toBeInTheDocument()
  })

  it("derives task detail stats from visible papers instead of stale task totals", () => {
    render(
      <TaskDetailPage
        task={{
          ...taskDetail,
          id: "task-custom",
          slug: "custom-task",
          name: "Custom Task",
          benchmarkCount: 9,
          methodCount: 7
        }}
        locale="en"
        papers={[
          {
            ...methodPapers[0],
            id: "paper-custom",
            slug: "paper-custom",
            title: "Custom Paper",
            taskRefs: [{ id: "task-custom", slug: "custom-task", name: "Custom Task" }],
            methodRefs: [],
            benchmarks: []
          }
        ]}
      />
    )

    const hero = screen.getByRole("heading", { name: "Custom Task" }).closest("section")
    expect(hero).not.toBeNull()
    const stats = within(hero!)
      .getAllByText(/^\d+$/)
      .map((node) => node.textContent)
    expect(stats).toEqual(["1", "0", "0"])
    expect(screen.queryByText("Task Branches")).not.toBeInTheDocument()
  })
})
