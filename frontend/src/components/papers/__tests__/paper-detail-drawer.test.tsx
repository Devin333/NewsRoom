import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperDetailDrawer } from "@/components/papers/shared/paper-detail-drawer"
import { fetchPaperDetail, requestPaperSummary } from "@/lib/papers/api"
import type { Paper } from "@/lib/papers/types"
import { useUiStore } from "@/stores/ui-store"

vi.mock("@/lib/papers/api", () => ({
  fetchPaperDetail: vi.fn(),
  requestPaperSummary: vi.fn()
}))

const paper: Paper = {
  id: "paper-segment-anything",
  slug: "segment-anything",
  title: "Segment Anything",
  abstractSnippet: "We introduce the Segment Anything project: a new task, model, and dataset for image segmentation.",
  authors: ["Alexander Kirillov", "Eric Mintun"],
  publishedAt: "2023-10-01",
  venue: "ICCV",
  citationCount: 8800,
  tags: ["segmentation"],
  taskRefs: [{ id: "task-vqa", slug: "visual-question-answering", name: "Visual QA", group: "multimodal" }],
  methodRefs: [{ id: "method-tool-use", slug: "tool-use", name: "Tool Use", area: "Prompt Engineering" }],
  githubStars: 54200,
  arxivUrl: "https://arxiv.org/abs/2304.02643",
  pdfUrl: "https://arxiv.org/pdf/2304.02643.pdf",
  repoUrl: "https://github.com/facebookresearch/segment-anything",
  paperUrl: "https://openaccess.thecvf.com/content/ICCV2023/html/Kirillov_Segment_Anything_ICCV_2023_paper.html",
  implementations: [
    {
      id: "primary-repository",
      name: "facebookresearch/segment-anything",
      repoUrl: "https://github.com/facebookresearch/segment-anything",
      githubStars: 54200
    }
  ],
  benchmarks: [],
  isPublished: true
}

