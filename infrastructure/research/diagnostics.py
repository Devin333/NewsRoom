"""Bounded structured diagnostics for Research persistence adapters."""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import Final


RESEARCH_PERSISTENCE_LOGGER: Final = "newsroom.research.persistence"
RESEARCH_PERSISTENCE_OPERATION_EVENT: Final = "research_persistence_operation_total"
SAFE_DIAGNOSTIC_LABEL: Final = "other"
MISSING_IDENTITY_REF: Final = "none"
_MAX_IDENTITY_BYTES: Final = 4_096
_IDENTITY_KEY: Final = b"newsroom-research-diagnostic-v1"

_ALLOWED_DIMENSION_VALUES: Final = {
    "component": frozenset({"artifact_store", "run_store"}),
    "operation": frozenset(
        {
            "artifact_read",
            "artifact_write",
            "run_get",
            "run_get_latest",
            "run_save",
        }
    ),
    "outcome": frozenset({"failed", "not_found", "succeeded"}),
    "reason": frozenset(
        {
            "atomic_commit_failed",
            "checksum_invalid",
            "completed",
            "content_invalid",
            "filesystem_unavailable",
            "identity_conflict",
            "identity_mismatch",
            "invalid_configuration",
            "invalid_input",
            "invalid_record",
            "lock_unavailable",
            "metadata_invalid",
            "not_found",
            "record_too_large",
            "run_binding_invalid",
            "schema_invalid",
            "schema_unsupported",
            "serialization_failed",
            "write_conflict",
        }
    ),
}
_LOGGER = logging.getLogger(RESEARCH_PERSISTENCE_LOGGER)


def emit_research_persistence_diagnostic(
    *,
    component: object,
    operation: object,
    outcome: object,
    reason: object,
    run_id: object = None,
    paper_id: object = None,
) -> None:
    """Emit one event containing only fixed labels and hashed identities."""

    normalized_outcome = _normalize_label("outcome", outcome)
    level = (
        logging.INFO
        if normalized_outcome in {"succeeded", "not_found"}
        else logging.WARNING
    )
    dimensions = {
        "component": _normalize_label("component", component),
        "operation": _normalize_label("operation", operation),
        "outcome": normalized_outcome,
        "reason": _normalize_label("reason", reason),
        "run_identity": _identity_ref(run_id, namespace="run"),
        "paper_identity": _identity_ref(paper_id, namespace="paper"),
    }
    try:
        _LOGGER.log(
            level,
            RESEARCH_PERSISTENCE_OPERATION_EVENT,
            extra={
                "research_event_name": RESEARCH_PERSISTENCE_OPERATION_EVENT,
                "research_event_dimensions": dimensions,
            },
            exc_info=None,
            stack_info=False,
        )
    except Exception:
        # Observability must never replace an adapter's storage outcome.
        return


def _normalize_label(name: str, value: object) -> str:
    if isinstance(value, str) and value in _ALLOWED_DIMENSION_VALUES[name]:
        return value
    return SAFE_DIAGNOSTIC_LABEL


def _identity_ref(value: object, *, namespace: str) -> str:
    if not isinstance(value, str) or not value:
        return MISSING_IDENTITY_REF
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return MISSING_IDENTITY_REF
    if len(encoded) > _MAX_IDENTITY_BYTES:
        return SAFE_DIAGNOSTIC_LABEL
    digest = sha256()
    digest.update(_IDENTITY_KEY)
    digest.update(b"\0")
    digest.update(namespace.encode("ascii"))
    digest.update(b"\0")
    digest.update(encoded)
    return f"redacted:sha256:{digest.hexdigest()}"


__all__ = [
    "MISSING_IDENTITY_REF",
    "RESEARCH_PERSISTENCE_LOGGER",
    "RESEARCH_PERSISTENCE_OPERATION_EVENT",
    "SAFE_DIAGNOSTIC_LABEL",
    "emit_research_persistence_diagnostic",
]
