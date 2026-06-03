from __future__ import annotations

from interfaces.services.run_inspection_projection import (
    project_quality_lineage_preview,
    project_quality_trace_preview,
)


def test_project_quality_trace_preview_builds_trace_from_canonical_output() -> None:
    trace = project_quality_trace_preview(
        {
            "run_id": "run-1",
            "quality_result": {
                "decision": "blocked",
                "route": "human_review",
                "metadata": {"citation_failure_categories": ["unsupported_claims"]},
            },
            "citation_check_result": {
                "unsupported_claims": ["claim-1"],
                "rejected_claim_usage": [],
            },
            "support_matrix": {"unsupported_sections": ["Summary"]},
            "final_report": {"report_id": "run-1:final", "title": "Daily"},
            "candidate_claims": [{"claim_id": "claim-1"}],
        }
    )

    assert trace["decision"] == "blocked"
    assert trace["route"] == "human_review"
    assert trace["citation_failure_categories"] == ["unsupported_claims"]
    assert trace["unsupported_claims"] == ["claim-1"]
    assert trace["unsupported_sections"] == ["Summary"]
    assert trace["quality_lineage"]["report_id"] == "run-1:final"
    assert trace["quality_lineage"]["claim_count"] == 1


def test_project_quality_trace_preview_falls_back_to_quality_route() -> None:
    trace = project_quality_trace_preview(
        {
            "run_id": "run-1",
            "quality_route": "blocked",
            "quality_result": {"decision": "blocked"},
        }
    )

    assert trace["route"] == "blocked"


def test_project_quality_lineage_preview_uses_blocked_report_id() -> None:
    lineage = project_quality_lineage_preview(
        {
            "run_id": "run-1",
            "blocked_report": {"report_id": "run-1:blocked"},
            "verified_findings": {
                "accepted_claims": [{"claim_id": "claim-1"}],
                "rejected_claims": [],
                "uncertain_claims": [],
            },
            "quality_result": {"decision": "blocked"},
        }
    )

    assert lineage["report_id"] == "run-1:blocked"
    assert lineage["claim_count"] == 1
