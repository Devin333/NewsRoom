import { describe, expect, it } from "vitest"
import {
  mapApprovalToReviewItem,
  mapBlockedRunToReviewItem,
  mapFallbackReportsToReviewItems
} from "@/features/studio/review/lib/human-review-adapter"

describe("human-review-adapter", () => {
  it("maps approval responses to review queue items", () => {
    const item = mapApprovalToReviewItem({
      approval_id: "appr_123",
      requested_action: "publish_report",
      status: "pending",
      risk_level: "critical",
      reason: "External publishing",
      payload: { report_id: "report-1" },
      run_id: "run-1",
      requested_by: "scheduler",
      created_at: "2026-05-24T12:00:00Z",
      expires_at: "2026-05-25T12:00:00Z"
    })

    expect(item).toMatchObject({
      approvalId: "appr_123",
      requestedAction: "publish_report",
      status: "pending",
      riskLevel: "critical",
      reportId: "report-1",
      runId: "run-1",
      actionKind: "approval_decision"
    })
    expect(item.history?.[0]).toMatchObject({ type: "requested", actor: "scheduler" })
  })

  it("maps payload report_id to reportId", () => {
    const item = mapApprovalToReviewItem({
      approval_id: "appr_456",
      requested_action: "review_report",
      status: "pending",
      payload: { report_id: "report-from-payload" },
      metadata: { report_id: "report-from-metadata" }
    })

    expect(item.reportId).toBe("report-from-payload")
  })

  it("maps blocked run to a high-risk resolvable item", () => {
    const item = mapBlockedRunToReviewItem({
      run_id: "run-blocked",
      status: "waiting_for_human",
      workflow_id: "daily",
      started_at: "2026-05-24T11:00:00Z",
      report_id: "report-blocked"
    })

    expect(item).toMatchObject({
      approvalId: "run:run-blocked:blocked",
      requestedAction: "resolve_blocked_run",
      riskLevel: "high",
      actionKind: "resolve_blocked_run",
      runId: "run-blocked",
      reportId: "report-blocked"
    })
  })

  it("creates disabled fallback report items with notices", () => {
    const items = mapFallbackReportsToReviewItems(
      [
        {
          report_id: "report-draft",
          run_id: "run-draft",
          status: "draft",
          title: "Draft report",
          created_at: "2026-05-24T10:00:00Z"
        },
        {
          report_id: "report-published",
          run_id: "run-published",
          status: "published"
        }
      ],
      "approvals offline"
    )

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      approvalId: "report:report-draft:review",
      actionKind: "none",
      actionDisabledReason: "Approvals API is unavailable; fallback report items cannot be approved here."
    })
    expect(items[0].notices[0]).toContain("approvals offline")
  })
})
