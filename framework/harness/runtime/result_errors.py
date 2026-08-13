from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError


class GraphArtifactResultErrorCode(StrEnum):
    RESULT_SCHEMA_INVALID = "result_schema_invalid"
    RESULT_TOO_LARGE = "result_too_large"
    ARTIFACT_QUOTA_EXCEEDED = "artifact_quota_exceeded"
    ARTIFACT_WRITE_FAILED = "artifact_write_failed"
    ARTIFACT_READBACK_FAILED = "artifact_readback_failed"
    ARTIFACT_SCOPE_MISMATCH = "artifact_scope_mismatch"
    ARTIFACT_CATALOG_CORRUPT = "artifact_catalog_corrupt"
    ARTIFACT_CATALOG_NOT_FOUND = "artifact_catalog_not_found"
    ARTIFACT_REFERENCE_CONFLICT = "artifact_reference_conflict"
    CACHE_IDENTITY_INVALID = "cache_identity_invalid"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    SENSITIVE_PAYLOAD_REJECTED = "sensitive_payload_rejected"
    POLICY_VERSION_UNSUPPORTED = "policy_version_unsupported"
    RESULT_IDENTITY_CONFLICT = "result_identity_conflict"


_MESSAGES: Mapping[GraphArtifactResultErrorCode, str] = {
    GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID: (
        "graph artifact result does not satisfy its contract"
    ),
    GraphArtifactResultErrorCode.RESULT_TOO_LARGE: (
        "graph artifact result exceeds a configured size limit"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_QUOTA_EXCEEDED: (
        "graph artifact result exceeds a configured quota"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_WRITE_FAILED: (
        "graph artifact result could not be written"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED: (
        "graph artifact result could not be verified after writing"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH: (
        "graph artifact result reference is outside the authorized scope"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT: (
        "graph artifact catalog state failed integrity validation"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_CATALOG_NOT_FOUND: (
        "graph artifact catalog record was not found"
    ),
    GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT: (
        "graph artifact catalog reference conflicts with committed ownership"
    ),
    GraphArtifactResultErrorCode.CACHE_IDENTITY_INVALID: (
        "graph artifact cache identity is invalid"
    ),
    GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED: (
        "graph artifact context request exceeds its approved budget"
    ),
    GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED: (
        "graph artifact result contains content that cannot be persisted"
    ),
    GraphArtifactResultErrorCode.POLICY_VERSION_UNSUPPORTED: (
        "graph artifact persistence policy version is not readable"
    ),
    GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT: (
        "graph artifact result identity was already committed with different content"
    ),
}

_RETRYABLE = frozenset(
    {
        GraphArtifactResultErrorCode.ARTIFACT_WRITE_FAILED,
        GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
        GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
    }
)
_DETAIL_KEYS = frozenset(
    {
        "actual",
        "artifact_class",
        "attempt",
        "available",
        "consumed",
        "field",
        "limit",
        "max_depth",
        "max_keys",
        "mode",
        "model",
        "policy_version",
        "reason",
        "required",
        "reserved",
    }
)
_SAFE_DETAIL_TEXT = re.compile(r"[A-Za-z0-9_.:@+-]{1,128}\Z")


class GraphArtifactResultError(HarnessValidationError):
    """Stable, sanitized failure contract for result materialization events."""

    def __init__(
        self,
        error_code: GraphArtifactResultErrorCode | str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        try:
            normalized_code = GraphArtifactResultErrorCode(error_code)
        except (TypeError, ValueError) as exc:
            normalized_code = GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID
            details = {"field": "error_code"}
            retryable = False
            cause = exc
        else:
            cause = None
        public_details = _sanitize_details(details or {})
        actual_retryable = (
            normalized_code in _RETRYABLE if retryable is None else retryable
        )
        if not isinstance(actual_retryable, bool):
            normalized_code = GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID
            public_details = {"field": "retryable"}
            actual_retryable = False
        self.error_code = normalized_code
        self.retryable = actual_retryable
        super().__init__(
            _MESSAGES[normalized_code],
            code=normalized_code.value,
            details=public_details,
        )
        if cause is not None:
            self.__cause__ = cause

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "code": self.error_code.value,
            "message": _MESSAGES[self.error_code],
            "retryable": self.retryable,
            "details": dict(self.details),
        }


def result_error(
    error_code: GraphArtifactResultErrorCode,
    **details: Any,
) -> GraphArtifactResultError:
    return GraphArtifactResultError(error_code, details=details)


def _sanitize_details(details: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for raw_key, value in details.items():
        key = str(raw_key)
        if key not in _DETAIL_KEYS:
            continue
        if value is None or isinstance(value, bool):
            sanitized[key] = value
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            sanitized[key] = value
            continue
        if isinstance(value, float):
            sanitized[key] = value
            continue
        if isinstance(value, StrEnum):
            value = value.value
        if isinstance(value, str) and _SAFE_DETAIL_TEXT.fullmatch(value):
            sanitized[key] = value
    return dict(sorted(sanitized.items()))


__all__ = [
    "GraphArtifactResultError",
    "GraphArtifactResultErrorCode",
    "result_error",
]
