from __future__ import annotations

from business.foundation import BoardCard, BoardType
from business.memory.duplicate_detection import estimate_historical_duplicate_score
from business.memory.features import build_memory_feature_vector
from business.memory.feedback_memory import estimate_previous_misrank_penalty
from business.memory.intelligence_repository import IntelligenceMemoryQueryRepository
from business.memory.memory_features import MemoryFeatureComputer, MemoryFeatureInput
from business.memory.models import BusinessMemoryContext
from business.memory.recall import BusinessMemoryRecallService
from business.memory.source_reliability import estimate_source_reliability, source_noise_penalty
from business.memory.topic_momentum import estimate_topic_momentum
from framework.scoring import FeatureVector


class BusinessMemoryDecisionService:
    def __init__(
        self,
        recall_service: BusinessMemoryRecallService | None = None,
        *,
        intelligence_repository: IntelligenceMemoryQueryRepository | None = None,
        memory_feature_computer: MemoryFeatureComputer | None = None,
    ) -> None:
        self.recall_service = recall_service or BusinessMemoryRecallService()
        self.memory_feature_computer = memory_feature_computer or (
            MemoryFeatureComputer(intelligence_repository) if intelligence_repository is not None else None
        )

    def memory_context_for_card(
        self,
        card: BoardCard,
        *,
        board_type: BoardType,
    ) -> BusinessMemoryContext:
        context = self.recall_service.recall_for_card(card, board_type=board_type)
        hits = context.hits
        source_name = card.evidence_refs[0].source_name if card.evidence_refs else None
        return BusinessMemoryContext(
            query=context.query,
            hits=hits,
            source_reliability_score=estimate_source_reliability(hits, source_name=source_name),
            historical_duplicate_score=estimate_historical_duplicate_score(card, hits),
            topic_momentum_score=estimate_topic_momentum(hits),
            previous_misrank_penalty=estimate_previous_misrank_penalty(hits),
            historical_noise_penalty=source_noise_penalty(hits),
            metadata=dict(context.metadata),
        )

    def memory_features_for_card(
        self,
        card: BoardCard,
        *,
        board_type: BoardType,
    ) -> FeatureVector:
        context = self.memory_context_for_card(card, board_type=board_type)
        features = build_memory_feature_vector(context)
        structured = self._structured_memory_features(card, context)
        return features.merge(structured) if structured is not None else features

    def _structured_memory_features(
        self,
        card: BoardCard,
        context: BusinessMemoryContext,
    ) -> FeatureVector | None:
        if self.memory_feature_computer is None:
            return None
        source_id = card.evidence_refs[0].source_id if card.evidence_refs else None
        topic = (
            str(card.metadata.get("topic"))
            if card.metadata.get("topic") is not None
            else str(context.query or card.title)
        )
        ranking = self.memory_feature_computer.compute(
            MemoryFeatureInput(
                topic=topic,
                source_id=source_id,
                entity_ids=_string_list(card.metadata.get("entity_ids")),
                claim_ids=_string_list(card.metadata.get("claim_ids")),
                event_id=_optional_str(card.metadata.get("event_id")),
                base_score=card.score.value,
            )
        )
        return FeatureVector.from_scores(
            {
                "memory_source_reliability": ranking.source_reliability,
                "memory_topic_momentum": ranking.topic_momentum,
                "memory_entity_importance": ranking.entity_importance,
                "memory_event_novelty": ranking.event_novelty,
                "memory_duplicate_penalty": ranking.duplicate_penalty,
                "memory_contradiction_penalty": ranking.contradiction_penalty,
                "memory_previous_quality_penalty": ranking.previous_quality_penalty,
                "memory_structured_adjustment": ranking.final_adjustment(),
            },
            source="intelligence_memory",
            metadata={"structured_memory_features_used": True},
        )


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
