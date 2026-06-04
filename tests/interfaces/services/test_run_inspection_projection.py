from __future__ import annotations

from interfaces.services.run_inspection_projection import (
    project_llm_trace_preview,
    project_manifest_output_preview,
    project_partial_artifacts_preview,
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


def test_project_quality_trace_preview_prefers_namespaced_output() -> None:
    trace = project_quality_trace_preview(
        {
            "run_id": "run-1",
            "quality_result": {"decision": "legacy", "route": "legacy"},
            "quality.result": {
                "decision": "blocked",
                "route": "human_review",
                "metadata": {"citation_failure_categories": ["unsupported_claims"]},
            },
            "quality.citation_check_result": {
                "unsupported_claims": ["claim-1"],
                "rejected_claim_usage": [],
            },
            "quality.support_matrix": {"unsupported_sections": ["Summary"]},
            "report.final": {"report_id": "run-1:final"},
            "evidence.candidate_claims": [{"claim_id": "claim-1"}],
        }
    )

    assert trace["decision"] == "blocked"
    assert trace["route"] == "human_review"
    assert trace["citation_failure_categories"] == ["unsupported_claims"]
    assert trace["unsupported_claims"] == ["claim-1"]
    assert trace["unsupported_sections"] == ["Summary"]
    assert trace["quality_lineage"]["report_id"] == "run-1:final"
    assert trace["quality_lineage"]["claim_count"] == 1


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


def test_project_llm_trace_preview_extracts_route_metrics() -> None:
    trace = project_llm_trace_preview(
        {
            "llm_route_manifest": {
                "selected_deployment_id": "gpt-test",
                "fallback_used": True,
                "fallback_count": 1,
                "metrics": {
                    "provider_error_count": 2,
                    "cooldown_skip_count": 3,
                },
                "budget_check": {"passed": True},
                "global_budget_check": {"passed": True},
            },
            "llm_router_events": [{"event": "primary_failed"}],
        }
    )

    assert trace == {
        "selected_deployment_id": "gpt-test",
        "fallback_used": True,
        "fallback_count": 1,
        "provider_error_count": 2,
        "cooldown_skip_count": 3,
        "router_event_count": 1,
        "budget_check": {"passed": True},
        "global_budget_check": {"passed": True},
    }


def test_project_partial_artifacts_preview_lists_required_artifacts_first_class() -> None:
    preview = project_partial_artifacts_preview(
        {
            "manifest": "manifest.json",
            "events": "events.jsonl",
            "step_results": "step_results.json",
            "custom": "custom.json",
        }
    )

    assert preview["required_artifact_keys"] == ["events", "step_results", "manifest"]
    assert preview["artifact_keys"] == ["custom", "events", "manifest", "step_results"]


def test_project_manifest_output_preview_combines_output_quality_llm_and_artifacts() -> None:
    preview = project_manifest_output_preview(
        {
            "quality.result": {"decision": "blocked"},
            "llm_route_manifest": {"selected_deployment_id": "gpt-test"},
        },
        business_output={
            "quality_result": {"decision": "blocked", "route": "human_review"},
        },
        artifacts={"manifest": "manifest.json"},
    )

    assert preview["quality.result"] == {"type": "object", "keys": ["decision"]}
    assert preview["quality_trace"]["decision"] == "blocked"
    assert preview["llm_trace"]["selected_deployment_id"] == "gpt-test"
    assert preview["partial_artifacts"]["required_artifact_keys"] == ["manifest"]
