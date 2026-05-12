from datetime import UTC, datetime

import pytest

from domain.sources import (
    SourceDefinition,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourcePipelineEvent,
    SourcePipelineMetrics,
    SourceReliability,
    SourceType,
)


def test_source_definition_normalizes_enums() -> None:
    source = SourceDefinition(
        source_id="openai",
        name="OpenAI",
        source_type="rss",
        url="https://example.com/feed.xml",
        reliability="high",
    )

    assert source.source_type == SourceType.RSS
    assert source.reliability == SourceReliability.HIGH
    assert source.respect_robots is True


def test_source_definition_requires_url() -> None:
    with pytest.raises(ValueError, match="url"):
        SourceDefinition(source_id="bad", name="Bad", source_type="rss", url="")


def test_source_fetch_request_and_result_serialize() -> None:
    request = SourceFetchRequest(
        request_id="fetch-1",
        source_id="source-1",
        source_type="rss",
        url="https://example.com/feed.xml",
        limit=5,
        since=datetime(2026, 5, 11, tzinfo=UTC),
    )
    result = SourceFetchResult(
        request_id=request.request_id,
        source_id=request.source_id,
        success=False,
        latency_ms=12,
        error_type="robots_disallowed",
        error_message="blocked",
        skipped=True,
        skip_reason="robots",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
    )

    assert request.to_dict()["source_type"] == "rss"
    assert request.to_dict()["since"] == "2026-05-11T00:00:00Z"
    assert result.to_dict()["request_id"] == "fetch-1"
    assert result.to_dict()["success"] is False
    assert result.to_dict()["skip_reason"] == "robots"


def test_source_error_exposes_top_level_policy_fields_from_legacy_metadata() -> None:
    error = SourceError(
        source_id="rss-source",
        source_name="RSS Source",
        error_type="unsupported_content_type",
        error_message="unsupported content type",
        url="https://example.com/feed.xml",
        metadata={"retryable": False, "source_health_affecting": False},
    )

    payload = error.to_dict()

    assert error.retryable is False
    assert payload["source_name"] == "RSS Source"
    assert payload["retryable"] is False
    assert payload["request_ref"] is None
    assert payload["response_ref"] is None
    assert payload["metadata"]["retryable"] is False


def test_source_error_defaults_retryable_when_policy_metadata_is_absent() -> None:
    error = SourceError(
        source_id="rss-source",
        error_type="fetch_connection_error",
        error_message="connection failed",
    )

    assert error.retryable is True
    assert error.to_dict()["retryable"] is True


def test_source_pipeline_event_serializes() -> None:
    event = SourcePipelineEvent(
        event_type="source_fetch_succeeded",
        source_id="openai",
        occurred_at=datetime(2026, 5, 11, tzinfo=UTC),
        metadata={"item_count": 2},
    )

    assert event.to_dict() == {
        "event_type": "source_fetch_succeeded",
        "source_id": "openai",
        "occurred_at": "2026-05-11T00:00:00Z",
        "metadata": {"item_count": 2},
    }


def test_source_pipeline_metrics_records_average_fetch_latency() -> None:
    metrics = SourcePipelineMetrics()

    metrics.record_fetch_latency(10)
    metrics.record_fetch_latency(20)

    assert metrics.avg_fetch_latency_ms == 15.0
    assert metrics.to_dict()["avg_fetch_latency_ms"] == 15.0
