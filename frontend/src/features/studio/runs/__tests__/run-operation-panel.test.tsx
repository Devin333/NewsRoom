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

    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "stop it" } })
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/I confirm/))
    expect(screen.getByRole("button", { name: "Cancel run" })).not.toBeDisabled()
  })

  it("sends reason and selected step id for rerun operations", async () => {
    vi.mocked(postRunOperation).mockResolvedValue({ ok: true, message: "accepted" })
    render(<RunOperationPanel detail={detail()} selectedStep={step} />)

    fireEvent.click(screen.getByRole("button", { name: /Rerun from selected step/ }))
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "try again" } })
    fireEvent.click(screen.getByLabelText(/I confirm/))
    fireEvent.click(screen.getAllByRole("button", { name: "Rerun from selected step" }).at(-1)!)

    await waitFor(() => {
      expect(postRunOperation).toHaveBeenCalledWith("run-1", "rerun-from-step", expect.objectContaining({ reason: "try again", stepId: "collect" }))
    })
  })

  it("renders requestId when an operation fails", async () => {
    vi.mocked(postRunOperation).mockResolvedValue({ ok: false, message: "nope", requestId: "req-123" })
    render(<RunOperationPanel detail={detail()} selectedStep={step} />)

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "stop it" } })
    fireEvent.click(screen.getByLabelText(/I confirm/))
    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }))

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
