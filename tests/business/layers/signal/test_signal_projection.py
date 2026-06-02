from datetime import UTC, datetime

from business.foundation import BoardType, ProcessingStatus, SignalType, SourceType
from business.foundation.models.source import SourceRankingSignals, SourceReliability
from business.layers.signal.records import RawSourceItem
from business.layers.signal.signal_projection import (
    SourceSignalProjectionInput,
    SourceSignalProjectionService,
)


def test_source_signal_projection_builds_signal_boundary_fields() -> None:
    raw = RawSourceItem(
        source_item_id="raw-1",
        source_id="atom-source",
        source_name="Atom Source",
        source_type="atom",
        title="AI Launch",
        url="HTTPS://Example.com/post?utm_source=x&b=2&a=1",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        published_at=datetime(2026, 5, 10, tzinfo=UTC),
        summary="Launch summary.",
        authors=["Alice"],
        tags=["AI", "launch"],
        metadata={
            "source_reliability": "high",
            "source_authority_score": 1.5,
            "signal_tags": ["AI", "policy"],
        },
    )

    signal = SourceSignalProjectionService().project(
        SourceSignalProjectionInput(
            item=raw,
            board_type=BoardType.AI_NEWS,
            signal_type=SignalType.AI_NEWS,
            processing_status=ProcessingStatus.NORMALIZED,
            metrics={"custom_metric": 3},
        )
    )

    assert signal.source.source_type == SourceType.RSS
    assert signal.url == "https://example.com/post?a=1&b=2"
    assert signal.metrics["source_authority_score"] == 1.0
    assert signal.metrics["custom_metric"] == 3
    assert signal.tags == ["ai", "launch", "policy"]
    assert signal.confidence.factors[1].name == "source_authority"
    assert signal.confidence.factors[1].value == 1.0


def test_source_signal_projection_prefers_explicit_quality_inputs_over_metadata() -> None:
    raw = RawSourceItem(
        source_item_id="raw-2",
        source_id="source",
        source_name="Source",
        source_type="rss",
        title="Boundary update",
        url="https://example.com/update",
        fetched_at=datetime(2026, 5, 11, tzinfo=UTC),
        summary="Summary.",
        tags=["metadata-tag"],
        metadata={
            "source_reliability": "low",
            "source_authority_score": 0.1,
        },
    )

    signal = SourceSignalProjectionService().project(
        SourceSignalProjectionInput(
            item=raw,
            board_type=BoardType.AI_NEWS,
            signal_type=SignalType.AI_NEWS,
            processing_status=ProcessingStatus.ANALYZED,
            source_reliability=SourceReliability.HIGH,
            ranking_signals=SourceRankingSignals(authority_score=0.9, tags=["formal-tag"]),
        )
    )

    assert signal.metrics["source_reliability"] == "high"
    assert signal.metrics["source_authority_score"] == 0.9
    assert signal.tags == ["formal-tag"]
    assert signal.confidence.factors[0].value == 1.0
    assert signal.confidence.factors[1].value == 0.9
