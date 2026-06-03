from __future__ import annotations

import pytest

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    apply_daily_board_attachment_result,
    apply_daily_public_output_aliases,
    daily_output_contains,
    daily_output_value,
    ensure_legacy_daily_output_aliases,
    project_daily_output_for_agent_validation,
    project_daily_output_for_agentic_artifacts,
    project_daily_output_for_board_attachment,
    project_daily_output_for_evidence_artifacts,
    project_daily_output_for_interface_metadata,
    project_daily_output_for_memory_ingestion,
    project_daily_output_for_persistence,
    project_daily_output_for_legacy_consumers,
    project_daily_output_for_quality_artifacts,
    project_daily_output_for_report_artifacts,
    project_daily_output_for_routing_predicates,
    project_daily_output_for_run_inspection,
    project_daily_output_for_source_diagnostic_artifacts,
    project_daily_output_for_source_recollection_artifacts,
)


def test_daily_output_value_prefers_namespaced_value() -> None:
    output = {
        "final_report": {"title": "legacy"},
        "report.final": {"title": "namespaced"},
    }

    assert daily_output_value(output, "final_report") == {"title": "namespaced"}
    assert daily_output_value(output, "report.final") == {"title": "namespaced"}


def test_daily_output_value_falls_back_to_legacy_value() -> None:
    output = {"evidence_bundle": {"items": []}}

    assert daily_output_contains(output, "evidence.bundle") is True
    assert daily_output_value(output, "evidence.bundle") == {"items": []}
    assert daily_output_value(output, "missing", default="fallback") == "fallback"


def test_project_daily_output_for_legacy_consumers_returns_projected_copy() -> None:
    output = {
        "report.final": {"title": "namespaced"},
        "quality.result": {"decision": "pass"},
        "unmapped": "kept",
    }

    projected = project_daily_output_for_legacy_consumers(output)

    assert projected is not output
    assert "final_report" not in output
    assert projected["final_report"] == {"title": "namespaced"}
    assert projected["quality_result"] == {"decision": "pass"}
    assert projected["unmapped"] == "kept"


def test_project_daily_output_for_persistence_projects_only_record_input_keys() -> None:
    output = {
        "report.final": {"title": "namespaced"},
        "quality.result": {"decision": "pass"},
        "sources.raw_items": [{"title": "raw"}],
        "sources.ranked_items": [{"title": "ranked"}],
        "unmapped_runtime_state": {"hidden": True},
    }

    projected = project_daily_output_for_persistence(output)

    assert projected["final_report"] == {"title": "namespaced"}
    assert projected["quality_result"] == {"decision": "pass"}
    assert projected["raw_items"] == [{"title": "raw"}]
    assert "sources.ranked_items" not in projected
    assert "ranked_items" not in projected
    assert "unmapped_runtime_state" not in projected


def test_persistence_output_projection_requires_namespaced_daily_outputs() -> None:
    output = {
        "final_report": {"title": "legacy"},
        "quality_result": {"decision": "pass"},
        "unmapped_runtime_state": {"hidden": True},
    }

    projected = project_daily_output_for_persistence(output)

    assert projected == {}


def test_project_daily_output_for_board_attachment_projects_board_input_keys() -> None:
    output = {
        "sources.ranked_items": [{"title": "ranked"}],
        "evidence.bundle": {"items": []},
        "quality.result": {"decision": "pass"},
        "unmapped_runtime_state": {"hidden": True},
    }

    projected = project_daily_output_for_board_attachment(output)

    assert projected["ranked_items"] == [{"title": "ranked"}]
    assert projected["evidence_bundle"] == {"items": []}
    assert "quality.result" not in projected
    assert "quality_result" not in projected
    assert "unmapped_runtime_state" not in projected


def test_board_attachment_projection_requires_namespaced_daily_outputs() -> None:
    output = {
        "ranked_items": [{"title": "legacy ranked"}],
        "evidence_bundle": {"items": []},
        "quality.result": {"decision": "pass"},
    }

    projected = project_daily_output_for_board_attachment(output)

    assert projected == {}


def test_apply_daily_board_attachment_result_copies_only_attachment_outputs() -> None:
    output = {"report.final": {"title": "Namespaced report"}}
    board_output = {
        "ranked_items": [{"title": "board-mutated item"}],
        "board_outputs": {"ai_news": {"cards": []}},
        "cross_board_output": {"board_type": "cross_board"},
        "internal_selection_trace": {"hidden": True},
    }

    result = apply_daily_board_attachment_result(output, board_output)

    assert result is output
    assert output == {
        "report.final": {"title": "Namespaced report"},
        "board_outputs": {"ai_news": {"cards": []}},
        "cross_board_output": {"board_type": "cross_board"},
    }


