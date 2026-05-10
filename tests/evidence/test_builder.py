from datetime import UTC, datetime

from domain.sources import NormalizedSourceItem, RankedSourceItem
from evidence import EvidenceBuilder


def test_evidence_builder_creates_bundle_from_ranked_sources() -> None:
    item = NormalizedSourceItem(
        normalized_item_id="norm_1",
        source_item_id="raw_1",
        source_id="source",
        title="AI chips",
        normalized_title="ai chips",
        url="https://example.com/chips?utm_source=x",
        canonical_url="https://example.com/chips",
        canonical_url_hash="hash-url",
        title_hash="hash-title",
        content_hash="hash-content",
        source_reliability="high",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        summary="Chip summary",
    )
    ranked = RankedSourceItem(
        ranked_item_id="rank_1",
        item=item,
        relevance_score=1.0,
        recency_score=1.0,
        reliability_score=1.0,
        novelty_score=1.0,
        final_score=0.95,
    )

    bundle = EvidenceBuilder().build([ranked], bundle_id="run-1")

    assert bundle.bundle_id == "run-1"
    assert bundle.items[0].source_url == "https://example.com/chips"
    assert bundle.items[0].confidence == 0.95
    assert bundle.source_urls == {"https://example.com/chips"}
