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
  approvalId: "appr_test",
  requestedAction: "publish_report",
  status: "pending",
  riskLevel: "high",
  reportId: "report-1",
  payloadPreview: { report_id: "report-1" },
  notices: [],
  actionKind: "approval_decision"
}

describe("ReviewDecisionPanel", () => {
  it("submits approve payload with decided_by after confirmation", async () => {
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

    fireEvent.change(screen.getByLabelText("decided_by"), { target: { value: "reviewer-1" } })
    fireEvent.click(screen.getByRole("button", { name: "通过" }))
    fireEvent.click(screen.getByRole("button", { name: /确认通过/ }))

    await waitFor(() => expect(submitted).toHaveLength(1))
    expect(submitted[0]).toMatchObject({
      action: "approve",
      decidedBy: "reviewer-1"
    })
  })

  it("requires decided_by for reject", async () => {
    const submit = vi.fn()
    render(<ReviewDecisionPanel item={pendingItem} onSubmitAction={submit} />)

    fireEvent.click(screen.getByRole("button", { name: "驳回" }))

    expect(await screen.findByText("必须填写 decided_by。")).toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })

  it("requires non-empty modifications for modify", async () => {
    const submit = vi.fn()
    render(<ReviewDecisionPanel item={pendingItem} onSubmitAction={submit} />)

    fireEvent.change(screen.getByLabelText("decided_by"), { target: { value: "reviewer-2" } })
    fireEvent.change(screen.getByLabelText("modifications JSON"), { target: { value: "{}" } })
    fireEvent.click(screen.getByRole("button", { name: "修改" }))

    expect(await screen.findByText("修改决策必须提供 modifications。")).toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })

  it("disables approval actions for fallback items", () => {
    render(
      <ReviewDecisionPanel
        item={{
          ...pendingItem,
          approvalId: "report:report-1:review",
          actionKind: "none",
          actionDisabledReason: "Approvals API is unavailable; fallback report items cannot be approved here."
        }}
        onSubmitAction={vi.fn()}
      />
    )

    expect(screen.getByRole("button", { name: "通过" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "驳回" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "修改" })).toBeDisabled()
    expect(screen.getByText("Approvals API is unavailable; fallback report items cannot be approved here.")).toBeInTheDocument()
  })
})
