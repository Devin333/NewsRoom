from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    SOURCE_ERROR_RUNTIME_METADATA_KEY,
)


@dataclass(frozen=True)
class SourceErrorMetadataInput:
    phase: str
    retryable: bool
    source_health_affecting: bool
    workflow_blocking: bool
    operator_action_required: bool = False
    request_id: str | None = None
    source_item_id: str | None = None
    original_exception_type: str | None = None
    extra: dict[str, Any] | None = None


def source_error_metadata(input: SourceErrorMetadataInput) -> dict[str, Any]:
    runtime_metadata = {
        "phase": input.phase,
        "retryable": input.retryable,
        "source_health_affecting": input.source_health_affecting,
        "request_id": input.request_id,
    }
    policy_metadata = {
        "source_health_affecting": input.source_health_affecting,
        "workflow_blocking": input.workflow_blocking,
        "operator_action_required": input.operator_action_required,
    }
    legacy_metadata = {
        "phase": input.phase,
        "source_item_id": input.source_item_id,
        "retryable": input.retryable,
        "source_health_affecting": input.source_health_affecting,
        "workflow_blocking": input.workflow_blocking,
        "operator_action_required": input.operator_action_required,
        "original_exception_type": input.original_exception_type,
        **dict(input.extra or {}),
    }
    return _compact_metadata(
        {
            **legacy_metadata,
            SOURCE_ERROR_RUNTIME_METADATA_KEY: _compact_metadata(runtime_metadata),
            SOURCE_ERROR_POLICY_METADATA_KEY: _compact_metadata(policy_metadata),
        }
    )


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}


__all__ = ["SourceErrorMetadataInput", "source_error_metadata"]
