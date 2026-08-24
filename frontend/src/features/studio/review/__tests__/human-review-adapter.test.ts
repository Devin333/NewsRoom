import { describe, expect, it } from "vitest"
import {
  mapBlockedRunToReviewItem,
  mapFallbackReportsToReviewItems,
  mapGraphWaitToReviewItem
} from "@/features/studio/review/lib/human-review-adapter"

describe("human-review-adapter", () => {
  it("maps a durable Graph approval Wait to a review item", () => {
    const item = mapGraphWaitToReviewItem({
      run_id: "run-1",
      node_instance_id: "node-approval",
      wait_id: "wait-1",
      kind: "approval",
      status: "registered",
      graph_id: "research",
      graph_version: "2.0.0",
      graph_ref: "research@2.0.0",
      graph_checksum: "sha256:graph",
      approval_id: "approval-1",
      registered_sequence: 12
    })

    expect(item).toMatchObject({
      approvalId: "approval-1",
      requestedAction: "graph_approval_decision",
      status: "pending",
      runId: "run-1",
      nodeInstanceId: "node-approval",
      waitId: "wait-1",
      graphRef: "research@2.0.0",
      graphChecksum: "sha256:graph",
      source: "graph_wait",
      actionKind: "approval_decision"
    })
    expect(item.actionDisabledReason).toBeUndefined()
  })

  it("disables a Graph approval decision when identity is incomplete", () => {
    const item = mapGraphWaitToReviewItem({
      run_id: "run-1",
      node_instance_id: "node-approval",
      wait_id: "wait-1",
      kind: "approval",
      status: "registered",
      approval_id: "approval-1"
    })

    expect(item.actionDisabledReason).toContain("identity is incomplete")
  })

  it("maps blocked runs as read-only inspection items", () => {
    const item = mapBlockedRunToReviewItem({
      run_id: "run-blocked",
      status: "waiting_for_human",
      profile: "daily",
      started_at: "2026-05-24T11:00:00Z",
      report_id: "report-blocked"
    })

    expect(item).toMatchObject({
      approvalId: "run:run-blocked:blocked",
      requestedAction: "graph_run_blocked",
      riskLevel: "high",
      actionKind: "none",
      runId: "run-blocked",
      reportId: "report-blocked"
    })
    expect(item.actionDisabledReason).toContain("no registered Graph Wait")
  })

  it("creates disabled fallback report items with Graph Wait notices", () => {
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
      "Graph Wait API offline"
    )

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      approvalId: "report:report-draft:review",
      actionKind: "none",
      actionDisabledReason: "Graph Wait data is unavailable; fallback report items cannot be approved here."
    })
    expect(items[0].notices[0]).toContain("Graph Wait API offline")
  })
})
