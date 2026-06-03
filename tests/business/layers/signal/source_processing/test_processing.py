from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from business.foundation.models.source import (
    RawSourceItem,
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourceHealth,
    SourceHealthStatus,
    SourcePipelineMetrics,
    SourceType,
)
from business.layers.signal.source_processing import (
    build_source_connector_dispatch_report,
    build_source_coverage_report,
    build_source_error_policy_report,
    build_source_fallback_report,
    build_source_freshness_report,
    build_source_governance_report,
    build_source_health_report,
    build_source_quality_summary_report,
    build_source_ranking_scores,
    build_source_traceability_report,
    deduplicate_items,
    deduplicate_with_result,
    detect_language,
    normalize_items,
    rank_items,
    score_source_item,
)
from business.layers.signal.source_processing.fallback import (
    SourceErrorFallbackInput,
    SourceItemFallbackInput,
    SourceSelectionFallbackInput,
)
from business.layers.signal.source_processing.governance import SourceGovernancePolicy
from business.layers.signal.source_processing.normalize import canonicalize_url, normalize_text


def _raw_item(
    title: str,
    url: str,
    *,
    reliability: str = "medium",
    days_old: int = 0,
    authority_score: float = 0.5,
    summary: str | None = None,
    language: str | None = None,
    metadata: dict[str, object] | None = None,
) -> RawSourceItem:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    item_metadata: dict[str, object] = {
        "source_reliability": reliability,
        "source_authority_score": authority_score,
    }
    item_metadata.update(metadata or {})
    return RawSourceItem(
        source_item_id=f"raw-{title}-{url}",
        source_id="source",
        source_name="Source",
        source_type=SourceType.RSS,
        title=title,
        url=url,
        fetched_at=now,
        published_at=now - timedelta(days=days_old),
        summary=summary if summary is not None else f"Summary for {title}",
        language=language,
        metadata=item_metadata,
    )


def test_normalize_text_and_canonical_url() -> None:
    assert normalize_text(" AI   Chips ") == "ai chips"
    assert (
        canonicalize_url("HTTPS://Example.COM/post/?utm_source=x&b=2&a=1#section")
        == "https://example.com/post?a=1&b=2"
    )


def test_build_source_coverage_report_summarizes_partial_outcomes() -> None:
    metrics = SourcePipelineMetrics(
        sources_total=3,
        sources_fetched=1,
        sources_failed=1,
        sources_skipped=1,
        raw_items_count=2,
        normalized_items_count=2,
        deduplicated_items_count=1,
        ranked_items_count=1,
        duplicate_count=1,
        errors_by_type={"fetch_timeout": 1},
        items_by_source={"official": 2},
        sources_by_type={"rss": 2, "github": 1},
        sources_by_reliability={"high": 1, "medium": 2},
        fetched_by_type={"rss": 1},
        failed_by_type={"rss": 1},
        skipped_by_type={"github": 1},
        items_by_source_type={"rss": 2},
        items_by_reliability={"high": 2},
    )
    metrics.avg_fetch_latency_ms = 12.5

    report = build_source_coverage_report(
        metrics,
        source_errors=[
            SourceError(
                source_id="failing",
                error_type="fetch_timeout",
                error_message="timeout",
            )
        ],
        skipped_sources=[{"source_id": "cooling"}],
        failed_sources=[{"source_id": "failing"}, {"source_id": "failing"}],
    )

    assert report.coverage_status == "partial"
    assert report.selected_source_count == 3
    assert report.attempted_source_count == 3
    assert report.fetched_source_count == 1
    assert report.failed_source_count == 1
    assert report.skipped_source_count == 1
    assert report.unattempted_source_count == 0
    assert report.fetch_success_ratio == 0.3333
    assert report.attempted_source_ratio == 1.0
    assert report.item_yield_ratio == 0.6667
    assert report.error_count == 1
    assert report.failed_source_ids == ["failing"]
    assert report.skipped_source_ids == ["cooling"]
    assert report.partial_reasons == ["source_failures", "source_skips", "source_errors"]
    assert report.to_dict()["items_by_reliability"] == {"high": 2}


def test_build_source_coverage_report_marks_no_source_run_empty() -> None:
    metrics = SourcePipelineMetrics(
        sources_total=1,
        sources_failed=1,
        raw_items_count=0,
        errors_by_type={"all_sources_failed": 1},
        sources_by_type={"rss": 1},
    )

    report = build_source_coverage_report(
        metrics,
        source_errors=[
            SourceError(
                source_id="source_pipeline",
                error_type="all_sources_failed",
                error_message="all failed",
            )
        ],
        failed_sources=[{"source_id": "source_pipeline"}],
    )

    assert report.coverage_status == "empty"
    assert report.failed_source_ids == []
    assert report.fetch_success_ratio == 0.0
    assert report.partial_reasons == ["no_raw_items", "source_failures", "source_errors"]


