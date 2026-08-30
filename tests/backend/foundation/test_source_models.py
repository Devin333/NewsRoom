from datetime import UTC, datetime

import pytest

from backend.foundation.models.source import (
    DedupResult,
    DuplicateGroup,
    Lineage,
    NormalizedSourceItem,
    SourceDefinition,
    SourceDuplicateCluster,
    SourceError,
    SourceFetchRequest,
    SourceFetchPolicy,
    SourceFetchResult,
    SourcePipelineEvent,
    SourcePipelineMetrics,
    SourceRankingSignals,
    RawSourceItem,
    SourceReliability,
    SourceHealth,
    SourceType,
)
from backend.foundation.models.source_error_normalization import normalize_source_errors


def test_source_definition_normalizes_enums() -> None:
    source = SourceDefinition(
        source_id="openai",
        name="OpenAI",
        source_type="official_blog",
        url="https://example.com/feed.xml",
        reliability="high",
    )

    assert source.source_type == SourceType.OFFICIAL_BLOG
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
        max_redirects=2,
        limit=5,
        connector_name="FeedConnector",
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
    assert request.to_dict()["max_redirects"] == 2
    assert request.to_dict()["connector_name"] == "FeedConnector"
    assert result.to_dict()["request_id"] == "fetch-1"
    assert result.to_dict()["success"] is False
    assert result.to_dict()["skip_reason"] == "robots"


def test_source_fetch_request_validates_fetch_policy_bounds() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        SourceFetchRequest(
            request_id="fetch-1",
            source_id="source-1",
            source_type="rss",
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="max_bytes"):
        SourceFetchRequest(
            request_id="fetch-1",
            source_id="source-1",
            source_type="rss",
            max_bytes=0,
        )
    with pytest.raises(ValueError, match="max_redirects"):
        SourceFetchRequest(
            request_id="fetch-1",
            source_id="source-1",
            source_type="rss",
            max_redirects=-1,
        )


def test_source_fetch_policy_normalizes_allowed_domains() -> None:
    policy = SourceFetchPolicy(allowed_domains=["Example.com", ".openai.com", "example.com"])

    assert policy.allowed_domains == ("example.com", "openai.com")
    assert policy.to_dict()["allowed_domains"] == ["example.com", "openai.com"]


def test_source_fetch_policy_rejects_url_shaped_allowed_domains() -> None:
    with pytest.raises(ValueError, match="domain names"):
        SourceFetchPolicy(allowed_domains=["https://example.com"])


def test_raw_source_item_serializes_artifact_refs() -> None:
    raw = RawSourceItem(
        source_item_id="raw-1",
        source_id="source-1",
        source_name="Source 1",
        source_type="rss",
        title="Source title",
        url="https://example.com/item",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        raw_artifact_ref={"artifact_id": "raw-artifact"},
        parse_artifact_ref={"artifact_id": "parse-artifact"},
    )

    payload = raw.to_dict()

    assert payload["source_type"] == "rss"
    assert payload["raw_artifact_ref"] == {"artifact_id": "raw-artifact"}
    assert payload["parse_artifact_ref"] == {"artifact_id": "parse-artifact"}
    assert payload["lineage"]["source_item_id"] == "raw-1"
    assert payload["lineage"]["raw_url"] == "https://example.com/item"


def test_lineage_round_trips_target_state_payload() -> None:
    lineage = Lineage(
        source_id="source-1",
        source_item_id="raw-1",
        normalized_item_id="norm-1",
        ranked_item_id="rank-1",
        raw_url="https://example.com/raw",
        canonical_url="https://example.com/raw",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        raw_artifact_ref={"artifact_id": "raw"},
    )

    payload = lineage.to_dict()
    restored = Lineage.from_dict(payload)

    assert payload["fetched_at"] == "2026-05-11T00:00:00Z"
    assert restored.source_id == "source-1"
    assert restored.raw_artifact_ref == {"artifact_id": "raw"}


def test_normalized_source_item_projects_legacy_metadata_into_ranking_signals() -> None:
    item = NormalizedSourceItem(
        normalized_item_id="norm-1",
        source_item_id="raw-1",
        source_id="source-1",
        title="AI Chips",
        normalized_title="ai chips",
        url="https://example.com/chips",
        canonical_url="https://example.com/chips",
        canonical_url_hash="hash-url",
        title_hash="hash-title",
        content_hash="hash-content",
        source_reliability="high",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        metadata={
            "source_authority_score": 1.2,
            "duplicate_cluster": {
                "cluster_id": "dup-1",
                "cluster_size": 3,
                "duplicate_item_ids": ["norm-2", "norm-3"],
                "same_event_cluster": True,
            },
            "historical_accuracy_score": 0.7,
            "source_tags": ["AI", "Chips"],
        },
    )

    assert item.ranking_signals.authority_score == 1.0
    assert item.ranking_signals.duplicate_cluster.cluster_size == 3
    assert item.ranking_signals.duplicate_cluster.same_event_cluster is True
    assert item.ranking_signals.historical_importance_score == 0.7
    assert item.ranking_signals.tags == ["ai", "chips"]