def test_project_daily_output_for_memory_ingestion_projects_only_memory_inputs() -> None:
    output = {
        "request": {"topic": "AI"},
        "report.final": {"title": "namespaced"},
        "evidence.bundle": {"items": []},
        "quality.result": {"decision": "pass"},
        "sources.ranked_items": [{"title": "ranked"}],
        "agent.feedback.summary": {"event_count": 1},
    }

    projected = project_daily_output_for_memory_ingestion(output)

    assert projected == {
        "request": {"topic": "AI"},
        "final_report": {"title": "namespaced"},
        "evidence_bundle": {"items": []},
        "quality_result": {"decision": "pass"},
    }


def test_memory_ingestion_projection_requires_namespaced_daily_outputs() -> None:
    output = {
        "request": {"topic": "AI"},
        "final_report": {"title": "legacy"},
        "evidence_bundle": {"items": []},
        "quality_result": {"decision": "pass"},
    }

    projected = project_daily_output_for_memory_ingestion(output)

    assert projected == {"request": {"topic": "AI"}}


def test_project_daily_output_for_run_inspection_projects_only_quality_preview_inputs() -> None:
    output = {
        "run_id": "run-1",
        "report.final": {"report_id": "run-1:final"},
        "quality.result": {"decision": "blocked", "route": "human_review"},
        "quality.citation_check_result": {"unsupported_claims": ["claim-1"]},
        "quality.support_matrix": {"unsupported_sections": ["Summary"]},
        "evidence.candidate_claims": [{"claim_id": "claim-1"}],
        "evidence.verified_findings": {"accepted_claims": [{"claim_id": "claim-1"}]},
        "sources.ranked_items": [{"title": "ranked"}],
        "agent.feedback.summary": {"event_count": 1},
    }

    projected = project_daily_output_for_run_inspection(output)

    assert projected == {
        "run_id": "run-1",
        "final_report": {"report_id": "run-1:final"},
        "quality_result": {"decision": "blocked", "route": "human_review"},
        "citation_check_result": {"unsupported_claims": ["claim-1"]},
        "support_matrix": {"unsupported_sections": ["Summary"]},
        "candidate_claims": [{"claim_id": "claim-1"}],
        "verified_findings": {"accepted_claims": [{"claim_id": "claim-1"}]},
    }


def test_run_inspection_projection_requires_namespaced_daily_outputs() -> None:
    output = {
        "run_id": "run-1",
        "final_report": {"report_id": "legacy-final"},
        "quality_result": {"decision": "legacy"},
        "citation_check_result": {"unsupported_claims": ["claim-1"]},
        "support_matrix": {"unsupported_sections": ["Summary"]},
        "candidate_claims": [{"claim_id": "claim-1"}],
        "verified_findings": {"accepted_claims": [{"claim_id": "claim-1"}]},
    }

    projected = project_daily_output_for_run_inspection(output)

    assert projected == {"run_id": "run-1"}


def test_project_daily_output_for_interface_metadata_reads_namespaced_agent_metrics() -> None:
    output = {
        "agent_loop_metrics": {"llm_calls": 1},
        "loop.metrics": {"llm_calls": 2, "tool_calls": 1},
    }

    projected = project_daily_output_for_interface_metadata(output)

    assert projected == {"agent_loop_metrics": {"llm_calls": 2, "tool_calls": 1}}


def test_interface_metadata_projection_requires_namespaced_daily_outputs() -> None:
    output = {"agent_loop_metrics": {"llm_calls": 1}}

    projected = project_daily_output_for_interface_metadata(output)

    assert projected == {}


def test_project_daily_output_for_agent_validation_reads_namespaced_final_report() -> None:
    output = {
        "final_report": {"title": "legacy"},
        "report.final": {"title": "Daily", "sections": []},
    }

    projected = project_daily_output_for_agent_validation(output)

    assert projected == {"final_report": {"title": "Daily", "sections": []}}


def test_agent_validation_projection_requires_namespaced_daily_outputs() -> None:
    output = {"final_report": {"title": "legacy", "sections": []}}

    projected = project_daily_output_for_agent_validation(output)

    assert projected == {}


def test_project_daily_output_for_quality_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "quality_result": {"decision": "legacy"},
        "quality.result": {"decision": "pass"},
        "quality_route": "human_review",
        "citation_check_result": {"unsupported_claims": ["legacy"]},
        "quality.citation_check_result": {"unsupported_claims": ["namespaced"]},
        "quality.gate_metrics": {"blocked": False},
    }

    projected = project_daily_output_for_quality_artifacts(output)

    assert projected == {
        "citation_check_result": {"unsupported_claims": ["namespaced"]},
        "quality_gate_metrics": {"blocked": False},
        "quality_result": {"decision": "pass"},
        "quality_route": "human_review",
    }