def test_build_source_coverage_report_accepts_serialized_source_errors() -> None:
    report = build_source_coverage_report(
        SourcePipelineMetrics(sources_total=1, sources_failed=1, raw_items_count=0),
        source_errors=[
            {
                "source_id": "feed",
                "error_type": "fetch_timeout",
                "error_message": "timeout",
            }
        ],
    )

    assert report.error_count == 1
    assert "source_errors" in report.partial_reasons


def test_build_source_coverage_report_rejects_unstructured_source_errors() -> None:
    with pytest.raises(TypeError, match="source coverage errors entries must be SourceError"):
        build_source_coverage_report(
            SourcePipelineMetrics(sources_total=1),
            source_errors=["fetch_timeout"],
        )


def test_build_source_connector_dispatch_report_joins_requests_and_results() -> None:
    requests = [
        SourceFetchRequest(
            request_id="req-1",
            source_id="feed",
            source_type="rss",
            connector_name="FeedConnector",
            metadata={"connector_name": "LegacyFeedConnector"},
        ),
        SourceFetchRequest(
            request_id="req-2",
            source_id="html",
            source_type="web_page",
            connector_name="HtmlConnector",
        ),
        SourceFetchRequest(
            request_id="req-3",
            source_id="cooling",
            source_type="rss",
            metadata={"connector_name": "FeedConnector"},
        ),
    ]
    results = [
        SourceFetchResult(request_id="req-1", source_id="feed", success=True),
        SourceFetchResult(
            request_id="req-2",
            source_id="html",
            success=False,
            error_type="fetch_timeout",
        ),
        SourceFetchResult(
            request_id="req-3",
            source_id="cooling",
            success=False,
            skipped=True,
            skip_reason="cooldown",
        ),
    ]

    report = build_source_connector_dispatch_report(requests, results)

    assert report.total_dispatch_count == 3
    assert report.success_count == 1
    assert report.failed_count == 1
    assert report.skipped_count == 1
    assert report.connector_counts == {"FeedConnector": 2, "HtmlConnector": 1}
    assert report.rows[0]["connector_name"] == "FeedConnector"
    assert report.success_by_connector == {"FeedConnector": 1}
    assert report.failed_by_connector == {"HtmlConnector": 1}
    assert report.skipped_by_connector == {"FeedConnector": 1}
    assert report.rows[1]["error_type"] == "fetch_timeout"
    assert report.rows[2]["skip_reason"] == "cooldown"


def test_build_source_fallback_report_summarizes_selection_item_and_error_fallbacks() -> None:
    raw_item = _raw_item(
        "Official fallback",
        "https://example.com/fallback",
        metadata={
            "official_blog_fetch_mode": "html_fallback",
            "official_blog_fallback": {
                "from": "feed",
                "to": "html",
                "feed_error_types": ["fetch_connection_error"],
            },
        },
    )
    error = SourceError(
        source_id="official",
        error_type="parse_error",
        error_message="parse failed",
        retryable=False,
        metadata={"official_blog_fallback_stage": "html"},
    )

    report = build_source_fallback_report(
        raw_items=[raw_item],
        source_errors=[error],
        source_selection_report={
            "fallback_used": True,
            "fallback_reason": "no_topic_match",
            "selected_source_ids": ["official"],
        },
    )

    assert report.total_fallback_count == 3
    assert report.selection_fallback_used is True
    assert report.selection_fallback_reason == "no_topic_match"
    assert report.item_fallback_count == 1
    assert report.error_fallback_count == 1
    assert [row["fallback_type"] for row in report.rows] == [
        "source_selection",
        "official_blog_fetch",
        "official_blog_failed_stage",
    ]
    assert report.rows[1]["feed_error_types"] == ["fetch_connection_error"]


