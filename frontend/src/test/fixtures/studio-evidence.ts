import type { StudioClaimEvidence, StudioRunEvidenceDetail } from "@/types/evidence"

export const unsupportedStudioClaimFixture: StudioClaimEvidence = {
  claimId: "claim-runtime-market-size",
  claimText: "Agent runtime observability is now the largest developer-tooling spend category.",
  status: "unsupported",
  confidence: 0.38,
  sourceRefs: [
    {
      sourceId: "source-community-pulse",
      title: "Community discussion about trace costs",
      url: "https://example.test/community/trace-costs",
      reliability: "medium"
    }
  ],
  evidenceRefs: [
    {
      evidenceId: "evidence-runtime-trace-001",
      summary: "Evidence supports rising interest in traces but not market-size leadership."
    }
  ],
  reportSection: "Market Signal",
  failureReason: "Missing primary source for market-size ranking."
}

export const studioEvidenceDetailFixture: StudioRunEvidenceDetail = {
  runId: "run-daily-20260522-0800",
  reportId: "report-daily-20260522",
  workflowName: "Daily NewsRoom Brief",
  status: "failed",
  startedAt: "2026-05-22T08:00:00.000Z",
  finishedAt: "2026-05-22T08:54:00.000Z",
  qualityScore: 72,
  qualityDecision: "review_required",
  counts: {
    accepted: 2,
    rejected: 1,
    uncertain: 1,
    unsupported: 1,
    total: 5
  },
  citationFailureCategories: [
    {
      code: "missing_primary_source",
      count: 1,
      items: ["claim-runtime-market-size"]
    }
  ],
  unsupportedSections: ["Market Signal"],
  hasQualityTrace: true,
  dataState: "fallback",
  notices: ["Evidence fixture uses fallback quality trace data."],
  claims: [unsupportedStudioClaimFixture],
  qualityLineage: {
    path: ["Source", "Evidence", "Claim", "Report Section", "Quality Decision"]
  },
  llmTrace: {
    fallbackUsed: false,
    fallbackCount: 0,
    providerErrorCount: 0,
    sanitized: {
      model: "redacted-test-model"
    }
  },
  lineageRefs: [{ source_type: "evidence", source_id: "evidence-runtime-trace-001" }]
}
