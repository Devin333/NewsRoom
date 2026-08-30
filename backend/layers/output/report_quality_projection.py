from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


REPORT_QUALITY_PAYLOAD_KEYS = (
    "quality_trace",
    "quality",
    "quality_gate",
    "editor_review",
    "quality_metrics",
)
QUALITY_RECORD_PAYLOAD_KEYS = (
    "quality_trace",
    "quality_result",
    "quality_summary",
    "editor_review",
    "quality",
    "quality_gate",
    "quality_metrics",
)
QUALITY_RECORD_SCALAR_KEYS = (
    "decision",
    "passed",
    "quality_score",
    "citation_coverage_score",
    "claim_support_score",
    "evidence_alignment_score",
)


def project_report_quality_payload(
    report_json: Any,
    *,
    quality_records: Iterable[Any] = (),
) -> dict[str, Any]:
    report_quality = _first_mapping_value(_mapping(report_json), REPORT_QUALITY_PAYLOAD_KEYS)
    if report_quality:
        return report_quality

    for record in normalize_quality_result_records(quality_records):
        quality = project_quality_result_record_payload(record)
        if quality:
            return quality
    return {}


def normalize_quality_result_records(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    result: list[dict[str, Any]] = []
    for record in records:
        payload = _mapping(record.to_dict() if hasattr(record, "to_dict") else record)
        if payload:
            result.append(payload)
    return result


def project_quality_result_record_payload(record: Any) -> dict[str, Any]:
    payload = _mapping(record)
    if not payload:
        return {}

    nested_payload = _mapping(payload.get("payload"))
    quality = _first_mapping_value(nested_payload, QUALITY_RECORD_PAYLOAD_KEYS)
    if not quality:
        quality = {}

    projected = dict(quality)
    for key in QUALITY_RECORD_SCALAR_KEYS:
        if key in payload and key not in projected:
            projected[key] = payload[key]
    return projected


def _first_mapping_value(payload: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "normalize_quality_result_records",
    "project_quality_result_record_payload",
    "project_report_quality_payload",
]