def test_source_fallback_inputs_project_legacy_and_typed_values() -> None:
    raw_item = _raw_item(
        "Official fallback",
        "https://example.com/fallback",
        metadata={
            "official_blog_fetch_mode": "html_fallback",
            "official_blog_fallback": {
                "from": "feed",
                "to": "html",
                "feed_error_types": ["fetch_connection_error"],
            },
        },
    )
    error = SourceError(
        source_id="official",
        error_type="parse_error",
        error_message="parse failed",
        retryable=False,
        metadata={"official_blog_fallback_stage": "html"},
    )

    selection = SourceSelectionFallbackInput.from_value(
        {
            "fallback_used": True,
            "fallback_reason": "no_topic_match",
            "selected_source_ids": ["official"],
        }
    )
    [item] = SourceItemFallbackInput.from_values([raw_item])
    [error_input] = SourceErrorFallbackInput.from_values([error])

    assert selection.fallback_used is True
    assert selection.fallback_reason == "no_topic_match"
    assert selection.selected_source_ids == ("official",)
    assert item.source_id == "source"
    assert item.has_official_blog_fallback is True
    assert item.fetch_mode == "html_fallback"
    assert item.feed_error_types == ("fetch_connection_error",)
    assert error_input.source_id == "official"
    assert error_input.official_blog_fallback_stage == "html"
    assert error_input.retryable is False


def test_source_fallback_item_input_requires_structured_fallback_payload() -> None:
    [item] = SourceItemFallbackInput.from_values(
        [
            _raw_item(
                "Unstructured fallback",
                "https://example.com/fallback",
                metadata={"official_blog_fallback": "yes"},
            )
        ]
    )

    assert item.has_official_blog_fallback is False
    assert item.feed_error_types == ()


def test_build_source_fallback_report_accepts_serialized_source_errors() -> None:
    report = build_source_fallback_report(
        raw_items=[],
        source_errors=[
            {
                "source_id": "official",
                "error_type": "parse_error",
                "error_message": "parse failed",
                "retryable": False,
                "metadata": {"official_blog_fallback_stage": "html"},
            }
        ],
    )

    assert report.error_fallback_count == 1
    assert report.rows[0]["source_id"] == "official"
    assert report.rows[0]["metadata"]["retryable"] is False


def test_build_source_fallback_report_rejects_unstructured_source_errors() -> None:
    with pytest.raises(TypeError, match="source fallback errors entries must be SourceError"):
        build_source_fallback_report(raw_items=[], source_errors=["parse_error"])


def test_build_source_error_policy_report_counts_policy_fields() -> None:
    errors = [
        SourceError(
            source_id="feed",
            error_type="fetch_timeout",
            error_message="timeout",
            retryable=True,
            metadata={"source_health_affecting": True},
        ),
        SourceError(
            source_id="pipeline",
            error_type="all_sources_failed",
            error_message="blocked",
            retryable=False,
            metadata={
                "source_health_affecting": False,
                "workflow_blocking": True,
                "operator_action_required": True,
            },
        ),
    ]

    report = build_source_error_policy_report(errors)

    assert report.total_error_count == 2
    assert report.retryable_error_count == 1
    assert report.non_retryable_error_count == 1
    assert report.health_affecting_error_count == 1
    assert report.workflow_blocking_error_count == 1
    assert report.operator_action_required_count == 1
    assert report.errors_by_type == {"fetch_timeout": 1, "all_sources_failed": 1}
    assert report.rows[1]["workflow_blocking"] is True


def test_build_source_error_policy_report_accepts_serialized_source_errors() -> None:
    report = build_source_error_policy_report(
        [
            {
                "source_id": "feed",
                "source_name": "Feed",
                "error_type": "fetch_timeout",
                "error_message": "timeout",
                "retryable": "false",
                "metadata": {
                    "source_health_affecting": "false",
                    "workflow_blocking": "true",
                },
            }
        ]
    )

    assert report.total_error_count == 1
    assert report.retryable_error_count == 0
    assert report.non_retryable_error_count == 1
    assert report.health_affecting_error_count == 0
    assert report.workflow_blocking_error_count == 1
    assert report.rows[0]["source_name"] == "Feed"


def test_build_source_error_policy_report_rejects_unstructured_source_errors() -> None:
    with pytest.raises(TypeError, match="source error policy errors entries must be SourceError"):
        build_source_error_policy_report(["fetch_timeout"])


def test_build_source_error_policy_report_projects_formal_policy_metadata() -> None:
    report = build_source_error_policy_report(
        [
            SourceError(
                source_id="feed",
                error_type="fetch_timeout",
                error_message="timeout",
                retryable=True,
                metadata={
                    "source_error_policy": {
                        "source_health_affecting": "false",
                        "workflow_blocking": "true",
                        "operator_action_required": "true",
                    },
                },
            )
        ]
    )

    assert report.total_error_count == 1
    assert report.retryable_error_count == 1
    assert report.health_affecting_error_count == 0
    assert report.workflow_blocking_error_count == 1
    assert report.operator_action_required_count == 1
    assert report.rows[0]["source_health_affecting"] is False
    assert report.rows[0]["workflow_blocking"] is True
    assert report.rows[0]["operator_action_required"] is True


