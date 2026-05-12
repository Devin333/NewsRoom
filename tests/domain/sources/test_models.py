from datetime import UTC, datetime

import pytest

from domain.sources import (
    SourceDefinition,
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


def test_source_definition_requires_url() -> None:
    with pytest.raises(ValueError, match="url"):
        SourceDefinition(source_id="bad", name="Bad", source_type="rss", url="")


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
