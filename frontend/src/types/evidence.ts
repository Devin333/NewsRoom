import type { CredibilityLevel, SourceType } from "@/types/common"

export type EvidenceItem = {
  id: string
  title: string
  sourceName: string
  sourceType: SourceType
  sourceUrl?: string
  originalUrl?: string
  capturedAt: string
  summary?: string
  quote?: string
  credibility: CredibilityLevel
  confidenceScore?: number
  relationReason: string
}

export type Evidence = EvidenceItem

export type ClaimSupportStatus = "accepted" | "rejected" | "uncertain" | "unsupported"

export type StudioEvidenceDataState = "ready" | "partial" | "fallback"

export type StudioEvidenceSourceRef = {
  sourceId?: string
  title?: string
  url?: string
  publishedAt?: string
  reliability?: string
}

export type StudioEvidenceRef = {
  evidenceId?: string
  quote?: string
  summary?: string
}

export type StudioClaimEvidence = {
  claimId: string
  claimText: string
  status: ClaimSupportStatus
  confidence?: number
  sourceRefs: StudioEvidenceSourceRef[]
  evidenceRefs: StudioEvidenceRef[]
  reportSection?: string
  failureReason?: string
}

export type StudioEvidenceCounts = Record<ClaimSupportStatus, number> & {
  total: number
}

export type StudioCitationFailureCategory = {
  code: string
  count: number
  items: string[]
  label?: string
}

export type StudioLlmTrace = {
  selectedDeploymentId?: string
  fallbackUsed?: boolean
  fallbackCount?: number
  providerErrorCount?: number
  cooldownSkipCount?: number
  routerEventCount?: number
  budgetCheck?: unknown
  globalBudgetCheck?: unknown
  sanitized: Record<string, unknown>
}

export type StudioEvidenceRunSummary = {
  runId: string
  reportId?: string
  workflowName?: string
  status?: string
  startedAt?: string
  finishedAt?: string
  qualityScore?: number
  qualityDecision?: string
  qualityRoute?: string
  counts: StudioEvidenceCounts
  citationFailureCategories: StudioCitationFailureCategory[]
  unsupportedSections: string[]
  hasQualityTrace: boolean
  dataState: StudioEvidenceDataState
  notices: string[]
}

export type StudioEvidenceOverview = {
  runs: StudioEvidenceRunSummary[]
  totals: StudioEvidenceCounts
  citationFailureCategories: StudioCitationFailureCategory[]
  dataState: StudioEvidenceDataState
  notices: string[]
  generatedAt: string
}

export type StudioRunEvidenceDetail = StudioEvidenceRunSummary & {
  claims: StudioClaimEvidence[]
  qualityLineage?: Record<string, unknown>
  llmTrace?: StudioLlmTrace
  lineageRefs: Array<Record<string, unknown>>
}
