from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from enum import Enum
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    AGENT_LOOP_LABELS,
    DAILY_BUFFER_ALIASES,
    legacy_key_for,
    namespaced_first_key_candidates,
    namespaced_key_for,
)


_MISSING = object()


class DailyOutputProjectionReadPolicy(str, Enum):
    NAMESPACED_ONLY = "namespaced_only"
    NAMESPACED_WITH_LEGACY_FALLBACK = "namespaced_with_legacy_fallback"


def daily_output_value(
    output: Mapping[str, Any],
    key: str,
    *,
    default: Any = None,
) -> Any:
    for candidate_key in _output_key_candidates(
        key,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    ):
        if candidate_key in output:
            return output[candidate_key]
    return default


def daily_output_contains(output: Mapping[str, Any], key: str) -> bool:
    return any(
        candidate_key in output
        for candidate_key in _output_key_candidates(
            key,
            read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
        )
    )


def project_daily_output_for_legacy_consumers(
    output: Mapping[str, Any],
    *,
    keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    projected = dict(output)
    for legacy_key in _legacy_projection_keys(keys):
        if daily_output_contains(output, legacy_key):
            projected[legacy_key] = daily_output_value(output, legacy_key)
    return projected


def project_daily_output_for_persistence(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_PERSISTENCE_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def project_daily_output_for_board_attachment(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def apply_daily_board_attachment_result(
    output: MutableMapping[str, Any],
    board_output: Mapping[str, Any],
) -> MutableMapping[str, Any]:
    for key in DAILY_BOARD_ATTACHMENT_RESULT_KEYS:
        if key in board_output:
            output[key] = board_output[key]
    return output


def project_daily_output_for_memory_ingestion(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_MEMORY_INGESTION_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def project_daily_output_for_run_inspection(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_RUN_INSPECTION_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def project_daily_output_for_interface_metadata(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_INTERFACE_METADATA_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def project_daily_output_for_agent_validation(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_AGENT_VALIDATION_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_ONLY,
    )


def project_daily_output_for_quality_artifacts(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_evidence_artifacts(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_source_recollection_artifacts(
    output: Mapping[str, Any],
) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_source_diagnostic_artifacts(
    output: Mapping[str, Any],
) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_agentic_artifacts(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_report_artifacts(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_REPORT_ARTIFACT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def apply_daily_public_output_aliases(
    output: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return ensure_legacy_daily_output_aliases(
        output,
        keys=DAILY_PUBLIC_OUTPUT_ALIAS_KEYS,
    )


def ensure_legacy_daily_output_aliases(
    output: MutableMapping[str, Any],
    *,
    keys: Iterable[str] | None = None,
) -> MutableMapping[str, Any]:
    for legacy_key in _legacy_projection_keys(keys):
        if daily_output_contains(output, legacy_key):
            output[legacy_key] = daily_output_value(output, legacy_key)
    return output


def _output_key_candidates(
    key: str,
    *,
    read_policy: DailyOutputProjectionReadPolicy,
) -> list[str]:
    namespaced_key = namespaced_key_for(key)
    if namespaced_key is not None:
        if read_policy == DailyOutputProjectionReadPolicy.NAMESPACED_ONLY:
            return [namespaced_key]
        return namespaced_first_key_candidates(key)

    legacy_key = legacy_key_for(key)
    if legacy_key is not None:
        if read_policy == DailyOutputProjectionReadPolicy.NAMESPACED_ONLY:
            return [key]
    return namespaced_first_key_candidates(key)


def _legacy_projection_keys(keys: Iterable[str] | None) -> list[str]:
    if keys is None:
        return list(DAILY_BUFFER_ALIASES)

    result: list[str] = []
    for key in keys:
        legacy_key = legacy_key_for(key)
        if legacy_key is not None and legacy_key not in result:
            result.append(legacy_key)
    return result


def _project_daily_output_for_keys(
    output: Mapping[str, Any],
    keys: Iterable[str],
    *,
    include_original: bool,
    read_policy: DailyOutputProjectionReadPolicy,
) -> dict[str, Any]:
    projected = dict(output) if include_original else {}
    for key in keys:
        value = _daily_output_value(
            output,
            key,
            read_policy=read_policy,
            default=_MISSING,
        )
        if value is not _MISSING:
            projected[_canonical_projection_key(key)] = value
    return projected


def _daily_output_value(
    output: Mapping[str, Any],
    key: str,
    *,
    read_policy: DailyOutputProjectionReadPolicy,
    default: Any = None,
) -> Any:
    for candidate_key in _output_key_candidates(key, read_policy=read_policy):
        if candidate_key in output:
            return output[candidate_key]
    return default


def _canonical_projection_key(key: str) -> str:
    return legacy_key_for(key) or key

DAILY_PERSISTENCE_OUTPUT_KEYS = (
    "source_pipeline_metrics",
    "agent_loop_metrics",
    "report_quality_summary",
    "quality_gate_metrics",
    "final_report",
    "blocked_report",
    "report_markdown",
    "quality_result",
    "quality_route",
    "citation_check_result",
    "support_matrix",
    "editor_review",
    "raw_items",
    "evidence_bundle",
    "verified_findings",
)

DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS = (
    "signals",
    "ranked_items",
    "normalized_items",
    "raw_items",
    "evidence_bundle",
)

DAILY_MEMORY_INGESTION_OUTPUT_KEYS = (
    "request",
    "final_report",
    "blocked_report",
    "evidence_bundle",
    "evidence_items",
    "quality_result",
    "verification_result",
    "review_result",
)

DAILY_RUN_INSPECTION_OUTPUT_KEYS = (
    "run_id",
    "report_id",
    "final_report",
    "blocked_report",
    "quality_result",
    "quality_route",
    "citation_check_result",
    "support_matrix",
    "candidate_claims",
    "verified_findings",
)

DAILY_INTERFACE_METADATA_OUTPUT_KEYS = (
    "agent_loop_metrics",
)

DAILY_AGENT_VALIDATION_OUTPUT_KEYS = (
    "final_report",
)

DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS = (
    "citation_check_result",
    "editor_review",
    "support_matrix",
    "report_quality_summary",
    "quality_events",
    "quality_gate_metrics",
    "quality_result",
    "quality_route",
    "rewrite_policy",
    "rewrite_instructions",
    "rewritten_report_draft",
    "human_review_request",
)

DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS = (
    "evidence_bundle",
    "evidence_source_map",
    "evidence_scores",
    "candidate_claims",
    "verified_findings",
)

DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS = (
    "source_recollection_profile",
    "source_recollection_execution_plan",
    "source_recollection_execution_report",
    "source_recollection_quality_assessment",
)

DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS = (
    "raw_items",
    "source_errors",
    "skipped_sources",
    "failed_sources",
    "source_fetch_requests",
    "source_fetch_results",
    "source_health_updates",
    "source_health_report",
    "source_duplicate_groups",
    "source_events",
    "source_pipeline_metrics",
    "source_connector_dispatch_report",
    "source_error_policy_report",
    "source_fallback_report",
    "source_selection_report",
    "source_coverage_report",
    "source_quality_scores",
    "source_quality_summary_report",
    "source_ranking_scores",
    "source_freshness_report",
    "source_traceability_report",
    "source_governance_report",
    *DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS,
)

DAILY_AGENTIC_ARTIFACT_LOOP_OUTPUT_SUFFIXES = (
    "agent_loop_result",
    "agent_loop_metrics",
    "agent_loop_diagnostics",
    "agent_loop_trace",
    "llm_call_artifacts",
)

DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS = (
    "agent_feedback_events",
    "agent_feedback_summary",
    "editor_review",
    "quality_result",
    "report_quality_summary",
    *(
        f"{label}_{suffix}"
        for label in AGENT_LOOP_LABELS
        for suffix in DAILY_AGENTIC_ARTIFACT_LOOP_OUTPUT_SUFFIXES
    ),
)

DAILY_REPORT_ARTIFACT_OUTPUT_KEYS = (
    "final_report",
    "report_markdown",
    "blocked_report",
)

DAILY_PUBLIC_OUTPUT_ALIAS_KEYS = (
    "final_report",
    "blocked_report",
    "report_markdown",
    "quality_result",
    "quality_route",
    "citation_check_result",
    "support_matrix",
    "candidate_claims",
    "verified_findings",
    "ranked_items",
    "raw_items",
    "evidence_bundle",
)

DAILY_BOARD_ATTACHMENT_RESULT_KEYS = (
    "board_outputs",
    "cross_board_output",
)


__all__ = [
    "DAILY_AGENT_VALIDATION_OUTPUT_KEYS",
    "DAILY_AGENTIC_ARTIFACT_LOOP_OUTPUT_SUFFIXES",
    "DAILY_AGENTIC_ARTIFACT_OUTPUT_KEYS",
    "DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS",
    "DAILY_BOARD_ATTACHMENT_RESULT_KEYS",
    "DAILY_MEMORY_INGESTION_OUTPUT_KEYS",
    "DAILY_PERSISTENCE_OUTPUT_KEYS",
    "DAILY_PUBLIC_OUTPUT_ALIAS_KEYS",
    "DAILY_REPORT_ARTIFACT_OUTPUT_KEYS",
    "DAILY_RUN_INSPECTION_OUTPUT_KEYS",
    "DAILY_INTERFACE_METADATA_OUTPUT_KEYS",
    "DAILY_EVIDENCE_ARTIFACT_OUTPUT_KEYS",
    "DAILY_QUALITY_ARTIFACT_OUTPUT_KEYS",
    "DAILY_SOURCE_DIAGNOSTIC_ARTIFACT_OUTPUT_KEYS",
    "DAILY_SOURCE_RECOLLECTION_ARTIFACT_OUTPUT_KEYS",
    "DailyOutputProjectionReadPolicy",
    "apply_daily_board_attachment_result",
    "apply_daily_public_output_aliases",
    "daily_output_contains",
    "daily_output_value",
    "ensure_legacy_daily_output_aliases",
    "project_daily_output_for_agent_validation",
    "project_daily_output_for_agentic_artifacts",
    "project_daily_output_for_board_attachment",
    "project_daily_output_for_evidence_artifacts",
    "project_daily_output_for_interface_metadata",
    "project_daily_output_for_memory_ingestion",
    "project_daily_output_for_persistence",
    "project_daily_output_for_legacy_consumers",
    "project_daily_output_for_quality_artifacts",
    "project_daily_output_for_report_artifacts",
    "project_daily_output_for_run_inspection",
    "project_daily_output_for_source_diagnostic_artifacts",
    "project_daily_output_for_source_recollection_artifacts",
]
