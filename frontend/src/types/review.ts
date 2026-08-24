export type ReviewRiskLevel = "low" | "medium" | "high" | "critical"

export type ReviewStatus = "pending" | "approved" | "rejected" | "expired"

export type ReviewSource = "graph_wait" | "run" | "report" | "fallback"

export type ReviewActionKind = "approval_decision" | "none"

export type ReviewHistoryEvent = {
  id: string
  type: string
  actor?: string
  at?: string
  reason?: string
  status?: string
}

export type StudioReviewItem = {
  approvalId: string
  requestedAction: string
  status: ReviewStatus
  riskLevel: ReviewRiskLevel
  reason?: string
  runId?: string
  nodeInstanceId?: string
  waitId?: string
  graphId?: string
  graphVersion?: string
  graphRef?: string
  graphChecksum?: string
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

export type ReviewDecisionAction = "approve" | "reject"

export type ReviewActionRequest = {
  item: StudioReviewItem
  action: ReviewDecisionAction
}

export type ReviewActionResult =
  | { ok: true; requestId?: string; data?: unknown }
  | { ok: false; errorCode: string; errorMessage: string; requestId?: string }