def test_build_source_error_policy_report_prefers_formal_policy_metadata_over_legacy() -> None:
    report = build_source_error_policy_report(
        [
            SourceError(
                source_id="feed",
                error_type="fetch_timeout",
                error_message="timeout",
                retryable=True,
                metadata={
                    "source_health_affecting": True,
                    "workflow_blocking": False,
                    "operator_action_required": False,
                    "source_error_policy": {
                        "source_health_affecting": False,
                        "workflow_blocking": True,
                        "operator_action_required": True,
                    },
                },
            )
        ]
    )

    assert report.health_affecting_error_count == 0
    assert report.workflow_blocking_error_count == 1
    assert report.operator_action_required_count == 1
    assert report.rows[0]["source_health_affecting"] is False
    assert report.rows[0]["workflow_blocking"] is True
    assert report.rows[0]["operator_action_required"] is True


def test_build_source_health_report_summarizes_statuses() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    report = build_source_health_report(
        [
            SourceHealth(
                source_id="healthy",
                source_name="Healthy",
                status=SourceHealthStatus.HEALTHY,
                success_count_24h=2,
                avg_latency_ms_24h=12.5,
            ),
            SourceHealth(
                source_id="cooling",
                source_name="Cooling",
                status=SourceHealthStatus.DOWN,
                consecutive_failures=2,
                failure_count_24h=2,
                cooldown_until=now,
                last_error=SourceError(
                    source_id="cooling",
                    error_type="fetch_timeout",
                    error_message="timeout",
                ),
                metadata={"health_policy": "cooldown"},
            ),
            SourceHealth(
                source_id="degraded",
                source_name="Degraded",
                status=SourceHealthStatus.DEGRADED,
                consecutive_failures=1,
            ),
        ]
    )

    assert report.health_update_count == 3
    assert report.status_counts == {"healthy": 1, "down": 1, "degraded": 1}
    assert report.down_source_ids == ["cooling"]
    assert report.cooling_down_source_ids == ["cooling"]
    assert report.degraded_source_ids == ["degraded"]
    assert report.max_consecutive_failures == 2
    assert report.rows[1]["health_status"] == "down"
    assert report.rows[1]["consecutive_failure_count"] == 2
    assert report.rows[1]["last_error_type"] == "fetch_timeout"
    assert report.rows[1]["last_error_message"] == "timeout"
    assert report.rows[1]["metadata"] == {"health_policy": "cooldown"}


def test_build_source_governance_report_flags_policy_findings() -> None:
    report = build_source_governance_report(
        source_quality_scores=[
            {
                "source_id": "community-low",
                "quality_score": 0.6,
                "reliability_score": 0.4,
                "traceability_score": 0.8,
            }
        ],
        source_selection_report={
            "selected_sources": [
                {
                    "source_id": "community-low",
                    "source_type": "reddit",
                    "category": "community",
                }
            ]
        },
    )

    finding_types = [finding.finding_type for finding in report.findings]
    assert report.finding_count == 4
    assert report.blocking_finding_count == 1
    assert report.requires_strict_verification_source_ids == ["community-low"]
    assert finding_types == [
        "low_reliability_source",
        "weak_traceability",
        "low_source_quality",
        "community_source_requires_verification",
    ]
    assert report.to_dict()["findings"][1]["severity"] == "blocking"


def test_source_governance_report_passes_non_social_sources() -> None:
    report = build_source_governance_report(
        source_quality_scores=[
            {
                "source_id": "official-low",
                "quality_score": 0.2,
                "reliability_score": 0.1,
                "traceability_score": 0.0,
            }
        ],
        source_selection_report={
            "selected_sources": [
                {
                    "source_id": "official-low",
                    "source_type": "official_blog",
                    "category": "official",
                    "authority_score": 0.1,
                }
            ]
        },
    )

    assert report.finding_count == 0
    assert report.blocking_finding_count == 0
    assert report.requires_strict_verification_source_ids == []


def test_source_governance_report_uses_configurable_policy() -> None:
    report = build_source_governance_report(
        source_quality_scores=[
            {
                "source_id": "medium",
                "quality_score": 0.72,
                "reliability_score": 0.45,
                "traceability_score": 0.9,
            }
        ],
        source_selection_report={
            "selected_sources": [
                {
                    "source_id": "medium",
                    "source_type": "medium",
                    "category": "developer-community",
                    "authority_score": 0.7,
                }
            ]
        },
        policy=SourceGovernancePolicy(
            low_reliability_threshold=0.5,
            low_quality_threshold=0.7,
            minimum_traceability_score=0.95,
            require_traceability_for_final_report=False,
        ),
    )

    finding_types = [finding.finding_type for finding in report.findings]
    assert "low_reliability_source" in finding_types
    assert "weak_traceability" in finding_types
    assert "community_source_requires_verification" in finding_types
    assert report.blocking_finding_count == 0
    assert report.requires_strict_verification_source_ids == ["medium"]