def test_source_ranking_signals_updates_duplicate_cluster_without_losing_inputs() -> None:
    signals = SourceRankingSignals(authority_score=0.8, historical_importance_score=0.6, tags=["Policy"])
    updated = signals.with_duplicate_cluster(
        SourceDuplicateCluster(
            cluster_id="dup-policy",
            cluster_size=2,
            duplicate_item_ids=["norm-2"],
            same_event_cluster=True,
        )
    )

    assert updated.authority_score == 0.8
    assert updated.historical_importance_score == 0.6
    assert updated.tags == ["policy"]
    assert updated.duplicate_cluster.to_dict()["cluster_size"] == 2


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


def test_normalize_source_errors_round_trips_serialized_source_errors() -> None:
    original = SourceError(
        source_id="rss-source",
        source_name="RSS Source",
        error_type="fetch_timeout",
        error_message="timed out",
        url="https://example.com/feed.xml",
        retryable=True,
        request_ref={"artifact_id": "request-ref"},
        response_ref={"artifact_id": "response-ref"},
        metadata={"source_health_affecting": True, "workflow_blocking": False},
    )

    restored = normalize_source_errors([original.to_dict()])[0]

    assert restored.source_id == "rss-source"
    assert restored.source_name == "RSS Source"
    assert restored.error_type == "fetch_timeout"
    assert restored.error_message == "timed out"
    assert restored.url == "https://example.com/feed.xml"
    assert restored.retryable is True
    assert restored.request_ref == {"artifact_id": "request-ref"}
    assert restored.response_ref == {"artifact_id": "response-ref"}
    assert restored.metadata["source_health_affecting"] is True
    assert restored.metadata["workflow_blocking"] is False


def test_normalize_source_errors_rejects_non_sequence_payload() -> None:
    with pytest.raises(TypeError, match="source_errors must be a sequence"):
        normalize_source_errors({"source_id": "rss-source"})

    with pytest.raises(TypeError, match="source_errors must be a sequence"):
        normalize_source_errors("fetch_timeout")

    with pytest.raises(TypeError, match="source_errors must be a sequence"):
        normalize_source_errors(b"fetch_timeout")

    with pytest.raises(TypeError, match="source_errors entries must be SourceError"):
        normalize_source_errors(["not-an-error"])


def test_source_health_serializes_window_metrics() -> None:
    health = SourceHealth(
        source_id="rss-source",
        status="healthy",
        consecutive_failures=0,
        success_count_24h=3,
        failure_count_24h=1,
        avg_latency_ms_24h=42.5,
        last_error=SourceError(
            source_id="rss-source",
            error_type="fetch_timeout",
            error_message="timed out",
        ),
        metadata={"owner": "source-pipeline"},
    )

    payload = health.to_dict()

    assert payload["health_status"] == "healthy"
    assert payload["consecutive_failure_count"] == 0
    assert payload["success_count_24h"] == 3
    assert payload["failure_count_24h"] == 1
    assert payload["avg_latency_ms_24h"] == 42.5
    assert payload["last_error_type"] == "fetch_timeout"
    assert payload["last_error_message"] == "timed out"
    assert payload["metadata"] == {"owner": "source-pipeline"}


def test_dedup_result_serializes_duplicate_groups() -> None:
    group = DuplicateGroup(
        group_id="dup-1",
        kept_item_id="norm-1",
        duplicate_item_ids=["norm-2"],
        reasons=["canonical_url_hash"],
        canonical_urls=["https://example.com/post"],
    )
    result = DedupResult(kept_items=[], duplicate_groups=[group], dropped_items=[])

    payload = result.to_dict()

    assert payload["duplicate_group_count"] == 1
    assert payload["duplicate_groups"][0]["kept_item_id"] == "norm-1"
    assert payload["duplicate_groups"][0]["duplicate_item_ids"] == ["norm-2"]


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
    metrics.record_source_seen("rss", "high")
    metrics.record_source_fetched(
        source_id="rss-source",
        source_type="rss",
        reliability="high",
        item_count=2,
    )
    metrics.record_source_failed("html")
    metrics.record_source_skipped("github")

    assert metrics.avg_fetch_latency_ms == 15.0
    payload = metrics.to_dict()
    assert payload["avg_fetch_latency_ms"] == 15.0
    assert payload["sources_by_type"] == {"rss": 1}
    assert payload["sources_by_reliability"] == {"high": 1}
    assert payload["fetched_by_type"] == {"rss": 1}
    assert payload["failed_by_type"] == {"html": 1}
    assert payload["skipped_by_type"] == {"github": 1}
    assert payload["items_by_source"] == {"rss-source": 2}
    assert payload["items_by_source_type"] == {"rss": 2}
    assert payload["items_by_reliability"] == {"high": 2}
