from datetime import UTC, datetime

from business.layers.signal import SignalPipeline
from business.layers.signal import records
from business.layers.signal.source_processing import rank_items as canonical_rank_items


def test_records_reexports_canonical_source_processing_services() -> None:
    assert records.rank_items is canonical_rank_items


def test_signal_pipeline_projects_raw_authority_through_ranking_signals() -> None:
    raw = records.RawSourceItem(
        source_item_id="raw-authority",
        source_id="source",
        source_name="Source",
        source_type="rss",
        title="AI chip update",
        url="https://example.com/chips",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        summary="AI chip export policy update.",
        tags=["AI"],
        metadata={
            "source_reliability": "high",
            "source_authority_score": 1.4,
        },
    )

    result = SignalPipeline().build_from_raw_items([raw], topic="AI chip")

    assert result.signals[0].metrics["source_authority_score"] == 1.0
    authority_factor = next(
        factor for factor in result.signals[0].confidence.factors if factor.name == "authority_score"
    )
    assert authority_factor.value == 1.0
    assert result.signals[0].tags == ["ai"]