def test_project_daily_output_for_evidence_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "evidence_bundle": {"bundle_id": "legacy"},
        "evidence.bundle": {"bundle_id": "namespaced"},
        "evidence_source_map": {"ev-1": ["https://example.com/source"]},
    }

    projected = project_daily_output_for_evidence_artifacts(output)

    assert projected == {
        "evidence_bundle": {"bundle_id": "namespaced"},
        "evidence_source_map": {"ev-1": ["https://example.com/source"]},
    }


def test_project_daily_output_for_source_recollection_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "source_recollection_execution_report": {"status": "legacy"},
        "sources.recollection_execution_report": {"status": "succeeded"},
        "source_recollection_quality_assessment": {"decision": "pass"},
    }

    projected = project_daily_output_for_source_recollection_artifacts(output)

    assert projected == {
        "source_recollection_execution_report": {"status": "succeeded"},
        "source_recollection_quality_assessment": {"decision": "pass"},
    }


def test_project_daily_output_for_source_diagnostic_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "source_events": [{"event_type": "legacy"}],
        "sources.events": [{"event_type": "namespaced"}],
        "source_quality_scores": [{"source_id": "feed"}],
        "sources.ranked_items": [{"title": "not published as diagnostic artifact"}],
    }

    projected = project_daily_output_for_source_diagnostic_artifacts(output)

    assert projected == {
        "source_events": [{"event_type": "namespaced"}],
        "source_quality_scores": [{"source_id": "feed"}],
    }


def test_project_daily_output_for_agentic_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "planner_agent_loop_result": {"status": "legacy"},
        "agent.planner.loop.result": {"status": "accepted"},
        "agent_feedback_summary": {"highest_severity": "legacy"},
        "agent.feedback.summary": {"highest_severity": "warning"},
        "quality.result": {"decision": "rewrite_required"},
        "source_events": [{"event_type": "not agentic"}],
    }

    projected = project_daily_output_for_agentic_artifacts(output)

    assert projected == {
        "planner_agent_loop_result": {"status": "accepted"},
        "agent_feedback_summary": {"highest_severity": "warning"},
        "quality_result": {"decision": "rewrite_required"},
    }


def test_project_daily_output_for_report_artifacts_keeps_legacy_fallback() -> None:
    output = {
        "final_report": {"title": "legacy"},
        "report.final": {"title": "namespaced"},
        "report_markdown": "# Legacy",
        "sources.events": [{"event_type": "not report"}],
    }

    projected = project_daily_output_for_report_artifacts(output)

    assert projected == {
        "final_report": {"title": "namespaced"},
        "report_markdown": "# Legacy",
    }


def test_project_daily_output_for_routing_predicates_requires_namespaced_outputs() -> None:
    output = {
        "quality_gate_metrics": {"decision": "blocked"},
        "quality.gate_metrics": {"decision": "pass"},
        "agent.feedback.route": {"decision": "retry_required"},
        "report.final": {"title": "not routing"},
    }

    projected = project_daily_output_for_routing_predicates(output)

    assert projected == {
        "agent_feedback_route": {"decision": "retry_required"},
        "quality_gate_metrics": {"decision": "pass"},
    }


def test_ensure_legacy_daily_output_aliases_mutates_output_for_service_consumers() -> None:
    output = {
        "ranked_items": [{"title": "legacy"}],
        "sources.ranked_items": [{"title": "namespaced"}],
    }

    result = ensure_legacy_daily_output_aliases(output, keys=["sources.ranked_items"])

    assert result is output
    assert output["ranked_items"] == [{"title": "namespaced"}]


def test_ensure_legacy_daily_output_aliases_requires_explicit_alias_scope() -> None:
    with pytest.raises(TypeError):
        ensure_legacy_daily_output_aliases({"report.final": {"title": "Daily"}})


def test_apply_daily_public_output_aliases_exposes_only_public_compatibility_keys() -> None:
    output = {
        "report.final": {"title": "namespaced"},
        "quality.result": {"decision": "pass"},
        "sources.ranked_items": [{"title": "ranked"}],
        "agent.feedback.summary": {"event_count": 1},
        "agent.writer.loop.metrics": {"llm_calls": 3},
        "sources.pipeline_metrics": {"raw_items_count": 1},
    }

    result = apply_daily_public_output_aliases(output)

    assert result is output
    assert output["final_report"] == {"title": "namespaced"}
    assert output["quality_result"] == {"decision": "pass"}
    assert output["ranked_items"] == [{"title": "ranked"}]
    assert "agent_feedback_summary" not in output
    assert "writer_agent_loop_metrics" not in output
    assert "source_pipeline_metrics" not in output
