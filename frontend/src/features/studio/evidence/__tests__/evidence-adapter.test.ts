import { describe, expect, it } from "vitest"
import { adaptLlmTrace, adaptRunEvidenceDetail } from "@/features/studio/evidence/lib/evidence-adapter"

describe("Evidence adapter", () => {
  it("maps quality trace lineage claims to claim evidence rows", () => {
    const detail = adaptRunEvidenceDetail({
      runId: "run-1",
      runDetail: {
        run_id: "run-1",
        workflow_id: "daily",
        output_preview: {
          quality_trace: {
            decision: "blocked",
            route: "human_review",
            citation_failure_categories: [{ code: "unsupported_claims", count: 1, items: ["Summary: Unsupported"] }],
            quality_lineage: {
              report_id: "run-1:final",
              claims: [
                {
                  claim_id: "claim-1",
                  status: "accepted",
                  text: "Supported claim",
                  supporting_evidence_ids: ["ev-1"],
                  supporting_sources: ["https://example.com/source"]
                }
              ]
            }
          }
        }
      }
    })

    expect(detail.hasQualityTrace).toBe(true)
    expect(detail.claims).toHaveLength(1)
    expect(detail.claims[0]).toMatchObject({
      claimId: "claim-1",
      claimText: "Supported claim",
      status: "accepted",
      evidenceRefs: [{ evidenceId: "ev-1" }],
      sourceRefs: [{ url: "https://example.com/source" }]
    })
    expect(detail.counts.accepted).toBe(1)
    expect(detail.citationFailureCategories[0].code).toBe("unsupported_claims")
  })

  it("returns partial notice when quality trace is missing", () => {
    const detail = adaptRunEvidenceDetail({
      runId: "run-missing",
      runDetail: { run_id: "run-missing", output_preview: {} }
    })

    expect(detail.dataState).toBe("partial")
    expect(detail.hasQualityTrace).toBe(false)
    expect(detail.claims).toEqual([])
    expect(detail.notices).toContain("This run did not include a quality_trace evidence matrix.")
  })

  it("merges unsupported and rejected claim usage with priority", () => {
    const detail = adaptRunEvidenceDetail({
      runId: "run-risk",
      runDetail: {
        run_id: "run-risk",
        output_preview: {
          quality_trace: {
            unsupported_claims: [{ claim_id: "claim-risk", text: "Risky claim", section_title: "Summary" }],
            rejected_claim_usage: [{ claim_id: "claim-risk", text: "Risky claim", reason: "Contradicted" }]
          }
        }
      }
    })

    expect(detail.claims).toHaveLength(1)
    expect(detail.claims[0].status).toBe("rejected")
    expect(detail.claims[0].reportSection).toBe("Summary")
    expect(detail.claims[0].failureReason).toBe("Contradicted")
    expect(detail.counts.rejected).toBe(1)
  })

  it("redacts sensitive values from llm trace", () => {
    const trace = adaptLlmTrace({
      selected_deployment_id: "primary",
      fallback_used: true,
      router_event_count: 2,
      api_key: "sk-secretvalue",
      nested: {
        prompt: "full prompt",
        authorization: "Bearer abc123"
      }
    })

    expect(trace?.selectedDeploymentId).toBe("primary")
    const serialized = JSON.stringify(trace?.sanitized)
    expect(serialized).not.toContain("sk-secretvalue")
    expect(serialized).not.toContain("full prompt")
    expect(serialized).not.toContain("Bearer abc123")
    expect(serialized).toContain("[redacted]")
  })
})