def test_score_source_item_summarizes_source_side_quality_signals() -> None:
    normalized = normalize_items(
        [
            _raw_item(
                "AI policy update",
                "https://example.com/quality",
                reliability="low",
                authority_score=0.2,
                summary="Short summary.",
                language=None,
            )
        ]
    )[0]

    quality = score_source_item(normalized, now=datetime(2026, 5, 11, tzinfo=UTC))

    assert quality.normalized_item_id == normalized.normalized_item_id
    assert quality.source_item_id == normalized.source_item_id
    assert quality.source_id == "source"
    assert quality.reliability_score == 0.4
    assert quality.authority_score == 0.2
    assert quality.traceability_score == 1.0
    assert quality.freshness_score == 1.0
    assert quality.content_score == 0.6
    assert quality.language_score == 0.7
    assert quality.quality_score == 0.635
    assert quality.penalties == ["low_reliability", "low_authority", "thin_content", "language_unknown"]
    assert quality.to_dict()["quality_score"] == 0.635


def test_build_source_quality_summary_report_aggregates_scores_and_penalties() -> None:
    report = build_source_quality_summary_report(
        [
            {
                "normalized_item_id": "norm-1",
                "source_item_id": "raw-1",
                "source_id": "official",
                "quality_score": 0.9,
                "traceability_score": 1.0,
                "penalties": [],
            },
            {
                "normalized_item_id": "norm-2",
                "source_item_id": "raw-2",
                "source_id": "community",
                "quality_score": 0.6,
                "traceability_score": 0.8,
                "penalties": ["low_reliability", "weak_traceability"],
            },
        ]
    )

    assert report.item_count == 2
    assert report.average_quality_score == 0.75
    assert report.min_quality_score == 0.6
    assert report.max_quality_score == 0.9
    assert report.low_quality_count == 1
    assert report.weak_traceability_count == 1
    assert report.penalty_counts == {"low_reliability": 1, "weak_traceability": 1}
    assert report.rows[1]["low_quality"] is True


def test_canonicalize_url_removes_default_ports_and_preserves_custom_ports() -> None:
    assert canonicalize_url("https://Example.COM:443/post") == "https://example.com/post"
    assert canonicalize_url("http://Example.COM:80/post") == "http://example.com/post"
    assert canonicalize_url("https://Example.COM:8443/post") == "https://example.com:8443/post"


def test_canonicalize_url_resolves_relative_urls_with_base_url() -> None:
    assert (
        canonicalize_url("/post?utm_source=x", base_url="https://Example.COM/blog/index.html")
        == "https://example.com/post"
    )
    assert (
        canonicalize_url("post?b=2&a=1", base_url="https://example.com/blog/")
        == "https://example.com/blog/post?a=1&b=2"
    )


def test_deduplicate_items_removes_duplicate_canonical_urls() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI chip news", "https://example.com/post?utm_source=a"),
            _raw_item("Different title", "https://example.com/post"),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].canonical_url == "https://example.com/post"
    assert unique[0].metadata["lineage"]["canonical_url"] == "https://example.com/post"
    assert unique[0].metadata["lineage"]["source_item_id"].startswith("raw-")


def test_deduplicate_with_result_reports_duplicate_groups() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI chip news", "https://example.com/post?utm_source=a", reliability="low"),
            _raw_item("AI chip news", "https://example.com/post", reliability="high"),
        ]
    )

    result = deduplicate_with_result(normalized)
    payload = result.to_dict()

    assert len(result.kept_items) == 1
    assert result.kept_items[0].source_reliability.value == "high"
    assert len(result.dropped_items) == 1
    assert payload["duplicate_group_count"] == 1
    assert payload["dropped_item_count"] == 1
    assert result.duplicate_groups[0].kept_item_id == result.kept_items[0].normalized_item_id
    assert result.duplicate_groups[0].duplicate_item_ids == [result.dropped_items[0].normalized_item_id]
    assert set(result.duplicate_groups[0].reasons) >= {"canonical_url_hash", "title_hash"}


