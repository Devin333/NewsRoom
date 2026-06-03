from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    agent_loop_output_aliases,
    canonicalize_namespaced_input_aliases,
    with_namespaced_aliases,
    with_namespaced_primary_read_keys,
    with_namespaced_read_keys,
    with_namespaced_write_keys,
)


def test_with_namespaced_aliases_adds_compatible_aliases_without_removing_legacy_keys() -> None:
    source_errors = []
    outputs = with_namespaced_aliases(
        {
            "source_errors": source_errors,
            "quality_events": [],
            "verification_result": {"status": "pass"},
            "unmapped": "kept",
        }
    )

    assert outputs["source_errors"] is source_errors
    assert outputs["sources.errors"] is source_errors
    assert outputs["quality.events"] == []
    assert outputs["quality.verification_result"] == {"status": "pass"}
    assert outputs["unmapped"] == "kept"


def test_with_namespaced_aliases_adds_agent_loop_telemetry_aliases() -> None:
    result = {"success": True}
    metrics = {"llm_calls": 1}
    outputs = with_namespaced_aliases(
        {
            "planner_agent_loop_result": result,
            "planner_agent_loop_metrics": metrics,
            "planner_llm_call_artifacts": [],
        }
    )

    assert outputs["agent.planner.loop.result"] is result
    assert outputs["agent.planner.loop.metrics"] is metrics
    assert outputs["agent.planner.loop.llm_call_artifacts"] == []


def test_with_namespaced_aliases_adds_agent_payload_aliases() -> None:
    research_plan = {"topic": "AI policy"}
    analysis_result = {"findings": []}
    outputs = with_namespaced_aliases(
        {
            "research_plan": research_plan,
            "planner_notes": {"mode": "offline"},
            "analysis_result": analysis_result,
            "analyst_notes": {"mode": "offline"},
        }
    )

    assert outputs["agent.planner.research_plan"] is research_plan
    assert outputs["agent.planner.notes"] == {"mode": "offline"}
    assert outputs["agent.analyst.analysis_result"] is analysis_result
    assert outputs["agent.analyst.notes"] == {"mode": "offline"}


def test_canonicalize_namespaced_input_aliases_prefers_namespaced_values() -> None:
    inputs = canonicalize_namespaced_input_aliases(
        {
            "evidence_bundle": "legacy-bundle",
            "evidence.bundle": "namespaced-bundle",
            "quality.verification_result": {"status": "pass"},
            "sources.errors": [],
            "unmapped": "kept",
        }
    )

    assert inputs == {
        "evidence_bundle": "namespaced-bundle",
        "verification_result": {"status": "pass"},
        "source_errors": [],
        "unmapped": "kept",
    }


def test_with_namespaced_write_keys_declares_aliases_after_legacy_keys() -> None:
    keys = with_namespaced_write_keys(
        ["source_errors", "quality_events", "verification_result", "unmapped"]
    )

    assert keys == [
        "source_errors",
        "quality_events",
        "verification_result",
        "unmapped",
        "sources.errors",
        "quality.events",
        "quality.verification_result",
    ]


def test_agent_loop_output_aliases_returns_single_agent_telemetry_map() -> None:
    aliases = agent_loop_output_aliases("writer")

    assert aliases == {
        "writer_agent_loop_result": "agent.writer.loop.result",
        "writer_agent_loop_events": "agent.writer.loop.events",
        "writer_agent_loop_metrics": "agent.writer.loop.metrics",
        "writer_agent_loop_diagnostics": "agent.writer.loop.diagnostics",
        "writer_agent_loop_trace": "agent.writer.loop.trace",
        "writer_llm_call_artifacts": "agent.writer.loop.llm_call_artifacts",
    }


def test_with_namespaced_read_keys_declares_aliases_after_legacy_keys() -> None:
    keys = with_namespaced_read_keys(
        ["research_plan", "report_draft", "evidence_bundle", "quality_events", "unmapped"]
    )

    assert keys == [
        "research_plan",
        "report_draft",
        "evidence_bundle",
        "quality_events",
        "unmapped",
        "agent.planner.research_plan",
        "report.draft",
        "evidence.bundle",
        "quality.events",
    ]


def test_with_namespaced_primary_read_keys_declares_aliases_before_legacy_keys() -> None:
    keys = with_namespaced_primary_read_keys(
        ["research_plan", "report_draft", "evidence_bundle", "quality_events", "unmapped"]
    )

    assert keys == [
        "agent.planner.research_plan",
        "research_plan",
        "report.draft",
        "report_draft",
        "evidence.bundle",
        "evidence_bundle",
        "quality.events",
        "quality_events",
        "unmapped",
    ]
