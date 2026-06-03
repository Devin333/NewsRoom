from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    DAILY_BUFFER_ALIASES,
)


def daily_output_value(
    output: Mapping[str, Any],
    key: str,
    *,
    default: Any = None,
) -> Any:
    for candidate_key in _output_key_candidates(key):
        if candidate_key in output:
            return output[candidate_key]
    return default


def daily_output_contains(output: Mapping[str, Any], key: str) -> bool:
    return any(candidate_key in output for candidate_key in _output_key_candidates(key))


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
    return project_daily_output_for_legacy_consumers(
        output,
        keys=DAILY_PERSISTENCE_OUTPUT_KEYS,
    )


def project_daily_output_for_board_attachment(output: Mapping[str, Any]) -> dict[str, Any]:
    return project_daily_output_for_legacy_consumers(
        output,
        keys=DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS,
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


def _output_key_candidates(key: str) -> list[str]:
    namespaced_key = DAILY_BUFFER_ALIASES.get(key)
    if namespaced_key is not None:
        return [namespaced_key, key]

    legacy_key = _DAILY_OUTPUT_LEGACY_ALIASES.get(key)
    if legacy_key is not None:
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

DAILY_BOARD_ATTACHMENT_RESULT_KEYS = (
    "board_outputs",
    "cross_board_output",
)


__all__ = [
    "DAILY_BOARD_ATTACHMENT_OUTPUT_KEYS",
    "DAILY_BOARD_ATTACHMENT_RESULT_KEYS",
    "DAILY_PERSISTENCE_OUTPUT_KEYS",
    "daily_output_contains",
    "daily_output_value",
    "ensure_legacy_daily_output_aliases",
    "project_daily_output_for_board_attachment",
    "project_daily_output_for_persistence",
    "project_daily_output_for_legacy_consumers",
]
