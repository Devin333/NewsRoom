from datetime import UTC, datetime, timedelta

from domain.sources import RawSourceItem, SourceType
from sources.processing import deduplicate_items, normalize_items, rank_items
from sources.processing.normalize import canonicalize_url, normalize_text


def _raw_item(title: str, url: str, *, reliability: str = "medium", days_old: int = 0) -> RawSourceItem:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    return RawSourceItem(
        source_item_id=f"raw-{title}-{url}",
        source_id="source",
        source_name="Source",
        source_type=SourceType.RSS,
        title=title,
        url=url,
        fetched_at=now,
        published_at=now - timedelta(days=days_old),
        summary=f"Summary for {title}",
        metadata={"source_reliability": reliability},
    )


def test_normalize_text_and_canonical_url() -> None:
    assert normalize_text(" AI   Chips ") == "ai chips"
    assert (
        canonicalize_url("HTTPS://Example.COM/post/?utm_source=x&b=2&a=1#section")
        == "https://example.com/post?a=1&b=2"
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
