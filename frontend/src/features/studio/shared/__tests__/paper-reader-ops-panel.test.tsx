import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PaperReaderOpsPanel } from "@/features/studio/shared/components/paper-reader-ops-panel"
import {
  fetchPaperIngestOpsState,
  fetchPaperReaderOpsStats,
  refreshPaperReaderSummary,
  triggerPaperIngest,
  triggerPaperVisualCompileBackfill,
} from "@/features/studio/shared/api/paper-reader-ops-api"
import { useUiStore } from "@/stores/ui-store"
import type { PaperIngestOpsState, PaperReaderOpsStats } from "@/types/studio"

vi.mock("@/features/studio/shared/api/paper-reader-ops-api", () => ({
  fetchPaperIngestOpsState: vi.fn(),
  fetchPaperReaderOpsStats: vi.fn(),
  refreshPaperReaderSummary: vi.fn(),
  triggerPaperIngest: vi.fn(),
  triggerPaperVisualCompileBackfill: vi.fn()
}))

const readyStats: PaperReaderOpsStats = {
  dataState: "ready",
  windowHours: 24,
  windowStart: "2026-05-24T01:00:00.000Z",
  windowEnd: "2026-05-25T01:00:00.000Z",
  paperCache: {
    status: "ready",
    exists: true,
    paperCount: 12,
    source: "paper_radar",
    collectedAt: "2026-05-25T00:30:00.000Z",
    lastUpdatedAt: "2026-05-25T00:30:00.000Z"
  },
  summaryCache: {
    status: "ready",
    exists: true,
    entryCount: 8,
    v2EntryCount: 6,
    localeCounts: { en: 5, zh: 3 },
    modelRouteCounts: { "writer-primary": 8 },
    lastGeneratedAt: "2026-05-25T00:40:00.000Z",
    lastUpdatedAt: "2026-05-25T00:40:00.000Z"
  },
  summaryEvents: {
    status: "ready",
    exists: true,
    eventCount: 10,
    cacheHitCount: 6,
    generatedCount: 3,
    failureCount: 1,
    hitRate: 0.6667,
    outcomeCounts: { cache_hit: 6, generated: 3, failed: 1 },
    errorCodeCounts: { paper_summary_unavailable: 1 },
    localeCounts: { en: 10 },
    modelRouteCounts: { "writer-primary": 10 },
    recentFailures: [
      {
        timestamp: "2026-05-25T00:58:00.000Z",
        paperId: "paper-1",
        locale: "en",
        modelRoute: "writer-primary",
        errorCode: "paper_summary_unavailable",
        durationMs: 100
      }
    ],
    averageDurationMs: 42,
    lastUpdatedAt: "2026-05-25T00:58:00.000Z"
  },
  readerCache: {
    status: "ready",
    exists: true,
    fileCount: 4,
    lastUpdatedAt: "2026-05-25T00:45:00.000Z"
  },
  textExtraction: {
    status: "ready",
    exists: true,
    fileCount: 2,
    lastUpdatedAt: "2026-05-25T00:45:00.000Z"
  },
  lastUpdatedAt: "2026-05-25T00:58:00.000Z"
}

const readyIngest: PaperIngestOpsState = {
  runs: [
    {
      runId: "paper-run-1",
      status: "partial",
      startedAt: "2026-05-25T00:55:00.000Z",
      finishedAt: "2026-05-25T01:00:00.000Z",
      candidateLimit: 100,
      minGithubStars: 50,
      autoTaxonomyConfidence: 0.85,
      candidateCount: 2,
      processedCount: 2,
      publishedCount: 1,
      skippedNoGithubCount: 0,
      skippedLowStarsCount: 0,
      repairQueuedCount: 1,
      blockedCount: 0,
      failureCount: 1,
      publishedPaperIds: ["paper-1"]
    }
  ],
  repairQueue: [
    {
      itemId: "repair-1",
      runId: "paper-run-1",
      paperId: "paper-2",
      step: "classify",
      errorCode: "classifier_json_invalid",
      errorMessage: "bad json",
      status: "queued",
      queue: "agent_repair",
      repairAction: "inject_prompt_memory_and_reclassify",
      retryAt: "2026-05-25T01:30:00.000Z",
      createdAt: "2026-05-25T01:00:00.000Z",
      userActionRequired: false
    }
  ],
  blockedItems: [],
  taxonomyEvents: [
    {
      eventId: "tax-1",
      runId: "paper-run-1",
      paperId: "paper-1",
      kind: "task",
      slug: "agent-planning",
      name: "Agent Planning",
      confidence: 0.9,
      action: "auto_published",
      createdAt: "2026-05-25T01:00:00.000Z"
    }
  ],
  promptMemory: [],
  config: {
    candidateLimit: 100,
    minGithubStars: 50,
    autoTaxonomyConfidence: 0.85,
    arxivQuery: "cat:cs.AI",
    classifierModelRoute: "writer-primary"
  }
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false
      }
    }
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PaperReaderOpsPanel />
    </QueryClientProvider>
  )
}