describe("PaperDetailDrawer", () => {
  beforeEach(() => {
    useUiStore.setState({ locale: "en" })
    vi.mocked(fetchPaperDetail).mockReset()
    vi.mocked(requestPaperSummary).mockReset()
    vi.mocked(requestPaperSummary).mockResolvedValue({
      paperId: paper.id,
      locale: "en",
      modelRoute: "writer-primary",
      abstractHash: "abc",
      summary: "Segment Anything introduces a promptable segmentation foundation model.",
      keyInsights: ["Promptable segmentation"],
      limitations: [],
      generatedAt: "2026-05-24T00:00:00Z",
      cached: false
    })
  })

  it("renders paper detail sections and real actions", () => {
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(screen.getByRole("dialog", { name: /paper detail/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Segment Anything" })).toBeInTheDocument()
    expect(screen.getByText("NewsRoom AI")).toBeInTheDocument()
    expect(screen.getByText("Abstract")).toBeInTheDocument()
    expect(screen.getByText("Tasks")).toBeInTheDocument()
    expect(screen.getByText("Methods")).toBeInTheDocument()
    expect(screen.getByText("Benchmarks / SOTA")).toBeInTheDocument()
    expect(screen.getByText("No real benchmark fields are recorded yet.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Visual QA" })).toHaveAttribute("href", "/papers/tasks/visual-question-answering")
    expect(screen.getByRole("link", { name: "Tool Use" })).toHaveAttribute("href", "/papers/methods/tool-use")
    expect(
      screen.getByText("Tasks").compareDocumentPosition(screen.getByText("Benchmarks / SOTA")) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    expect(screen.getByRole("link", { name: /view pdf/i })).toHaveAttribute("href", "https://arxiv.org/pdf/2304.02643.pdf")
    expect(screen.getByRole("link", { name: /code/i })).toHaveAttribute("href", "https://github.com/facebookresearch/segment-anything")
    expect(screen.getByRole("link", { name: /open reader/i })).toHaveAttribute("href", "/papers/segment-anything/read")
  })

  it("uses encoded Research routes for reader and taxonomy links", () => {
    render(
      <PaperDetailDrawer
        paper={{
          ...paper,
          slug: "segment anything/v2",
          taskRefs: [{ id: "task-special", slug: "visual qa/v2", name: "Visual QA v2", group: "multimodal" }],
          methodRefs: [{ id: "method-special", slug: "tool use/v2", name: "Tool Use v2", area: "Agents" }]
        }}
        locale="en"
        open
        onOpenChange={vi.fn()}
      />
    )

    expect(screen.getByRole("link", { name: /open reader/i })).toHaveAttribute("href", "/papers/segment%20anything%2Fv2/read")
    expect(screen.getByRole("link", { name: "Visual QA v2" })).toHaveAttribute("href", "/papers/tasks/visual%20qa%2Fv2")
    expect(screen.getByRole("link", { name: "Tool Use v2" })).toHaveAttribute("href", "/papers/methods/tool%20use%2Fv2")
  })

  it("notifies when dismissed", () => {
    const onOpenChange = vi.fn()
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={onOpenChange} />)

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("loads a deep-linked paper detail by id", async () => {
    vi.mocked(fetchPaperDetail).mockResolvedValue(paper)
    render(<PaperDetailDrawer paper={null} paperId="paper-segment-anything" locale="en" open onOpenChange={vi.fn()} />)

    expect(await screen.findByRole("heading", { name: "Segment Anything" })).toBeInTheDocument()
    expect(fetchPaperDetail).toHaveBeenCalledWith("paper-segment-anything")
  })

  it("keeps the deep-linked drawer open while paper detail is loading", () => {
    vi.mocked(fetchPaperDetail).mockReturnValue(new Promise(() => undefined))

    render(<PaperDetailDrawer paper={null} paperId="paper-segment-anything" locale="en" open onOpenChange={vi.fn()} />)

    expect(screen.getByRole("dialog", { name: /paper detail/i })).toBeInTheDocument()
    expect(screen.getByText("Loading...")).toBeInTheDocument()
    expect(requestPaperSummary).not.toHaveBeenCalled()
  })

  it("shows deep-linked paper detail failures inside a dismissible drawer", async () => {
    const onOpenChange = vi.fn()
    vi.mocked(fetchPaperDetail).mockRejectedValue(new Error("paper detail unavailable"))

    render(<PaperDetailDrawer paper={null} paperId="paper-segment-anything" locale="en" open onOpenChange={onOpenChange} />)

    expect(await screen.findByRole("alert")).toHaveTextContent("Paper detail is temporarily unavailable.")
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("does not expose unpublished paper details returned by a deep link", async () => {
    vi.mocked(fetchPaperDetail).mockResolvedValue({ ...paper, id: "paper-draft", slug: "paper-draft", title: "Draft Paper", isPublished: false })

    render(<PaperDetailDrawer paper={null} paperId="paper-draft" locale="en" open onOpenChange={vi.fn()} />)

    expect(await screen.findByRole("alert")).toHaveTextContent("Paper detail is temporarily unavailable.")
    expect(screen.queryByText("Draft Paper")).not.toBeInTheDocument()
    expect(requestPaperSummary).not.toHaveBeenCalled()
  })

  it("renders summary loading and success states", async () => {
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(screen.getByText("Generating NewsRoom AI summary...")).toBeInTheDocument()
    expect(await screen.findByText("Segment Anything introduces a promptable segmentation foundation model.")).toBeInTheDocument()
  })

  it("renders compact v2 contributions in the AI summary block", async () => {
    vi.mocked(requestPaperSummary).mockResolvedValue({
      paperId: paper.id,
      locale: "en",
      modelRoute: "writer-primary",
      abstractHash: "abc",
      summary: "Segment Anything introduces promptable segmentation.",
      keyInsights: ["Promptable segmentation"],
      limitations: [],
      contributions: ["Introduces a promptable segmentation task."],
      generatedAt: "2026-05-24T00:00:00Z",
      cached: false,
      summarySchemaVersion: "v2"
    })

    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(await screen.findByText("Introduces a promptable segmentation task.")).toBeInTheDocument()
    expect(screen.getByText("Contributions")).toBeInTheDocument()
  })

  it("shows paper user state badges when present", () => {
    render(
      <PaperDetailDrawer
        paper={{
          ...paper,
          userState: {
            userId: "user-1",
            paperId: paper.id,
            favorite: true,
            subscribed: true,
            readingStatus: "reading",
            progressPercent: 20,
            updatedAt: "2026-05-24T00:00:00Z"
          }
        }}
        locale="en"
        open
        onOpenChange={vi.fn()}
      />
    )

    expect(screen.getByText("Favorite")).toBeInTheDocument()
    expect(screen.getByText("Subscribed")).toBeInTheDocument()
  })

  it("shows benchmark category badges when benchmark results are available", () => {
    render(
      <PaperDetailDrawer
        paper={{
          ...paper,
          benchmarks: [
            {
              id: "bench-vqa",
              name: "VQA v2",
              category: "visual-question-answering",
              metric: "accuracy",
              value: "86.4"
            }
          ]
        }}
        locale="en"
        open
        onOpenChange={vi.fn()}
      />
    )

    expect(screen.getByText("VQA v2")).toBeInTheDocument()
    expect(screen.getAllByText("Visual QA").length).toBeGreaterThan(0)
    expect(screen.queryByRole("link", { name: /VQA v2/ })).not.toBeInTheDocument()
  })

  it("links benchmark results only when a real source URL is recorded", () => {
    render(
      <PaperDetailDrawer
        paper={{
          ...paper,
          benchmarks: [
            {
              id: "bench-vqa",
              name: "VQA v2",
              category: "visual-question-answering",
              metric: "accuracy",
              value: "86.4",
              url: "https://paperswithcode.com/sota/visual-question-answering-on-vqa-v2-test-dev"
            }
          ]
        }}
        locale="en"
        open
        onOpenChange={vi.fn()}
      />
    )

    expect(screen.getByRole("link", { name: /VQA v2/ })).toHaveAttribute(
      "href",
      "https://paperswithcode.com/sota/visual-question-answering-on-vqa-v2-test-dev"
    )
  })

  it("renders retryable summary error state", async () => {
    vi.mocked(requestPaperSummary).mockRejectedValue(new Error("provider unavailable"))
    render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(await screen.findByText("AI summary is temporarily unavailable. You can keep reading the original abstract.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument()
  })

  it("clears stale summary errors when switching to another paper", async () => {
    vi.mocked(requestPaperSummary)
      .mockRejectedValueOnce(new Error("provider unavailable"))
      .mockReturnValue(new Promise(() => undefined))
    const { rerender } = render(<PaperDetailDrawer paper={paper} locale="en" open onOpenChange={vi.fn()} />)

    expect(await screen.findByText("AI summary is temporarily unavailable. You can keep reading the original abstract.")).toBeInTheDocument()

    rerender(
      <PaperDetailDrawer
        paper={{
          ...paper,
          id: "paper-other",
          slug: "other-paper",
          title: "Other Paper",
          aiSummary: undefined
        }}
        locale="en"
        open
        onOpenChange={vi.fn()}
      />
    )

    await waitFor(() => expect(screen.queryByText("AI summary is temporarily unavailable. You can keep reading the original abstract.")).not.toBeInTheDocument())
    expect(screen.getByText("Generating NewsRoom AI summary...")).toBeInTheDocument()
  })
})
