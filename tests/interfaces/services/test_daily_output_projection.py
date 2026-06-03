from __future__ import annotations

from interfaces.services.daily_output_projection import (
    apply_daily_run_board_attachment_result,
    apply_daily_run_public_output_aliases,
    project_daily_run_agent_loop_metrics,
    project_daily_run_output_for_board_attachment,
    project_daily_run_output_for_memory_ingestion,
    project_daily_run_output_for_persistence,
    project_daily_run_output_for_run_inspection,
)


def test_project_daily_run_output_for_memory_ingestion_reads_namespaced_only_output() -> None:
    output = {
        "report.final": {"title": "Namespaced report"},
        "evidence.bundle": {"items": []},
        "quality.result": {"decision": "pass"},
    }

    projected = project_daily_run_output_for_memory_ingestion(output)

    assert projected == {
        "final_report": {"title": "Namespaced report"},
        "evidence_bundle": {"items": []},
        "quality_result": {"decision": "pass"},
    }
    assert "final_report" not in output


def test_project_daily_run_output_for_persistence_reads_record_input_keys() -> None:
    output = {
        "sources.pipeline_metrics": {"raw_items_count": 2},
        "loop.metrics": {"llm_calls": 3},
        "quality.report_summary": {"score": 0.9},
        "quality.gate_metrics": {"attempts": 1},
        "report.final": {"title": "Daily"},
        "quality.result": {"decision": "pass"},
        "quality.route": "published",
        "sources.raw_items": [{"title": "Raw"}],
        "evidence.bundle": {"items": []},
        "evidence.verified_findings": {"accepted_claims": []},
        "final_report": {"title": "legacy"},
    }

    projected = project_daily_run_output_for_persistence(output)

    assert projected == {
        "source_pipeline_metrics": {"raw_items_count": 2},
        "agent_loop_metrics": {"llm_calls": 3},
        "report_quality_summary": {"score": 0.9},
        "quality_gate_metrics": {"attempts": 1},
        "final_report": {"title": "Daily"},
        "quality_result": {"decision": "pass"},
        "quality_route": "published",
        "raw_items": [{"title": "Raw"}],
        "evidence_bundle": {"items": []},
        "verified_findings": {"accepted_claims": []},
    }


def test_project_daily_run_output_for_board_attachment_reads_namespaced_only_output() -> None:
    output = {
        "sources.ranked_items": [{"title": "Ranked"}],
        "sources.normalized_items": [{"title": "Normalized"}],
        "sources.raw_items": [{"title": "Raw"}],
        "evidence.bundle": {"items": []},
    }

    projected = project_daily_run_output_for_board_attachment(output)

    assert projected == {
        "ranked_items": [{"title": "Ranked"}],
        "normalized_items": [{"title": "Normalized"}],
        "raw_items": [{"title": "Raw"}],
        "evidence_bundle": {"items": []},
    }


def test_project_daily_run_output_for_run_inspection_reads_quality_preview_keys() -> None:
    output = {
        "run_id": "run-1",
        "quality_result": {"decision": "legacy"},
        "quality.result": {"decision": "blocked", "route": "human_review"},
        "quality.citation_check_result": {"unsupported_claims": ["claim-1"]},
        "quality.support_matrix": {"unsupported_sections": ["Summary"]},
        "report.final": {"report_id": "run-1:final"},
        "evidence.candidate_claims": [{"claim_id": "claim-1"}],
        "evidence.verified_findings": {"accepted_claims": [{"claim_id": "claim-1"}]},
        "sources.ranked_items": [{"title": "Ranked"}],
    }

    projected = project_daily_run_output_for_run_inspection(output)

    assert projected == {
        "run_id": "run-1",
        "final_report": {"report_id": "run-1:final"},
        "quality_result": {"decision": "blocked", "route": "human_review"},
        "citation_check_result": {"unsupported_claims": ["claim-1"]},
        "support_matrix": {"unsupported_sections": ["Summary"]},
        "candidate_claims": [{"claim_id": "claim-1"}],
        "verified_findings": {"accepted_claims": [{"claim_id": "claim-1"}]},
    }


def test_project_daily_run_agent_loop_metrics_prefers_namespaced_metric_alias() -> None:
    output = {
        "agent_loop_metrics": {"llm_calls": 1},
        "loop.metrics": {"llm_calls": 2, "tool_calls": 1},
    }

    metrics = project_daily_run_agent_loop_metrics(output)

    assert metrics == {"llm_calls": 2, "tool_calls": 1}


def test_apply_daily_run_board_attachment_result_merges_formal_result_keys() -> None:
    output = {"report.final": {"title": "Daily"}}
    board_output = {
        "board_outputs": {"ai_news": {"cards": []}},
        "cross_board_output": {"summary": "ok"},
        "ignored": "value",
    }

    result = apply_daily_run_board_attachment_result(output, board_output)

    assert result is output
    assert output["board_outputs"] == {"ai_news": {"cards": []}}
    assert output["cross_board_output"] == {"summary": "ok"}
    assert "ignored" not in output


def test_apply_daily_run_public_output_aliases_adds_legacy_public_aliases() -> None:
    output = {"report.final": {"title": "Daily"}}

    result = apply_daily_run_public_output_aliases(output)

    assert result is output
    assert output["final_report"] == {"title": "Daily"}