def test_deduplicate_items_removes_duplicate_content_hashes() -> None:
    normalized = normalize_items(
        [
            _raw_item("First headline", "https://example.com/first", summary="Same article body"),
            _raw_item("Second headline", "https://other.example/second", summary="Same article body"),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].title == "First headline"
    assert normalized[0].content_hash == normalized[1].content_hash


def test_deduplicate_items_merges_near_duplicate_titles() -> None:
    normalized = normalize_items(
        [
            _raw_item(
                "OpenAI releases GPT-5 model for developers",
                "https://example.com/openai-release",
                reliability="medium",
                summary="Official release summary.",
            ),
            _raw_item(
                "OpenAI releases new GPT 5 model for developers",
                "https://other.example/openai-release-analysis",
                reliability="high",
                summary="Analysis summary.",
            ),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].title == "OpenAI releases new GPT 5 model for developers"
    assert unique[0].source_reliability.value == "high"


def test_deduplicate_items_keeps_low_signal_title_overlap_separate() -> None:
    normalized = normalize_items(
        [
            _raw_item("OpenAI releases model update", "https://example.com/model"),
            _raw_item("OpenAI releases security update", "https://example.com/security"),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 2


def test_deduplicate_items_retains_higher_reliability_duplicate() -> None:
    normalized = normalize_items(
        [
            _raw_item(
                "Lower reliability",
                "https://example.com/post?utm_source=a",
                reliability="low",
            ),
            _raw_item("Higher reliability", "https://example.com/post", reliability="high"),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].title == "Higher reliability"
    assert unique[0].source_reliability.value == "high"


def test_deduplicate_items_prefers_newer_duplicate_when_reliability_ties() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI launch", "https://example.com/newer", days_old=1),
            _raw_item("AI launch", "https://example.com/latest"),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].url == "https://example.com/latest"


def test_deduplicate_items_prefers_more_complete_summary_when_other_signals_tie() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI launch", "https://example.com/brief", summary="Brief."),
            _raw_item(
                "AI launch",
                "https://example.com/complete",
                summary="Detailed summary with more complete source context.",
            ),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].url == "https://example.com/complete"


def test_deduplicate_items_prefers_official_source_when_other_signals_tie() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI launch", "https://example.com/community"),
            _raw_item(
                "AI launch",
                "https://example.com/official",
                metadata={"official_blog": True},
            ),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].url == "https://example.com/official"


def test_deduplicate_items_prefers_canonical_url_when_other_signals_tie() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI launch", "https://example.com/tracked?utm_source=a"),
            _raw_item(
                "AI launch",
                "https://example.com/tracked",
            ),
        ]
    )

    unique = deduplicate_items(normalized)

    assert len(unique) == 1
    assert unique[0].url == "https://example.com/tracked"


def test_normalize_item_detects_future_published_at() -> None:
    raw = _raw_item("Future dated", "https://example.com/future", days_old=-1)

    normalized = normalize_items([raw])[0]

    assert normalized.published_at == raw.fetched_at
    assert normalized.metadata["lineage"]["published_at"] == raw.fetched_at.isoformat().replace("+00:00", "Z")
    assert normalized.metadata["time_normalization"] == {
        "future_timestamp_detected": True,
        "original_published_at": raw.published_at.isoformat().replace("+00:00", "Z"),
        "published_at_normalized_to": "fetched_at",
    }


def test_normalize_item_preserves_valid_published_at() -> None:
    raw = _raw_item("Valid date", "https://example.com/valid", days_old=1)

    normalized = normalize_items([raw])[0]

    assert normalized.published_at == raw.published_at
    assert "time_normalization" not in normalized.metadata


def test_normalize_item_falls_back_missing_language_to_unknown() -> None:
    raw = _raw_item("No language", "https://example.com/no-language")

    normalized = normalize_items([raw])[0]

    assert normalized.language == "unknown"
    assert normalized.metadata["language_normalization"] == {
        "fallback_applied": True,
        "language": "unknown",
    }


def test_normalize_item_detects_clear_content_language() -> None:
    raw = _raw_item(
        "人工智能政策更新",
        "https://example.com/zh",
        summary="中国发布人工智能治理政策，强调模型安全和透明度。",
        language=None,
    )

    normalized = normalize_items([raw])[0]

    assert normalized.language == "zh"
    assert normalized.metadata["language_normalization"] == {
        "fallback_applied": False,
        "detection_applied": True,
        "language": "zh",
    }


def test_detect_language_identifies_long_english_content() -> None:
    assert (
        detect_language(
            "The policy update from the agency focuses on model safety and "
            "coordination with industry."
        )
        == "en"
    )


def test_normalize_item_preserves_existing_language() -> None:
    raw = _raw_item("English", "https://example.com/en", language="en")

    normalized = normalize_items([raw])[0]

    assert normalized.language == "en"
    assert "language_normalization" not in normalized.metadata


