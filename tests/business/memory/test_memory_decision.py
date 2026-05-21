from __future__ import annotations

from dataclasses import dataclass

from business.foundation import (
    BoardCard,
    BoardType,
    Confidence,
    ObjectRef,
    ObjectType,
    Score,
    SourceRef,
    SourceReliability,
    SourceType,
)
from business.memory import (
    BusinessMemoryContext,
    BusinessMemoryDecisionService,
    BusinessMemoryHit,
    BusinessMemoryRecallService,
    estimate_historical_duplicate_score,
    estimate_previous_misrank_penalty,
    estimate_source_reliability,
    estimate_topic_momentum,
    source_noise_penalty,
)


def test_empty_memory_context_is_zero_impact() -> None:
    context = BusinessMemoryContext.empty("agent memory", reason="missing")

    assert context.metadata["memory_available"] is False
    assert context.to_feature_dict() == {
        "source_reliability_memory_score": 0.0,
        "historical_duplicate_score": 0.0,
        "topic_momentum_score": 0.0,
        "previous_misrank_penalty": 0.0,
        "historical_noise_penalty": 0.0,
        "memory_safety_score": 0.0,
        "memory_decision_score": 0.0,
    }


def test_memory_hit_normalizes_dict_and_object_results() -> None:
    dict_hit = BusinessMemoryHit.from_any(
        {
            "document_id": "doc-1",
            "score": 1.2,
            "payload": {"source_name": "OpenAI Blog", "topic": "agents"},
            "metadata": {"confidence": 0.9, "tags": ["reliable_source"]},
        }
    )
    object_hit = BusinessMemoryHit.from_any(_SearchResult())

    assert dict_hit.hit_id == "doc-1"
    assert dict_hit.score == 1.0
    assert dict_hit.source_name == "OpenAI Blog"
    assert object_hit.hit_id == "doc-2"
    assert object_hit.topic == "memory"


def test_recall_service_soft_fails_without_port() -> None:
    context = BusinessMemoryRecallService().recall_for_card(_card(), board_type=BoardType.AI_NEWS)

    assert context.hits == []
    assert context.metadata["memory_available"] is False
    assert context.metadata["reason"] == "memory_search_port_missing"


def test_recall_service_normalizes_search_port_results() -> None:
    port = _SearchPort(
        [
            {
                "document_id": "doc-1",
                "text": "OpenAI launches agent memory",
                "score": 0.91,
                "metadata": {"source_name": "OpenAI Blog", "topic": "agents"},
            }
        ]
    )

    context = BusinessMemoryRecallService(port).recall_for_card(_card(), board_type=BoardType.AI_NEWS)

    assert port.calls[0]["collection"] == "evidence_items"
    assert context.metadata["memory_available"] is True
    assert context.hits[0].source_name == "OpenAI Blog"


def test_memory_decision_helpers_are_deterministic() -> None:
    card = _card()
    hits = [
        BusinessMemoryHit(
            hit_id="doc-1",
            score=0.9,
            text=card.title,
            source_name="OpenAI Blog",
            topic="agents",
            evidence_id=card.evidence_refs[0].source_id,
            published_at="2026-05-20T00:00:00Z",
            tags=["reliable_source", "weak_evidence_ranked_too_high", "repeated_noise"],
            metadata={"confidence": 0.92, "note": "noise"},
        )
    ]

    assert estimate_source_reliability(hits, source_name="OpenAI Blog") > 0.0
    assert estimate_historical_duplicate_score(card, hits) > 0.6
    assert estimate_topic_momentum(hits) > 0.0
    assert estimate_previous_misrank_penalty(hits) > 0.0
    assert source_noise_penalty(hits) > 0.0


def test_decision_service_builds_memory_feature_vector() -> None:
    port = _SearchPort(
        [
            {
                "document_id": "doc-1",
                "text": "OpenAI launches agent memory",
                "score": 0.91,
                "metadata": {
                    "source_name": "OpenAI Blog",
                    "topic": "agents",
                    "confidence": 0.9,
                    "tags": ["reliable_source"],
                },
                "published_at": "2026-05-20T00:00:00Z",
            }
        ]
    )
    service = BusinessMemoryDecisionService(BusinessMemoryRecallService(port))

    features = service.memory_features_for_card(_card(), board_type=BoardType.AI_NEWS)

    assert features.metadata["memory_available"] is True
    assert features.metadata["memory_hit_count"] == 1
    assert features.get("source_reliability_memory_score") > 0.5
    assert 0.0 <= features.get("memory_decision_score") <= 1.0


@dataclass
class _SearchResult:
    document_id: str = "doc-2"
    score: float = 0.8
    text: str = "Memory launch"
    topic: str = "memory"


class _SearchPort:
    def __init__(self, results: list[object]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[object]:
        self.calls.append(dict(kwargs))
        return list(self.results)


def _card() -> BoardCard:
    return BoardCard(
        card_id="card-1",
        board_type=BoardType.AI_NEWS,
        title="OpenAI launches agent memory",
        summary="OpenAI announces a new agent memory API for enterprise adoption.",
        primary_object_ref=ObjectRef(object_type=ObjectType.NEWS_ITEM, object_id="news-1"),
        score=Score(value=0.5),
        confidence=Confidence(value=0.7),
        evidence_refs=[
            SourceRef(
                source_name="OpenAI Blog",
                source_type=SourceType.OFFICIAL_BLOG,
                source_id="src-1",
                reliability=SourceReliability.OFFICIAL,
                url="https://example.com/news",
            )
        ],
    )
