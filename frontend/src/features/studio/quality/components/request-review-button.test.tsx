import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { RequestReviewButton } from "@/features/studio/quality/components/request-review-button"
import type { StudioRequestReviewAction } from "@/types/quality"

describe("RequestReviewButton", () => {
  it("requires a reason before submitting", async () => {
    const action = vi.fn<StudioRequestReviewAction>()
    render(<RequestReviewButton reportId="report-1" dataState="ready" requestReviewAction={action} />)

    fireEvent.click(screen.getByRole("button", { name: /request review/i }))
    fireEvent.click(screen.getByRole("button", { name: /submit/i }))

    expect(await screen.findByText("Reason is required.")).toBeInTheDocument()
    expect(action).not.toHaveBeenCalled()
  })

  it("submits the expected request review payload", async () => {
    const action = vi.fn<StudioRequestReviewAction>().mockResolvedValue({
      ok: true,
      approvalId: "approval-1",
      message: "report review requested"
    })
    render(<RequestReviewButton reportId="report-1" dataState="ready" requestReviewAction={action} />)

    fireEvent.click(screen.getByRole("button", { name: /request review/i }))
    fireEvent.change(screen.getByPlaceholderText("Explain why this report needs human review."), {
      target: { value: "Citation gap needs editor review" }
    })
    fireEvent.change(screen.getByPlaceholderText("operator@example.com"), {
      target: { value: "operator@example.com" }
    })
    fireEvent.click(screen.getByRole("button", { name: /submit/i }))

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1))
    expect(action).toHaveBeenCalledWith("report-1", {
      reason: "Citation gap needs editor review",
      requested_by: "operator@example.com",
      metadata: { source: "studio_quality_gate" }
    })
  })

  it("renders approval id on success", async () => {
    const action = vi.fn<StudioRequestReviewAction>().mockResolvedValue({
      ok: true,
      approvalId: "approval-123",
      message: "report review requested",
      requestId: "req-1"
    })
    render(<RequestReviewButton reportId="report-1" dataState="ready" requestReviewAction={action} />)

    fireEvent.click(screen.getByRole("button", { name: /request review/i }))
    fireEvent.change(screen.getByPlaceholderText("Explain why this report needs human review."), {
      target: { value: "Needs review" }
    })
    fireEvent.click(screen.getByRole("button", { name: /submit/i }))

    expect(await screen.findByText("Approval: approval-123")).toBeInTheDocument()
    expect(screen.getByText("RequestId: req-1")).toBeInTheDocument()
  })

  it("renders request id on failure", async () => {
    const action = vi.fn<StudioRequestReviewAction>().mockResolvedValue({
      ok: false,
      errorMessage: "API failed",
      requestId: "req-error"
    })
    render(<RequestReviewButton reportId="report-1" dataState="ready" requestReviewAction={action} />)

    fireEvent.click(screen.getByRole("button", { name: /request review/i }))
    fireEvent.change(screen.getByPlaceholderText("Explain why this report needs human review."), {
      target: { value: "Needs review" }
    })
    fireEvent.click(screen.getByRole("button", { name: /submit/i }))

    expect(await screen.findByText("API failed")).toBeInTheDocument()
    expect(screen.getByText("RequestId: req-error")).toBeInTheDocument()
  })

  it("disables request review in fallback mode", () => {
    const action = vi.fn<StudioRequestReviewAction>()
    render(<RequestReviewButton reportId="report-1" dataState="fallback" requestReviewAction={action} />)

    expect(screen.getByRole("button", { name: /request review/i })).toBeDisabled()
  })
})
