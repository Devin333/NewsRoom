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
