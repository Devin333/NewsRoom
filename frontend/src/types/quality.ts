export type QualityGateStatus = "passed" | "review" | "failed"

export type QualityGateSummary = {
  status: QualityGateStatus
  passedChecks: number
  totalChecks: number
  summary: string
}

export type QualityResultStatus = "passed" | "warning" | "failed" | "review_required"

export type QualityCheck = {
  id: string
  name:
    | "sourceCoverage"
    | "factConsistency"
    | "duplicateRisk"
    | "summaryCompleteness"
    | "titleQuality"
    | "evidenceCompleteness"
    | "citationQuality"
    | "humanReviewRequired"
  status: "passed" | "warning" | "failed"
  score?: number
  message?: string
}

export type QualityResult = {
  id: string
  objectType: "news" | "topic" | "report" | "run"
  objectId: string
  objectTitle: string
  score: number
  status: QualityResultStatus
  issueCount: number
  checks: QualityCheck[]
  createdAt: string
  reviewerDecision?: "approved" | "rejected" | "needs_changes" | "pending"
}

export type QualityFilters = {
  keyword: string
  objectType: "all" | QualityResult["objectType"]
  status: "all" | QualityResultStatus
  minScore: number
  review: "all" | "pending" | "decided"
}

export type StudioQualityStatus =
  | "passed"
  | "warning"
  | "failed"
  | "review_required"
  | "unknown"

export type StudioQualityDataState = "ready" | "partial" | "fallback"

export type StudioQualityCheck = {
  id: string
  name: string
  status: StudioQualityStatus
  score?: number
  message?: string
  details?: Record<string, unknown>
  userActionRequired?: boolean
}

export type StudioQualityReportSummary = {
  reportId: string
  runId?: string
  title: string
  status: StudioQualityStatus
  reportStatus?: string
  qualityScore?: number
  generatedAt?: string
  workflowId?: string
  artifactPath?: string
  issueCount: number
  failureReasons: string[]
}

export type StudioBlockedRun = {
  runId: string
  status: StudioQualityStatus
  severity?: string
  summary: string
  latestEventCount?: number
  requestId?: string
}

export type StudioQualityMetrics = {
  citationCoverage?: number
  sourceFreshness?: number
  duplicateRate?: number
  unsupportedClaims: number
}

export type StudioQualityDashboard = {
  dataState: StudioQualityDataState
  notices: string[]
  requestId?: string
  counts: Record<StudioQualityStatus, number>
  metrics: StudioQualityMetrics
  recentFailedReports: StudioQualityReportSummary[]
  recentBlockedRuns: StudioBlockedRun[]
  reports: StudioQualityReportSummary[]
  catalogHealth?: Record<string, unknown>
}

export type StudioQualityDetail = {
  dataState: StudioQualityDataState
  notices: string[]
  requestId?: string
  report: StudioQualityReportSummary
  checks: StudioQualityCheck[]
  failureReasons: string[]
  metrics: StudioQualityMetrics
  run?: {
    runId: string
    health?: Record<string, unknown>
    diagnostics?: Record<string, unknown>
  }
  artifactRefs: Array<{
    label: string
    value: string
  }>
  rawQuality?: Record<string, unknown>
}

export type StudioRequestReviewPayload = {
  reason: string
  requested_by?: string
  metadata: {
    source: "studio_quality_gate"
  }
}

export type StudioRequestReviewResult =
  | {
      ok: true
      approvalId?: string
      message: string
      requestId?: string
    }
  | {
      ok: false
      errorMessage: string
      requestId?: string
    }

export type StudioRequestReviewAction = (
  reportId: string,
  payload: StudioRequestReviewPayload
) => Promise<StudioRequestReviewResult>
