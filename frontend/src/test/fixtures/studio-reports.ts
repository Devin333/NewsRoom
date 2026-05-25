import type { Report } from "@/types/report"

export const studioReportFixtures: Report[] = [
  {
    id: "report-daily-20260522",
    title: "Daily AI Runtime Brief",
    type: "daily",
    generatedAt: "2026-05-22T09:00:00.000Z",
    agentName: "DailyNewsAgent",
    qualityScore: 72,
    topicIds: ["agent-runtime-observability"],
    evidenceIds: ["evidence-runtime-trace-001"],
    status: "draft"
  },
  {
    id: "report-daily-20260521",
    title: "Daily AI Runtime Brief",
    type: "daily",
    generatedAt: "2026-05-21T09:00:00.000Z",
    agentName: "DailyNewsAgent",
    qualityScore: 89,
    topicIds: ["agent-runtime-observability"],
    evidenceIds: ["evidence-runtime-trace-001", "evidence-quality-gate-002"],
    status: "published"
  }
]

export const studioReportQualityFixture = {
  reportId: "report-daily-20260522",
  status: "failed",
  score: 72,
  checks: [
    {
      id: "citation-coverage",
      name: "citationQuality",
      status: "failed",
      score: 58,
      message: "One high-impact claim does not have enough source support."
    },
    {
      id: "source-freshness",
      name: "sourceCoverage",
      status: "passed",
      score: 92,
      message: "Primary sources are inside the freshness window."
    },
    {
      id: "human-review",
      name: "humanReviewRequired",
      status: "warning",
      score: 70,
      message: "Manual review is required before publish."
    }
  ],
  unsupported_claims: ["Claim about runtime market size has insufficient primary evidence."],
  citation_failure_categories: [
    {
      code: "missing_primary_source",
      count: 1,
      items: ["claim-runtime-market-size"]
    }
  ]
} as const
