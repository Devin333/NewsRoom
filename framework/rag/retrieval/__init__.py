from __future__ import annotations

from framework.rag.retrieval.dedup import dedupe_by_key, dedupe_evidence, order_evidence
from framework.rag.retrieval.expansion import ExpansionMetadata, expansion_metadata
from framework.rag.retrieval.field_score import FieldScoreResult, score_fields
from framework.rag.retrieval.rerank import RerankScoreSet, rerank_sort_key
from framework.rag.retrieval.scoring import (
    RAGScoringWeights,
    fuse_score,
    normalize_score_weights,
    score_evidence,
    weighted_component_score,
)

__all__ = [
    "ExpansionMetadata",
    "FieldScoreResult",
    "RAGScoringWeights",
    "RerankScoreSet",
    "dedupe_by_key",
    "dedupe_evidence",
    "expansion_metadata",
    "fuse_score",
    "normalize_score_weights",
    "order_evidence",
    "rerank_sort_key",
    "score_evidence",
    "score_fields",
    "weighted_component_score",
]
