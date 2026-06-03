from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from enum import Enum
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    DAILY_BUFFER_ALIASES,
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
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


def project_daily_output_for_board_attachment(output: Mapping[str, Any]) -> dict[str, Any]:
    return _project_daily_output_for_keys(
        output,
        DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS,
        include_original=False,
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
    )


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
        read_policy=DailyOutputProjectionReadPolicy.NAMESPACED_WITH_LEGACY_FALLBACK,
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
    namespaced_key = DAILY_BUFFER_ALIASES.get(key)
    if namespaced_key is not None:
        if read_policy == DailyOutputProjectionReadPolicy.NAMESPACED_ONLY:
            return [namespaced_key]
        return [namespaced_key, key]

    legacy_key = _DAILY_OUTPUT_LEGACY_ALIASES.get(key)
    if legacy_key is not None:
        if read_policy == DailyOutputProjectionReadPolicy.NAMESPACED_ONLY:
            return [key]
        return [key, legacy_key]
    return [key]


def _legacy_projection_keys(keys: Iterable[str] | None) -> list[str]:
    if keys is None:
        return list(DAILY_BUFFER_ALIASES)

    result: list[str] = []
    for key in keys:
        legacy_key = key if key in DAILY_BUFFER_ALIASES else _DAILY_OUTPUT_LEGACY_ALIASES.get(key)
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
    if key in DAILY_BUFFER_ALIASES:
        return key
    return _DAILY_OUTPUT_LEGACY_ALIASES.get(key, key)


_DAILY_OUTPUT_LEGACY_ALIASES = {
    namespaced_key: legacy_key
    for legacy_key, namespaced_key in DAILY_BUFFER_ALIASES.items()
}

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

DAILY_BOARD_ATTACHMENT_RESULT_KEYS = (
    "board_outputs",
    "cross_board_output",
)


__all__ = [
    "DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS",
    "DAILY_BOARD_ATTACHMENT_RESULT_KEYS",
    "DAILY_MEMORY_INGESTION_OUTPUT_KEYS",
    "DAILY_PERSISTENCE_OUTPUT_KEYS",
    "DAILY_RUN_INSPECTION_OUTPUT_KEYS",
    "DailyOutputProjectionReadPolicy",
    "daily_output_contains",
    "daily_output_value",
    "ensure_legacy_daily_output_aliases",
    "project_daily_output_for_board_attachment",
    "project_daily_output_for_memory_ingestion",
    "project_daily_output_for_persistence",
    "project_daily_output_for_legacy_consumers",
    "project_daily_output_for_run_inspection",
]
