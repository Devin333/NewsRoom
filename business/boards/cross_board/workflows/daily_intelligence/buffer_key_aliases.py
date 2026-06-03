from __future__ import annotations

from typing import Any


SOURCE_BUFFER_ALIASES = {
    "raw_items": "sources.raw_items",
    "normalized_items": "sources.normalized_items",
    "deduplicated_items": "sources.deduplicated_items",
    "ranked_items": "sources.ranked_items",
    "source_errors": "sources.errors",
    "source_events": "sources.events",
    "source_pipeline_metrics": "sources.pipeline_metrics",
    "source_duplicate_groups": "sources.duplicate_groups",
    "source_coverage_report": "sources.coverage_report",
    "source_quality_scores": "sources.quality_scores",
    "source_quality_summary_report": "sources.quality_summary_report",
    "source_ranking_scores": "sources.ranking_scores",
    "source_freshness_report": "sources.freshness_report",
    "source_traceability_report": "sources.traceability_report",
    "source_governance_report": "sources.governance_report",
    "skipped_sources": "sources.skipped",
    "failed_sources": "sources.failed",
    "source_fetch_requests": "sources.fetch_requests",
    "source_fetch_results": "sources.fetch_results",
    "source_health_updates": "sources.health_updates",
    "source_health_report": "sources.health_report",
    "source_connector_dispatch_report": "sources.connector_dispatch_report",
    "source_error_policy_report": "sources.error_policy_report",
    "source_fallback_report": "sources.fallback_report",
    "source_selection_report": "sources.selection_report",
    "source_collection_status": "sources.collection_status",
    "source_recollection_profile": "sources.recollection_profile",
    "source_recollection_execution_plan": "sources.recollection_execution_plan",
    "source_recollection_execution_report": "sources.recollection_execution_report",
    "source_recollection_quality_assessment": "sources.recollection_quality_assessment",
}

EVIDENCE_BUFFER_ALIASES = {
    "evidence_bundle": "evidence.bundle",
    "evidence_scores": "evidence.scores",
    "candidate_claims": "evidence.candidate_claims",
    "verified_findings": "evidence.verified_findings",
}

QUALITY_BUFFER_ALIASES = {
    "quality_events": "quality.events",
    "verification_result": "quality.verification_result",
    "citation_check_result": "quality.citation_check_result",
    "editor_review": "quality.editor_review",
    "support_matrix": "quality.support_matrix",
    "report_quality_summary": "quality.report_summary",
    "quality_gate_metrics": "quality.gate_metrics",
    "quality_result": "quality.result",
    "quality_route": "quality.route",
    "rewrite_policy": "quality.rewrite_policy",
    "rewrite_instructions": "quality.rewrite_instructions",
    "rewritten_report_draft": "quality.rewritten_report_draft",
    "human_review_request": "quality.human_review_request",
    "human_review_resume_route": "quality.human_review_resume_route",
    "memory_quality_result": "memory.quality_result",
}

MEMORY_BUFFER_ALIASES = {
    "memory_context": "memory.context",
    "historian_context": "memory.historian_context",
}

REPORT_BUFFER_ALIASES = {
    "report_draft": "report.draft",
    "edited_report_draft": "report.edited_draft",
    "final_report": "report.final",
    "report_markdown": "report.markdown",
    "blocked_report": "report.blocked",
}

AGENT_BUFFER_ALIASES = {
    "agent_feedback_events": "agent.feedback.events",
    "agent_feedback_summary": "agent.feedback.summary",
    "agent_feedback_route": "agent.feedback.route",
    "agent_feedback_loop_state": "agent.feedback.loop_state",
}

AGENT_PAYLOAD_BUFFER_ALIASES = {
    "research_plan": "agent.planner.research_plan",
    "planner_notes": "agent.planner.notes",
    "analysis_result": "agent.analyst.analysis_result",
    "analyst_notes": "agent.analyst.notes",
    "writer_notes": "agent.writer.notes",
    "verifier_notes": "agent.verifier.notes",
    "editor_notes": "agent.editor.notes",
}

AGENT_LOOP_LABELS = ("planner", "analyst", "writer", "verifier", "editor")
AGENT_LOOP_TELEMETRY_SUFFIX_ALIASES = {
    "agent_loop_result": "loop.result",
    "agent_loop_events": "loop.events",
    "agent_loop_metrics": "loop.metrics",
    "agent_loop_diagnostics": "loop.diagnostics",
    "agent_loop_trace": "loop.trace",
    "llm_call_artifacts": "loop.llm_call_artifacts",
}
AGENT_LOOP_TELEMETRY_BUFFER_ALIASES = {
    f"{label}_{legacy_suffix}": f"agent.{label}.{namespaced_suffix}"
    for label in AGENT_LOOP_LABELS
    for legacy_suffix, namespaced_suffix in AGENT_LOOP_TELEMETRY_SUFFIX_ALIASES.items()
}

DAILY_BUFFER_ALIASES = {
    **SOURCE_BUFFER_ALIASES,
    **EVIDENCE_BUFFER_ALIASES,
    **QUALITY_BUFFER_ALIASES,
    **MEMORY_BUFFER_ALIASES,
    **REPORT_BUFFER_ALIASES,
    **AGENT_BUFFER_ALIASES,
    **AGENT_PAYLOAD_BUFFER_ALIASES,
    **AGENT_LOOP_TELEMETRY_BUFFER_ALIASES,
}


def with_namespaced_aliases(
    outputs: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    alias_map = aliases or DAILY_BUFFER_ALIASES
    values = dict(outputs)
    for legacy_key, namespaced_key in alias_map.items():
        if legacy_key in values and namespaced_key not in values:
            values[namespaced_key] = values[legacy_key]
    return values


def canonicalize_namespaced_input_aliases(
    inputs: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    alias_map = aliases or DAILY_BUFFER_ALIASES
    values = dict(inputs)
    for legacy_key, namespaced_key in alias_map.items():
        if namespaced_key in values:
            values[legacy_key] = values[namespaced_key]
            values.pop(namespaced_key, None)
    return values


def with_namespaced_write_keys(keys: list[str]) -> list[str]:
    values = list(keys)
    for legacy_key in keys:
        namespaced_key = DAILY_BUFFER_ALIASES.get(legacy_key)
        if namespaced_key and namespaced_key not in values:
            values.append(namespaced_key)
    return values


def with_namespaced_read_keys(keys: list[str]) -> list[str]:
    return with_namespaced_write_keys(keys)


def with_namespaced_primary_read_keys(keys: list[str]) -> list[str]:
    values: list[str] = []
    for key in keys:
        namespaced_key = DAILY_BUFFER_ALIASES.get(key)
        if namespaced_key and namespaced_key not in values:
            values.append(namespaced_key)
        if key not in values:
            values.append(key)
    return values


def agent_loop_output_aliases(label: str) -> dict[str, str]:
    prefix = f"{label}_"
    return {
        legacy_key: namespaced_key
        for legacy_key, namespaced_key in AGENT_LOOP_TELEMETRY_BUFFER_ALIASES.items()
        if legacy_key.startswith(prefix)
    }
