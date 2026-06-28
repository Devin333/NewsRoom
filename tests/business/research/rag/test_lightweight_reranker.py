from __future__ import annotations

from business.research.rag.retrieval.paper_lightweight_reranker import LightweightLexicalReranker


def test_lightweight_lexical_reranker_prefers_content_overlap() -> None:
    reranker = LightweightLexicalReranker()

    scores = reranker.score(
        "What quantitative evidence reports BLEU on WMT14?",
        [
            "Method details about encoder layers.",
            "Table rows: WMT14 BLEU quantitative evidence improves over baseline.",
        ],
    )

    assert len(scores) == 2
    assert scores[1] > scores[0]
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_lightweight_lexical_reranker_returns_zero_without_query_terms() -> None:
    reranker = LightweightLexicalReranker()

    assert reranker.score("what does it show", ["Any passage"]) == [0.0]
