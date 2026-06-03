from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_error_metadata import (
    SourceErrorMetadataInput,
    source_error_metadata,
)
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    SOURCE_ERROR_RUNTIME_METADATA_KEY,
)
from business.layers.signal.source_processing.error_policy import SOURCE_ERROR_POLICY_METADATA_KEY


def test_source_error_metadata_writes_formal_runtime_and_policy_payloads() -> None:
    metadata = source_error_metadata(
        SourceErrorMetadataInput(
            phase="parse",
            retryable=False,
            source_health_affecting=False,
            workflow_blocking=True,
            operator_action_required=True,
            request_id="fetch-1",
            source_item_id="raw-1",
            original_exception_type="ValueError",
            extra={"registered_connector": True},
        )
    )

    assert metadata[SOURCE_ERROR_RUNTIME_METADATA_KEY] == {
        "phase": "parse",
        "retryable": False,
        "source_health_affecting": False,
        "request_id": "fetch-1",
    }
    assert metadata[SOURCE_ERROR_POLICY_METADATA_KEY] == {
        "source_health_affecting": False,
        "workflow_blocking": True,
        "operator_action_required": True,
    }
    assert metadata["phase"] == "parse"
    assert metadata["retryable"] is False
    assert metadata["source_health_affecting"] is False
    assert metadata["workflow_blocking"] is True
    assert metadata["operator_action_required"] is True
    assert metadata["source_item_id"] == "raw-1"
    assert metadata["original_exception_type"] == "ValueError"
    assert metadata["registered_connector"] is True
