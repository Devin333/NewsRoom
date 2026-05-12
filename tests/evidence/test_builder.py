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
        metadata={
            "lineage": {
                "source_id": "source",
                "source_item_id": "raw_1",
                "canonical_url": "https://example.com/chips",
            }
        },
    )
    ranked = RankedSourceItem(
        ranked_item_id="rank_1",
        item=item,
        relevance_score=1.0,
        recency_score=1.0,
        reliability_score=1.0,
        novelty_score=1.0,
        final_score=0.95,
        metadata={
            "lineage": {
                "source_id": "source",
                "source_item_id": "raw_1",
                "normalized_item_id": "norm_1",
                "ranked_item_id": "rank_1",
                "canonical_url": "https://example.com/chips",
            }
        },
    )

    build_result = EvidenceBuilder().build_with_scores([ranked], bundle_id="run-1")
    bundle = build_result.bundle

    assert bundle.bundle_id == "run-1"
    assert bundle.items[0].source_url == "https://example.com/chips"
    assert bundle.items[0].confidence == 0.95
    assert bundle.items[0].lineage is not None
    assert bundle.items[0].lineage.ranked_item_id == "rank_1"
    assert bundle.items[0].metadata["source_lineage"]["source_item_id"] == "raw_1"
    assert bundle.items[0].metadata["source_lineage"]["ranked_item_id"] == "rank_1"
    assert bundle.source_urls == {"https://example.com/chips"}
    assert bundle.source_map == {"https://example.com/chips": [bundle.items[0].evidence_id]}
    assert bundle.coverage_notes == ["Built 1 evidence item(s) from 1 source URL(s)."]
    assert bundle.missing_information == []

    score = build_result.evidence_scores[0]
    assert score.evidence_id == bundle.items[0].evidence_id
    assert score.source_reliability_score == 1.0
    assert score.freshness_score == 1.0
    assert score.extraction_confidence_score == 1.0
    assert score.final_confidence == 0.95
    assert build_result.candidate_claims[0].source_evidence_ids == [bundle.items[0].evidence_id]
    assert build_result.verified_findings is not None
    assert len(build_result.verified_findings.accepted_claims) == 1
    assert build_result.verified_findings.accepted_claims[0].supporting_sources == [
        "https://example.com/chips"
    ]

    compatibility_bundle = EvidenceBuilder().build([ranked], bundle_id="run-1")
    assert compatibility_bundle.to_dict() == bundle.to_dict()
