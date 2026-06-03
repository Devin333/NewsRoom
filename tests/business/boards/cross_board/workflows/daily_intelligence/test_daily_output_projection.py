from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains,
    daily_output_value,
    ensure_legacy_daily_output_aliases,
    project_daily_output_for_board_attachment,
    project_daily_output_for_memory_ingestion,
    project_daily_output_for_persistence,
    project_daily_output_for_legacy_consumers,
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
    }

    projected = project_daily_output_for_persistence(output)

    assert projected["final_report"] == {"title": "namespaced"}
    assert projected["quality_result"] == {"decision": "pass"}
    assert projected["raw_items"] == [{"title": "raw"}]
    assert "ranked_items" not in projected


def test_project_daily_output_for_board_attachment_projects_board_input_keys() -> None:
    output = {
        "sources.ranked_items": [{"title": "ranked"}],
        "evidence.bundle": {"items": []},
        "quality.result": {"decision": "pass"},
    }

    projected = project_daily_output_for_board_attachment(output)

    assert projected["ranked_items"] == [{"title": "ranked"}]
    assert projected["evidence_bundle"] == {"items": []}
    assert "quality_result" not in projected


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


def test_ensure_legacy_daily_output_aliases_mutates_output_for_service_consumers() -> None:
    output = {
        "ranked_items": [{"title": "legacy"}],
        "sources.ranked_items": [{"title": "namespaced"}],
    }

    result = ensure_legacy_daily_output_aliases(output, keys=["sources.ranked_items"])

    assert result is output
    assert output["ranked_items"] == [{"title": "namespaced"}]
