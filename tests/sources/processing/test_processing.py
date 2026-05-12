from datetime import UTC, datetime, timedelta

from domain.sources import RawSourceItem, SourceError, SourcePipelineMetrics, SourceType
from sources.processing import (
    build_source_coverage_report,
    deduplicate_items,
    deduplicate_with_result,
    normalize_items,
    rank_items,
)
from sources.processing.normalize import canonicalize_url, normalize_text


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
    lineage = ranked[0].metadata["lineage"]
    assert lineage["source_id"] == "source"
    assert lineage["normalized_item_id"] == ranked[0].item.normalized_item_id
    assert lineage["ranked_item_id"] == ranked[0].ranked_item_id
    assert lineage["final_score"] == ranked[0].final_score
    assert lineage["authority_score"] == 0.5


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

    ranked = rank_items(normalized, topic="AI chip", now=datetime(2026, 5, 11, tzinfo=UTC))

    assert ranked[0].item.url == "https://example.com/high-authority"
    assert ranked[0].final_score > ranked[1].final_score
    assert ranked[0].metadata["lineage"]["authority_score"] == 1.0
