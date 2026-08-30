from __future__ import annotations

import pytest

from backend.research.rag.adapters import RerankerRelevanceScorer


def test_reranker_relevance_scorer_sigmoid_normalizes_scores() -> None:
    scorer = RerankerRelevanceScorer(_Reranker((-2.0, 0.0, 2.0)))

    scores = scorer.score("question", ["low", "mid", "high"])

    assert scores == pytest.approx([0.1192029, 0.5, 0.8807971])


def test_reranker_relevance_scorer_handles_empty_passages_without_calling_reranker() -> None:
    reranker = _Reranker((1.0,))
    scorer = RerankerRelevanceScorer(reranker)

    assert scorer.score("question", []) == []
    assert reranker.calls == []


def test_reranker_relevance_scorer_rejects_invalid_scale() -> None:
    with pytest.raises(ValueError, match="scale"):
        RerankerRelevanceScorer(_Reranker((1.0,)), scale=0)


class _Reranker:
    def __init__(self, scores: tuple[float, ...]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, passages))
        return list(self.scores)
