import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ReviewDecisionPanel } from "@/features/studio/review/components/review-decision-panel"
import type { ReviewActionRequest, StudioReviewItem } from "@/types/review"

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn()
  })
}))

const pendingItem: StudioReviewItem = {
  approvalId: "approval-test",
  requestedAction: "graph_approval_decision",
  status: "pending",
  riskLevel: "high",
  runId: "run-1",
  nodeInstanceId: "node-approval",
  graphChecksum: "sha256:graph",
  notices: [],
  actionKind: "approval_decision"
}

describe("ReviewDecisionPanel", () => {
  it("submits an approval decision without caller-supplied actor or patch fields", async () => {
    const submitted: ReviewActionRequest[] = []
    render(
      <ReviewDecisionPanel
        item={pendingItem}
        onSubmitAction={async (request) => {
          submitted.push(request)
          return { ok: true }
        }}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: /通过|Approve/ }))
    fireEvent.click(screen.getByRole("button", { name: /确认.*通过|Confirm.*approve/i }))

    await waitFor(() => expect(submitted).toHaveLength(1))
    expect(submitted[0]).toEqual({ item: pendingItem, action: "approve" })
  })

  it("does not expose a modify action or actor input", () => {
    render(<ReviewDecisionPanel item={pendingItem} onSubmitAction={vi.fn()} />)

    expect(screen.queryByLabelText("decided_by")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /修改|Modify/ })).not.toBeInTheDocument()
  })

  it("disables approval actions for fallback items", () => {
    render(
      <ReviewDecisionPanel
        item={{
          ...pendingItem,
          approvalId: "report:report-1:review",
          actionKind: "none",
          actionDisabledReason: "Graph Wait data is unavailable; fallback report items cannot be approved here."
        }}
        onSubmitAction={vi.fn()}
      />
    )

    expect(screen.queryByRole("button", { name: /通过|Approve/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /驳回|Reject/ })).not.toBeInTheDocument()
    expect(screen.getByText("Graph Wait data is unavailable; fallback report items cannot be approved here.")).toBeInTheDocument()
  })
})