describe("PaperReaderOpsPanel", () => {
  beforeEach(() => {
    vi.mocked(fetchPaperReaderOpsStats).mockReset()
    vi.mocked(fetchPaperIngestOpsState).mockReset()
    vi.mocked(refreshPaperReaderSummary).mockReset()
    vi.mocked(triggerPaperIngest).mockReset()
    vi.mocked(triggerPaperVisualCompileBackfill).mockReset()
    vi.mocked(fetchPaperIngestOpsState).mockResolvedValue(readyIngest)
    useUiStore.setState({ locale: "zh" })
  })

  it("renders loading state", () => {
    vi.mocked(fetchPaperReaderOpsStats).mockReturnValue(new Promise(() => undefined))

    renderPanel()

    expect(screen.getByText("正在加载论文缓存与摘要运行时统计。")).toBeInTheDocument()
  })

  it("renders error state", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockRejectedValue(new Error("ops down"))

    renderPanel()

    expect(await screen.findByText("Paper Reader 运维不可用")).toBeInTheDocument()
    expect(screen.getByText("ops down")).toBeInTheDocument()
  })

  it("renders empty state", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue({
      ...readyStats,
      dataState: "empty",
      paperCache: { ...readyStats.paperCache, paperCount: 0 },
      summaryEvents: { ...readyStats.summaryEvents, eventCount: 0, generatedCount: 0, cacheHitCount: 0, failureCount: 0 },
      readerCache: { ...readyStats.readerCache, fileCount: 0 },
      textExtraction: { ...readyStats.textExtraction, fileCount: 0 }
    })

    renderPanel()

    expect(await screen.findByText("暂无 Paper Reader 运行数据")).toBeInTheDocument()
  })

  it("renders ready stats and recent failures", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue(readyStats)

    renderPanel()

    expect(await screen.findByText("摘要命中率")).toBeInTheDocument()
    expect(screen.getByText("67%")).toBeInTheDocument()
    expect(screen.getByText("paper_summary_unavailable (1)")).toBeInTheDocument()
    expect(screen.getAllByText("paper_summary_unavailable").length).toBeGreaterThan(0)
    expect(screen.getByText("4")).toBeInTheDocument()
    expect(screen.getByText("2 个文本产物")).toBeInTheDocument()
  })

  it("renders paper ingest ops state", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue(readyStats)

    renderPanel()

    expect(await screen.findByText("论文入库自治")).toBeInTheDocument()
    expect(screen.getByText(/classifier_json_invalid/)).toBeInTheDocument()
    expect(screen.getByText("Agent 修复")).toBeInTheDocument()
  })

  it("triggers paper ingest from the ops panel", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue(readyStats)
    vi.mocked(triggerPaperIngest).mockResolvedValue({
      message_id: "1-0",
      task_id: "task-1",
      task_type: "papers.ingest_github_arxiv_daily",
      queue_name: "news:queue:papers",
      status: "queued"
    })

    renderPanel()

    const trigger = await screen.findByRole("button", { name: /触发入库/ })
    fireEvent.click(trigger)

    await waitFor(() => {
      expect(triggerPaperIngest).toHaveBeenCalledWith({})
    })
  })

  it("triggers reader compile backfill from the ops panel", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue(readyStats)
    vi.mocked(triggerPaperVisualCompileBackfill).mockResolvedValue({
      message_id: "2-0",
      task_id: "task-reader-backfill",
      task_type: "papers.visual_compile_backfill",
      queue_name: "news:queue:papers",
      status: "queued",
      limit: 10,
      force: true
    })

    renderPanel()

    expect(await screen.findByText("Reader 编译补齐")).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("数量上限"), { target: { value: "10" } })
    fireEvent.click(screen.getByLabelText("强制重编译"))
    fireEvent.click(screen.getByRole("button", { name: /补齐 Reader/ }))

    await waitFor(() => {
      expect(triggerPaperVisualCompileBackfill).toHaveBeenCalledWith({ limit: 10, force: true })
    })
  })

  it("requires a reason before refreshing summary", async () => {
    vi.mocked(fetchPaperReaderOpsStats).mockResolvedValue(readyStats)
    vi.mocked(refreshPaperReaderSummary).mockResolvedValue({
      paperId: "paper-1",
      locale: "en",
      modelRoute: "writer-primary",
      abstractHash: "hash",
      summary: "Updated",
      keyInsights: [],
      limitations: [],
      generatedAt: "2026-05-25T01:00:00.000Z",
      cached: false
    })

    renderPanel()

    const submit = await screen.findByRole("button", { name: /刷新/ })
    expect(submit).toBeDisabled()

    fireEvent.change(screen.getByLabelText("论文 ID 或 slug"), { target: { value: "paper-1" } })
    expect(submit).toBeDisabled()

    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "stale summary" } })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    await waitFor(() => {
      expect(refreshPaperReaderSummary).toHaveBeenCalledWith({
        paperId: "paper-1",
        locale: "en",
        reason: "stale summary"
      })
    })
  })
})
