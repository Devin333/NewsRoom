from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from business.foundation.models.source import SourceError, SourceErrorPolicyReport
from business.foundation.models.source_error_normalization import normalize_source_errors


SOURCE_ERROR_POLICY_METADATA_KEY = "source_error_policy"


def build_source_error_policy_report(source_errors: Iterable[Any]) -> SourceErrorPolicyReport:
    normalized_source_errors = normalize_source_errors(
        source_errors,
        context="source error policy errors",
    )
    rows: list[dict[str, Any]] = []
    errors_by_type: dict[str, int] = {}

    for error in normalized_source_errors:
        policy_input = SourceErrorPolicyInput.from_error(error)
        errors_by_type[policy_input.error_type] = errors_by_type.get(policy_input.error_type, 0) + 1
        rows.append(
            {
                "source_id": policy_input.source_id,
                "source_name": policy_input.source_name,
                "error_type": policy_input.error_type,
                "retryable": policy_input.retryable,
                "source_health_affecting": policy_input.source_health_affecting,
                "workflow_blocking": policy_input.workflow_blocking,
                "operator_action_required": policy_input.operator_action_required,
            }
        )

    return SourceErrorPolicyReport(
        total_error_count=len(rows),
        retryable_error_count=sum(1 for row in rows if row["retryable"]),
        non_retryable_error_count=sum(1 for row in rows if not row["retryable"]),
        health_affecting_error_count=sum(1 for row in rows if row["source_health_affecting"]),
        workflow_blocking_error_count=sum(1 for row in rows if row["workflow_blocking"]),
        operator_action_required_count=sum(1 for row in rows if row["operator_action_required"]),
        errors_by_type=errors_by_type,
        rows=rows,
    )


@dataclass(frozen=True)
class SourceErrorPolicyInput:
    source_id: str
    source_name: str | None
    error_type: str
    retryable: bool
    source_health_affecting: bool
    workflow_blocking: bool
    operator_action_required: bool

    @classmethod
    def from_error(cls, error: SourceError) -> "SourceErrorPolicyInput":
        metadata = _SourceErrorPolicyMetadataView.from_metadata(error.metadata)
        return cls(
            source_id=error.source_id,
            source_name=error.source_name,
            error_type=error.error_type or "unknown",
            retryable=_bool_value(error.retryable, default=True),
            source_health_affecting=metadata.source_health_affecting,
            workflow_blocking=metadata.workflow_blocking,
            operator_action_required=metadata.operator_action_required,
        )


@dataclass(frozen=True)
class _SourceErrorPolicyMetadataView:
    formal: dict[str, Any]
    legacy: dict[str, Any]

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "_SourceErrorPolicyMetadataView":
        legacy = _metadata_dict(metadata)
        return cls(
            formal=_metadata_dict(legacy.get(SOURCE_ERROR_POLICY_METADATA_KEY)),
            legacy=legacy,
        )

    @property
    def source_health_affecting(self) -> bool:
        return _bool_value(self._present("source_health_affecting", default=True), default=True)

    @property
    def workflow_blocking(self) -> bool:
        return _bool_value(self._present("workflow_blocking", default=False), default=False)

    @property
    def operator_action_required(self) -> bool:
        return _bool_value(self._present("operator_action_required", default=False), default=False)

    def _present(self, key: str, *, default: Any) -> Any:
        if key in self.formal:
            return self.formal[key]
        if key in self.legacy:
            return self.legacy[key]
        return default


def _metadata_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
