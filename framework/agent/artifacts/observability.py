"""Safe structured observability for artifact integrity boundaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final


ARTIFACT_OBSERVABILITY_LOGGER: Final = "newsroom.artifacts.integrity"
SAFE_FALLBACK_LABEL: Final = "other"

ARTIFACT_PATH_REJECTED_EVENT: Final = "artifact_path_rejected_total"
ARTIFACT_RESERVED_METADATA_REJECTED_EVENT: Final = (
    "artifact_reserved_metadata_rejected_total"
)
ARTIFACT_CHECKSUM_MISMATCH_EVENT: Final = "artifact_checksum_mismatch_total"
ARTIFACT_METADATA_CORRUPT_EVENT: Final = "artifact_metadata_corrupt_total"
ARTIFACT_CHECKSUM_MISSING_EVENT: Final = "artifact_checksum_missing_total"
ARTIFACT_INTEGRITY_INSPECTION_EVENT: Final = "artifact_integrity_inspection_total"


@dataclass(frozen=True)
class _EventSpec:
    level: int
    dimensions: tuple[str, ...]


_EVENT_SPECS: Final = {
    ARTIFACT_PATH_REJECTED_EVENT: _EventSpec(
        logging.WARNING,
        ("field", "operation"),
    ),
    ARTIFACT_RESERVED_METADATA_REJECTED_EVENT: _EventSpec(
        logging.WARNING,
        ("key", "publisher"),
    ),
    ARTIFACT_CHECKSUM_MISMATCH_EVENT: _EventSpec(
        logging.WARNING,
        ("store", "operation"),
    ),
    ARTIFACT_METADATA_CORRUPT_EVENT: _EventSpec(
        logging.WARNING,
        ("store",),
    ),
    ARTIFACT_CHECKSUM_MISSING_EVENT: _EventSpec(
        logging.WARNING,
        ("store",),
    ),
    ARTIFACT_INTEGRITY_INSPECTION_EVENT: _EventSpec(
        logging.WARNING,
        ("result",),
    ),
}

_FIELD_ALIASES: Final = {
    "artifact name": "artifact_name",
    "artifact path": "artifact_path",
    "artifact path prefix": "artifact_path",
    "artifact uri": "artifact_uri",
    "artifact list path": "artifact_path",
    "artifact metadata path": "artifact_metadata_path",
    "artifact metadata root": "artifact_metadata_root",
    "artifact_id": "artifact_id",
    "artifact_list_path": "artifact_path",
    "artifact_metadata_path": "artifact_metadata_path",
    "artifact_metadata_root": "artifact_metadata_root",
    "artifact_name": "artifact_name",
    "artifact_path": "artifact_path",
    "artifact_uri": "artifact_uri",
    "checkpoint_path": "checkpoint_path",
    "checkpoint path": "checkpoint_path",
    "indexed artifact path": "index_path",
    "index_path": "index_path",
    "manifest artifact path": "manifest_path",
    "manifest_artifact_path": "manifest_path",
    "manifest_path": "manifest_path",
    "run_id": "run_id",
    "step_id": "step_id",
}

_ALLOWED_DIMENSION_VALUES: Final = {
    "field": frozenset(
        {
            "artifact_id",
            "artifact_metadata_path",
            "artifact_metadata_root",
            "artifact_name",
            "artifact_path",
            "artifact_uri",
            "checkpoint_path",
            "index_path",
            "manifest_path",
            "run_id",
            "step_id",
            SAFE_FALLBACK_LABEL,
        }
    ),
    "operation": frozenset(
        {
            "inspect",
            "list",
            "publish",
            "read",
            "resolve_descendant",
            "strict_read",
            "validate_relative",
            "validate_segment",
            "verify",
            "write",
            SAFE_FALLBACK_LABEL,
        }
    ),
    "key": frozenset(
        {
            "artifact_id",
            "artifact_key",
            "artifact_type",
            "checksum",
            "content_hash",
            "content_type",
            "created_at",
            "created_by_step_id",
            "key",
            "media_type",
            "path",
            "publisher_id",
            "redacted",
            "relative_path",
            "run_id",
            "size_bytes",
            "status",
            "uri",
            SAFE_FALLBACK_LABEL,
        }
    ),
    "publisher": frozenset(
        {
            "graph",
            "local",
            SAFE_FALLBACK_LABEL,
        }
    ),
    "store": frozenset(
        {
            "artifact_store",
            "filesystem",
            "graph",
            "local",
            "strict_graph",
            SAFE_FALLBACK_LABEL,
        }
    ),
    "result": frozenset(
        {
            "error",
            "invalid",
            "store_unavailable",
            "valid",
            SAFE_FALLBACK_LABEL,
        }
    ),
}

_LOGGER = logging.getLogger(ARTIFACT_OBSERVABILITY_LOGGER)


def emit_artifact_path_rejected(*, field: object, operation: object) -> None:
    _emit(
        ARTIFACT_PATH_REJECTED_EVENT,
        field=_normalize_field(field),
        operation=operation,
    )


def emit_artifact_reserved_metadata_rejected(
    *,
    key: object,
    publisher: object,
) -> None:
    _emit(
        ARTIFACT_RESERVED_METADATA_REJECTED_EVENT,
        key=key,
        publisher=publisher,
    )


def emit_artifact_checksum_mismatch(*, store: object, operation: object) -> None:
    _emit(
        ARTIFACT_CHECKSUM_MISMATCH_EVENT,
        store=store,
        operation=operation,
    )


def emit_artifact_metadata_corrupt(*, store: object) -> None:
    _emit(ARTIFACT_METADATA_CORRUPT_EVENT, store=store)


def emit_artifact_checksum_missing(*, store: object) -> None:
    _emit(ARTIFACT_CHECKSUM_MISSING_EVENT, store=store)


def emit_artifact_integrity_inspection(*, result: object) -> None:
    normalized_result = _normalize_dimension("result", result)
    level = logging.INFO if normalized_result == "valid" else logging.WARNING
    _emit(
        ARTIFACT_INTEGRITY_INSPECTION_EVENT,
        level=level,
        result=normalized_result,
    )


def _emit(event_name: str, *, level: int | None = None, **dimensions: object) -> None:
    spec = _EVENT_SPECS.get(event_name)
    if spec is None:
        raise ValueError("unknown artifact observability event")
    normalized = {
        name: _normalize_dimension(name, dimensions.get(name))
        for name in spec.dimensions
    }
    _LOGGER.log(
        spec.level if level is None else level,
        event_name,
        extra={
            "artifact_event_name": event_name,
            "artifact_event_dimensions": normalized,
        },
        exc_info=None,
        stack_info=False,
    )


def _normalize_field(value: object) -> object:
    if not isinstance(value, str):
        return SAFE_FALLBACK_LABEL
    return _FIELD_ALIASES.get(value, value)


def _normalize_dimension(name: str, value: object) -> str:
    allowed = _ALLOWED_DIMENSION_VALUES[name]
    if isinstance(value, str) and value in allowed:
        return value
    return SAFE_FALLBACK_LABEL


__all__ = [
    "ARTIFACT_CHECKSUM_MISMATCH_EVENT",
    "ARTIFACT_CHECKSUM_MISSING_EVENT",
    "ARTIFACT_INTEGRITY_INSPECTION_EVENT",
    "ARTIFACT_METADATA_CORRUPT_EVENT",
    "ARTIFACT_OBSERVABILITY_LOGGER",
    "ARTIFACT_PATH_REJECTED_EVENT",
    "ARTIFACT_RESERVED_METADATA_REJECTED_EVENT",
    "SAFE_FALLBACK_LABEL",
    "emit_artifact_checksum_mismatch",
    "emit_artifact_checksum_missing",
    "emit_artifact_integrity_inspection",
    "emit_artifact_metadata_corrupt",
    "emit_artifact_path_rejected",
    "emit_artifact_reserved_metadata_rejected",
]
