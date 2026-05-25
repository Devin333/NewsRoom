export type ReviewRiskLevel = "low" | "medium" | "high" | "critical"

export type ReviewStatus = "pending" | "approved" | "rejected" | "modified" | "expired"

export type ReviewSource = "approval" | "run" | "report" | "fallback"

export type ReviewActionKind = "approval_decision" | "resolve_blocked_run" | "none"

export type ReviewHistoryEvent = {
  id: string
  type: string
  actor?: string
  at?: string
  reason?: string
  status?: string
  modifications?: Record<string, unknown>
}

export type StudioReviewItem = {
  approvalId: string
  requestedAction: string
  status: ReviewStatus
  riskLevel: ReviewRiskLevel
  reason?: string
  runId?: string
  reportId?: string
  requestedBy?: string
  requestedAt?: string
  expiresAt?: string
  payloadPreview?: Record<string, unknown>
  notices: string[]
  rawStatus?: string
  source?: ReviewSource
  actionKind?: ReviewActionKind
  history?: ReviewHistoryEvent[]
  requestId?: string
  actionDisabledReason?: string
}

export type StudioReviewQueue = {
  items: StudioReviewItem[]
  notices: string[]
  dataState: "ready" | "partial" | "fallback"
}

export type StudioReviewDetail = {
  item: StudioReviewItem
  notices: string[]
  dataState: "ready" | "partial" | "fallback"
}

export type ReviewDecisionAction = "approve" | "reject" | "modify" | "resolve_blocked_run"

export type ReviewActionRequest = {
  item: StudioReviewItem
  action: ReviewDecisionAction
  decidedBy: string
  reason?: string
  modifications?: Record<string, unknown>
}

export type ReviewActionResult =
  | { ok: true; requestId?: string; data?: unknown }
  | { ok: false; errorCode: string; errorMessage: string; requestId?: string }