def test_normalize_item_preserves_artifact_refs_in_lineage() -> None:
    raw = RawSourceItem(
        source_item_id="raw-artifacted",
        source_id="source",
        source_name="Source",
        source_type=SourceType.RSS,
        title="Artifacted item",
        url="https://example.com/artifacted",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        summary="Summary",
        raw_artifact_ref={"artifact_id": "raw-ref", "path": "sources/raw.txt"},
        parse_artifact_ref={"artifact_id": "parse-ref", "path": "sources/item.json"},
        metadata={"source_reliability": "high"},
    )

    normalized = normalize_items([raw])[0]

    lineage = normalized.metadata["lineage"]
    assert lineage["raw_artifact_ref"]["artifact_id"] == "raw-ref"
    assert lineage["parse_artifact_ref"]["artifact_id"] == "parse-ref"


def test_rank_items_prioritizes_topic_relevance_and_reliability() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI chip export update", "https://example.com/chips", reliability="high"),
            _raw_item("Sports result", "https://example.com/sports", reliability="low"),
        ]
    )

    ranked = rank_items(normalized, topic="AI chip", now=datetime(2026, 5, 11, tzinfo=UTC))

    assert ranked[0].item.title == "AI chip export update"
    assert ranked[0].final_score > ranked[1].final_score
    assert ranked[0].lineage.source_id == "source"
    assert ranked[0].lineage.normalized_item_id == ranked[0].item.normalized_item_id
    assert ranked[0].lineage.ranked_item_id == ranked[0].ranked_item_id
    assert ranked[0].ranking_trace.final_score == ranked[0].final_score
    assert ranked[0].source_quality.traceability_score == 1.0
    lineage = ranked[0].metadata["lineage"]
    assert lineage["source_id"] == "source"
    assert lineage["normalized_item_id"] == ranked[0].item.normalized_item_id
    assert lineage["ranked_item_id"] == ranked[0].ranked_item_id
    assert lineage["final_score"] == ranked[0].final_score
    assert lineage["authority_score"] == 0.5
    assert lineage["source_quality_score"] == ranked[0].metadata["source_quality"]["quality_score"]
    assert ranked[0].metadata["source_quality"]["traceability_score"] == 1.0
    assert ranked[0].duplicate_cluster_score == 0.5
    assert ranked[0].historical_importance_score == 0.5
    assert ranked[0].subscription_match_score > 0
    ranking_scores = build_source_ranking_scores(ranked)
    assert ranking_scores[0].ranked_item_id == ranked[0].ranked_item_id
    assert ranking_scores[0].source_id == "source"
    assert ranking_scores[0].authority_score == 0.5
    assert ranking_scores[0].final_score == ranked[0].final_score
    assert ranking_scores[0].to_dict()["url"] == ranked[0].item.canonical_url

    traceability_report = build_source_traceability_report(ranked)
    assert traceability_report.traceability_status == "complete"
    assert traceability_report.traceable_item_count == 2
    assert traceability_report.issue_count == 0
    assert traceability_report.rows[0]["ranked_item_id"] == ranked[0].ranked_item_id


def test_ranked_source_item_projects_legacy_metadata_into_formal_fields() -> None:
    ranked = rank_items(
        normalize_items([_raw_item("AI chip export update", "https://example.com/chips")]),
        topic="AI chip",
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )[0]

    lineage_only = {
        "source_id": "source",
        "source_item_id": ranked.item.source_item_id,
        "normalized_item_id": ranked.item.normalized_item_id,
        "ranked_item_id": ranked.ranked_item_id,
        "canonical_url": ranked.item.canonical_url,
    }
    legacy_ranked = replace(
        ranked,
        lineage=None,
        source_quality=None,
        ranking_trace=None,
        metadata={
            "lineage": lineage_only,
            "source_quality": ranked.source_quality.to_dict(),
        },
    )

    assert legacy_ranked.lineage.source_id == "source"
    assert legacy_ranked.lineage.ranked_item_id == ranked.ranked_item_id
    assert legacy_ranked.ranking_trace.final_score == ranked.final_score
    assert legacy_ranked.ranking_trace.relevance_score == ranked.relevance_score
    assert legacy_ranked.source_quality.quality_score == ranked.source_quality.quality_score


