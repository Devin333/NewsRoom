from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    SourceErrorRuntimeMetadata,
    SourceFetchResultMetadata,
    error_metadata_bool,
    error_phase,
    skipped_source_fetch_result,
    source_fetch_result,
)
from business.foundation.models.source import SourceDefinition, SourceError, SourceType


def test_source_fetch_result_metadata_keeps_compatibility_fields() -> None:
    result = source_fetch_result(
        _source(),
        request_id="fetch-1",
        success=True,
        latency_ms=12,
        items=[],
        errors=[],
    )

    metadata = result.metadata
    formal = metadata["source_fetch_result_metadata"]
    assert formal["schema_version"] == "business.cross_board.daily_source_fetch.metadata.v1"
    assert metadata["source_type"] == SourceType.RSS.value
    assert metadata["item_count"] == 0
    assert metadata["error_count"] == 0


def test_skipped_source_fetch_result_syncs_formal_skip_metadata() -> None:
    result = skipped_source_fetch_result(
        _source(),
        request_id="fetch-skip",
        skip_reason="cooldown",
        metadata={"reason": "cooldown", "until": None},
    )

    metadata = result.metadata
    assert metadata["skip"] == {"reason": "cooldown"}
    assert metadata["source_fetch_result_metadata"]["skip"] == {"reason": "cooldown"}


def test_source_fetch_result_metadata_can_restore_from_legacy_metadata() -> None:
    payload = SourceFetchResultMetadata.from_result_metadata(
        {
            "source_type": "rss",
            "url": "https://example.com/feed.xml",
            "item_count": 2,
            "error_count": 1,
            "skip": {"reason": "disabled"},
        }
    )

    assert payload.schema_version == "business.cross_board.daily_source_fetch.metadata.v1"
    assert payload.item_count == 2
    assert payload.skip == {"reason": "disabled"}


def test_source_fetch_result_metadata_prefers_formal_zero_counts() -> None:
    payload = SourceFetchResultMetadata.from_result_metadata(
        {
            "item_count": 4,
            "error_count": 3,
            "source_fetch_result_metadata": {
                "source_type": "rss",
                "item_count": 0,
                "error_count": 0,
            },
        }
    )

    assert payload.item_count == 0
    assert payload.error_count == 0


def test_source_error_runtime_metadata_projects_legacy_error_metadata() -> None:
    error = SourceError(
        source_id="source-1",
        error_type="parse_error",
        error_message="Could not parse feed.",
        metadata={
            "retryable": False,
            "source_health_affecting": False,
            "phase": "parse",
            "request_id": "fetch-1",
        },
    )

    runtime_metadata = SourceErrorRuntimeMetadata.from_error(error)

    assert runtime_metadata.retryable is False
    assert runtime_metadata.source_health_affecting is False
    assert runtime_metadata.phase == "parse"
    assert runtime_metadata.request_id == "fetch-1"
    assert error_metadata_bool(error, "retryable", default=True) is False
    assert error_metadata_bool(error, "source_health_affecting", default=True) is False
    assert error_phase(error) == "parse"


def test_source_error_runtime_metadata_uses_retryable_metadata_when_formal_value_missing() -> None:
    error = SourceError(
        source_id="source-1",
        error_type="fetch_timeout",
        error_message="Timed out.",
        retryable=None,
        metadata={"retryable": False},
    )

    runtime_metadata = SourceErrorRuntimeMetadata.from_error(error)

    assert runtime_metadata.retryable is False
    assert error_metadata_bool(error, "retryable", default=True) is False


def test_source_error_metadata_bool_ignores_unknown_metadata_keys() -> None:
    error = SourceError(
        source_id="source-1",
        error_type="fetch_timeout",
        error_message="Timed out.",
        metadata={"unknown_policy_flag": False},
    )

    assert error_metadata_bool(error, "unknown_policy_flag", default=True) is True


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="source-1",
        name="Source",
        source_type=SourceType.RSS,
        url="https://example.com/feed.xml",
    )
