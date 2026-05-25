export type StudioApprovalAction = "approve" | "reject" | "modify"

export type StudioApprovalFixture = {
  approvalId: string
  requestedAction: string
  status: "pending" | "approved" | "rejected" | "modified" | "expired"
  riskLevel: "low" | "medium" | "high" | "critical"
  runId?: string
  reportId?: string
  requestedBy: string
  requestedAt: string
  reason: string
}

export const studioApprovalFixtures: StudioApprovalFixture[] = [
  {
    approvalId: "approval-report-daily-20260522",
    requestedAction: "publish_report",
    status: "pending",
    riskLevel: "high",
    runId: "run-daily-20260522-0800",
    reportId: "report-daily-20260522",
    requestedBy: "quality-gate",
    requestedAt: "2026-05-22T09:05:00.000Z",
    reason: "Quality gate failed citation coverage and requires a human decision."
  },
  {
    approvalId: "approval-blocked-run-20260522",
    requestedAction: "mark_blocked_resolved",
    status: "pending",
    riskLevel: "medium",
    runId: "run-report-20260522-0715",
    requestedBy: "run-center",
    requestedAt: "2026-05-22T09:10:00.000Z",
    reason: "Operator needs to resolve a waiting_for_human run."
  }
]

export const requiredReviewDecisionFields = {
  approve: ["decided_by"],
  reject: ["decided_by", "reason"],
  modify: ["decided_by", "modifications"]
} satisfies Record<StudioApprovalAction, string[]>
