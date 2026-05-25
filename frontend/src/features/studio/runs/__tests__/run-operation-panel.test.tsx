import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { RunOperationPanel } from "@/features/studio/runs/components/run-operation-panel"
import { postRunOperation } from "@/features/studio/runs/api/run-center-operations-api"
import type { AgentStep, StudioRunDetail } from "@/types/agent"

vi.mock("@/features/studio/runs/api/run-center-operations-api", () => ({
  postRunOperation: vi.fn()
}))

const step: AgentStep = {
  id: "collect",
  runId: "run-1",
  nodeId: "node-collect",
  label: "Collect",
  type: "collect",
  status: "failed"
}

describe("RunOperationPanel", () => {
  beforeEach(() => {
    vi.mocked(postRunOperation).mockReset()
  })

  it("requires reason and confirmation before submitting", () => {
    render(<RunOperationPanel detail={detail()} selectedStep={step} />)

    expect(screen.getByRole("button", { name: "取消运行" })).toBeDisabled()
    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "stop it" } })
    expect(screen.getByRole("button", { name: "取消运行" })).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/我确认/))
    expect(screen.getByRole("button", { name: "取消运行" })).not.toBeDisabled()
  })

  it("sends reason and selected step id for rerun operations", async () => {
    vi.mocked(postRunOperation).mockResolvedValue({ ok: true, message: "accepted" })
    render(<RunOperationPanel detail={detail()} selectedStep={step} />)

    fireEvent.click(screen.getByRole("button", { name: /从选中步骤重跑/ }))
    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "try again" } })
    fireEvent.click(screen.getByLabelText(/我确认/))
    fireEvent.click(screen.getAllByRole("button", { name: "从选中步骤重跑" }).at(-1)!)

    await waitFor(() => {
      expect(postRunOperation).toHaveBeenCalledWith("run-1", "rerun-from-step", expect.objectContaining({ reason: "try again", stepId: "collect" }))
    })
  })

  it("renders requestId when an operation fails", async () => {
    vi.mocked(postRunOperation).mockResolvedValue({ ok: false, message: "nope", requestId: "req-123" })
    render(<RunOperationPanel detail={detail()} selectedStep={step} />)

    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "stop it" } })
    fireEvent.click(screen.getByLabelText(/我确认/))
    fireEvent.click(screen.getByRole("button", { name: "取消运行" }))

    expect(await screen.findByText("requestId: req-123")).toBeInTheDocument()
  })
})

function detail(): StudioRunDetail {
  return {
    run: {
      id: "run-1",
      agentName: "daily",
      workflowId: "daily",
      profile: "live",
      status: "running",
      startedAt: "2026-05-24T01:00:00Z",
      durationSeconds: 60,
      inputCount: 0,
      outputCount: 0,
      artifactCount: 0,
      errorCount: 0,
      dataState: "ready",
      notices: []
    },
    steps: [step],
    dag: { nodes: [], edges: [] },
    logs: [],
    events: [],
    toolCalls: [],
    memoryHits: [],
    artifacts: [],
    errors: [],
    operations: { canCancel: true, canRerunFromStep: true, canSkipStep: true, canResolveBlocked: false },
    dataState: "ready",
    notices: []
  }
}
