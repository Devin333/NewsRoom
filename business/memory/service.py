from __future__ import annotations

from business.foundation import BoardCard, BoardType
from business.memory.duplicate_detection import estimate_historical_duplicate_score
from business.memory.features import build_memory_feature_vector
from business.memory.feedback_memory import estimate_previous_misrank_penalty
from business.memory.models import BusinessMemoryContext
from business.memory.recall import BusinessMemoryRecallService
from business.memory.source_reliability import estimate_source_reliability, source_noise_penalty
from business.memory.topic_momentum import estimate_topic_momentum
from framework.scoring import FeatureVector


class BusinessMemoryDecisionService:
    def __init__(self, recall_service: BusinessMemoryRecallService | None = None) -> None:
        self.recall_service = recall_service or BusinessMemoryRecallService()

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
        return build_memory_feature_vector(self.memory_context_for_card(card, board_type=board_type))
