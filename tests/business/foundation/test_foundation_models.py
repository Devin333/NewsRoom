from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from business.foundation import (
    Badge,
    BoardCard,
    BoardType,
    Confidence,
    DisplayMetric,
    ObjectRef,
    ObjectType,
    ProcessingStatus,
    Relation,
    RelationDirection,
    RelationType,
    Score,
    ScoreFactor,
    Signal,
    SignalType,
    SourceRef,
    SourceType,
    build_stable_id,
    make_signal_identity,
    score_level,
)


def test_score_level_matches_prd_thresholds() -> None:
    assert score_level(0.0) == "very_low"
    assert score_level(0.19) == "very_low"
    assert score_level(0.2) == "low"
    assert score_level(0.4) == "medium"
    assert score_level(0.6) == "high"
    assert score_level(0.8) == "very_high"
    assert Score(value=0.72).level == "high"


def test_score_and_confidence_validate_bounds_and_factors() -> None:
    factor = ScoreFactor(name="source_reliability", value=0.8, weight=0.4)

    score = Score(value=0.8, factors=[factor])
    confidence = Confidence(value=0.7, factors=[factor])

    assert score.factors == [factor]
    assert confidence.factors == [factor]
    with pytest.raises(ValidationError):
        Score(value=1.2)
    with pytest.raises(ValidationError):
        ScoreFactor(name="", value=0.5)


def test_stable_ids_and_signal_identity_are_deterministic() -> None:
    source = SourceRef(
        source_id="openai-blog",
        source_name="OpenAI Blog",
        source_type=SourceType.OFFICIAL_BLOG,
        source_url="https://openai.com/blog",
    )
    published_at = datetime(2026, 5, 19, tzinfo=UTC)

    first = make_signal_identity(
        signal_type=SignalType.AI_NEWS,
        board_type=BoardType.AI_NEWS,
        source=source,
        title="Agent Memory update",
        url="https://openai.com/blog/agent-memory?utm_source=newsletter",
        published_at=published_at,
    )
    second = make_signal_identity(
        signal_type=SignalType.AI_NEWS,
        board_type=BoardType.AI_NEWS,
        source=source,
        title="Agent Memory update",
        url="https://openai.com/blog/agent-memory?utm_source=newsletter",
        published_at=published_at,
    )

    assert first == second
    assert build_stable_id("tech", "Agent Memory") == build_stable_id("tech", "agent memory")
    assert "utm_source" not in first[1]


def test_signal_required_fields_and_datetime_normalization() -> None:
    signal = _signal()

    assert signal.processing_status == ProcessingStatus.NEW
    assert signal.published_at is not None
    assert signal.published_at.tzinfo == UTC
    assert signal.collected_at.tzinfo == UTC

    with pytest.raises(ValidationError):
        _signal(title="")


def test_relation_requires_evidence_and_validates_direction() -> None:
    relation = _relation(
        relation_type=RelationType.IMPLEMENTS,
        direction=RelationDirection.DIRECTED,
        evidence_signal_ids=["sig-1"],
    )

    assert relation.evidence_signal_ids == ["sig-1"]
    assert relation.created_at.tzinfo == UTC

    with pytest.raises(ValidationError):
        _relation(evidence_signal_ids=[], evidence_claim_ids=[])
    with pytest.raises(ValidationError):
        _relation(
            relation_type=RelationType.IMPLEMENTS,
            direction=RelationDirection.UNDIRECTED,
            evidence_signal_ids=["sig-1"],
        )
    with pytest.raises(ValidationError):
        _relation(
            relation_type=RelationType.COMPARES,
            direction=RelationDirection.DIRECTED,
            evidence_signal_ids=["sig-1"],
        )


def test_board_card_serialization_does_not_expose_signal_raw_payload() -> None:
    card = BoardCard(
        card_id="card-1",
        board_type=BoardType.AI_NEWS,
        title="Agent Memory",
        summary="A concise card",
        primary_object_ref=ObjectRef(
            object_type=ObjectType.TECHNOLOGY,
            object_id="tech-agent-memory",
            label="Agent Memory",
        ),
        badges=[Badge(label="ai_news")],
        metrics=[DisplayMetric(label="Signals", value=1)],
        score=Score(value=0.7, factors=[ScoreFactor(name="impact", value=0.7)]),
        confidence=Confidence(value=0.75, factors=[ScoreFactor(name="evidence", value=0.75)]),
    )

    payload = card.to_dict()

    assert "raw_payload" not in payload
    assert payload["score"]["factors"][0]["name"] == "impact"


def _signal(**overrides) -> Signal:
    source = SourceRef(
        source_id="source-1",
        source_name="Source",
        source_type=SourceType.RSS,
        source_url="https://example.com",
    )
    signal_id, canonical_key, content_hash = make_signal_identity(
        signal_type=SignalType.AI_NEWS,
        board_type=BoardType.AI_NEWS,
        source=source,
        title=overrides.get("title", "Agent Memory update"),
        url="https://example.com/item",
        published_at=datetime(2026, 5, 19),
    )
    values = {
        "signal_id": signal_id,
        "signal_type": SignalType.AI_NEWS,
        "board_type": BoardType.AI_NEWS,
        "title": "Agent Memory update",
        "summary": "Signal summary",
        "source": source,
        "published_at": datetime(2026, 5, 19),
        "collected_at": datetime(2026, 5, 20),
        "content_hash": content_hash,
        "canonical_key": canonical_key,
    }
    values.update(overrides)
    return Signal(**values)


def _relation(**overrides) -> Relation:
    values = {
        "relation_id": "rel-1",
        "relation_type": RelationType.MENTIONS,
        "source_ref": ObjectRef(object_type=ObjectType.SIGNAL, object_id="sig-1"),
        "target_ref": ObjectRef(object_type=ObjectType.TECHNOLOGY, object_id="tech-1"),
        "direction": RelationDirection.DIRECTED,
        "evidence_signal_ids": ["sig-1"],
        "confidence": Confidence(value=0.8, factors=[ScoreFactor(name="evidence", value=0.8)]),
        "created_at": datetime(2026, 5, 19),
    }
    values.update(overrides)
    return Relation(**values)
