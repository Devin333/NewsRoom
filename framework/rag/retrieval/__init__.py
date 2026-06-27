from __future__ import annotations

from framework.rag.retrieval.dedup import dedupe_evidence, order_evidence
from framework.rag.retrieval.field_score import FieldScoreResult, score_fields
from framework.rag.retrieval.scoring import (
    RAGScoringWeights,
    fuse_score,
    normalize_score_weights,
    score_evidence,
    weighted_component_score,
)

__all__ = [
    "FieldScoreResult",
    "RAGScoringWeights",
    "dedupe_evidence",
    "fuse_score",
    "normalize_score_weights",
    "order_evidence",
    "score_evidence",
    "score_fields",
    "weighted_component_score",
]
