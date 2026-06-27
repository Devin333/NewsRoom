from __future__ import annotations

from framework.rag.retrieval import RerankScoreSet, rerank_sort_key


def test_rerank_score_set_clamps_scores_and_maps_ids():
    scores = RerankScoreSet.from_raw([1.2, "-0.5", "0.7"], expected_count=3)

    assert scores is not None
    assert scores.scores == (1.0, 0.0, 0.7)
    assert scores.as_id_map(["a", "b", "c"]) == {"a": 1.0, "b": 0.0, "c": 0.7}


def test_rerank_score_set_rejects_length_mismatch():
    assert RerankScoreSet.from_raw([0.9], expected_count=2) is None


def test_rerank_score_set_returns_indexes_above_threshold():
    scores = RerankScoreSet(scores=(0.9, 0.2, 0.5))

    assert scores.keep_indexes(threshold=0.5) == (0, 2)


def test_rerank_sort_key_orders_by_rerank_then_priority_then_fallback():
    rows = [
        ("weak-priority", rerank_sort_key(rerank_score=0.8, priority=(1, 0), fallback_score=0.9)),
        ("strong-score", rerank_sort_key(rerank_score=0.9, priority=(9, 9), fallback_score=0.1)),
        ("strong-priority", rerank_sort_key(rerank_score=0.8, priority=(0, 0), fallback_score=0.1)),
    ]

    assert [name for name, _key in sorted(rows, key=lambda item: item[1])] == [
        "strong-score",
        "strong-priority",
        "weak-priority",
    ]