def test_deduplicate_marks_same_event_cluster_for_ranking() -> None:
    normalized = normalize_items(
        [
            _raw_item("AI runtime update", "https://example.com/a", reliability="high"),
            _raw_item("AI runtime update", "https://mirror.example.com/a", reliability="medium"),
        ]
    )

    dedup_result = deduplicate_with_result(normalized)

    assert len(dedup_result.kept_items) == 1
    cluster = dedup_result.kept_items[0].metadata["duplicate_cluster"]
    assert cluster["cluster_size"] == 2
    assert cluster["same_event_cluster"] is True
    assert dedup_result.kept_items[0].ranking_signals.duplicate_cluster.cluster_size == 2
    assert dedup_result.kept_items[0].ranking_signals.duplicate_cluster.same_event_cluster is True
    kept_item_without_cluster_metadata = replace(dedup_result.kept_items[0], metadata={})
    ranked = rank_items(
        [kept_item_without_cluster_metadata],
        topic="AI runtime",
        subscription_topics=["runtime update"],
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    ranking_scores = build_source_ranking_scores(ranked)
    assert ranked[0].duplicate_cluster_score > 0.5
    assert ranking_scores[0].duplicate_cluster_score == ranked[0].duplicate_cluster_score
    assert ranking_scores[0].subscription_match_score > 0


def test_build_source_traceability_report_flags_missing_and_mismatched_lineage() -> None:
    ranked = rank_items(
        normalize_items([_raw_item("AI chip export update", "https://example.com/chips")]),
        topic="AI chip",
        now=datetime(2026, 5, 11, tzinfo=UTC),
    )
    broken_lineage = replace(
        ranked[0].lineage,
        canonical_url=None,
        source_id="other-source",
    )
    broken_ranked = replace(
        ranked[0],
        lineage=broken_lineage,
        ranking_trace=replace(ranked[0].ranking_trace, lineage=broken_lineage),
    )

    report = build_source_traceability_report([broken_ranked])

    assert report.traceability_status == "partial"
    assert report.traceable_item_count == 0
    assert report.untraceable_item_count == 1
    assert report.issue_count == 2
    assert report.rows[0]["missing_fields"] == ["canonical_url"]
    assert report.rows[0]["mismatched_fields"] == ["source_id"]
    assert [issue.issue_type for issue in report.issues] == [
        "mismatched_lineage_field",
        "missing_lineage_field",
    ]
    assert report.to_dict()["issues"][0]["expected"] == "source"


def test_build_source_freshness_report_buckets_ranked_items() -> None:
    current_time = datetime(2026, 5, 11, tzinfo=UTC)
    ranked = rank_items(
        normalize_items(
            [
                _raw_item("Current AI update", "https://example.com/current"),
                _raw_item("Stale AI update", "https://example.com/stale", days_old=45),
            ]
        ),
        topic="AI",
        now=current_time,
    )

    report = build_source_freshness_report(ranked, now=current_time)

    assert report.freshness_status == "mixed"
    assert report.ranked_item_count == 2
    assert report.fresh_item_count == 1
    assert report.stale_item_count == 1
    assert report.buckets["0_1_days"] == 1
    assert report.buckets["over_30_days"] == 1
    assert any(row["stale"] is True for row in report.rows)


def test_build_source_freshness_report_tracks_missing_and_future_timestamps() -> None:
    current_time = datetime(2026, 5, 11, tzinfo=UTC)
    normalized = normalize_items(
        [
            _raw_item("Missing published date", "https://example.com/missing"),
            _raw_item("Future published date", "https://example.com/future", days_old=-1),
        ]
    )
    normalized[0] = replace(normalized[0], published_at=None)
    ranked = rank_items(normalized, topic="AI", now=current_time)

    report = build_source_freshness_report(ranked, now=current_time)

    assert report.freshness_status == "mixed"
    assert report.missing_published_at_count == 1
    assert report.future_timestamp_count == 1
    assert report.buckets["missing_published_at"] == 1
    assert any(row["timestamp_basis"] == "fetched_at" for row in report.rows)
    assert any(row["future_timestamp_detected"] is True for row in report.rows)


def test_rank_items_uses_source_authority_score() -> None:
    normalized = normalize_items(
        [
            _raw_item(
                "AI chip export update",
                "https://example.com/low-authority",
                reliability="high",
                authority_score=0.1,
            ),
            _raw_item(
                "AI chip export update",
                "https://example.com/high-authority",
                reliability="high",
                authority_score=1.0,
            ),
        ]
    )

    normalized = [
        replace(
            item,
            metadata={key: value for key, value in item.metadata.items() if key != "source_authority_score"},
        )
        for item in normalized
    ]

    ranked = rank_items(normalized, topic="AI chip", now=datetime(2026, 5, 11, tzinfo=UTC))

    assert ranked[0].item.url == "https://example.com/high-authority"
    assert ranked[0].final_score > ranked[1].final_score
    assert ranked[0].source_quality.authority_score == 1.0
    assert ranked[0].metadata["lineage"]["authority_score"] == 1.0
