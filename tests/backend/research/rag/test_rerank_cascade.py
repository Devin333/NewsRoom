from __future__ import annotations

from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval.paper_retriever import RetrievalPolicy
from backend.research.rag.retrieval.rerank import RerankCascade, field_rerank_passage


def _chunk(
    chunk_id: str,
    *,
    content: str = "The method uses attention.",
    chunk_type: str = "paragraph",
    metadata: dict[str, Any] | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title="Method",
        section_role=["method"],  # type: ignore[arg-type]
        section_index=1,
        content=content,
        metadata=metadata or {},
    )


class _Reranker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, passages))
        return self.scores


class _FailingReranker:
    def score(self, query: str, passages: list[str]) -> list[float]:
        raise RuntimeError("reranker unavailable")


def test_base_scores_fall_back_to_semantic_when_disabled() -> None:
    chunks = [(_chunk("a"), 0.2), (_chunk("b"), 0.7)]
    cascade = RerankCascade(RetrievalPolicy())

    assert cascade.base_scores("how", chunks, intent="concept_method") == [0.2, 0.7]


def test_base_scores_use_reranker_when_enabled_for_intent() -> None:
    chunks = [(_chunk("a"), 0.2), (_chunk("b"), 0.7)]
    reranker = _Reranker([0.9, 0.1])
    cascade = RerankCascade(
        RetrievalPolicy(reranking_intents=("concept_method",)),
        reranker=reranker,
    )

    assert cascade.base_scores("how", chunks, intent="concept_method") == [0.9, 0.1]
    assert reranker.calls[0][1] == ["The method uses attention.", "The method uses attention."]


def test_base_scores_fall_back_on_failure_or_malformed_count() -> None:
    chunks = [(_chunk("a"), 0.2), (_chunk("b"), 0.7)]

    failing = RerankCascade(
        RetrievalPolicy(reranking_intents=("concept_method",)),
        reranker=_FailingReranker(),
    )
    malformed = RerankCascade(
        RetrievalPolicy(reranking_intents=("concept_method",)),
        reranker=_Reranker([0.4]),
    )

    assert failing.base_scores("how", chunks, intent="concept_method") == [0.2, 0.7]
    assert malformed.base_scores("how", chunks, intent="concept_method") == [0.2, 0.7]


def test_field_scores_return_chunk_id_map_when_enabled() -> None:
    chunks = [
        _chunk("a", content="weak field"),
        _chunk("b", content="strong field"),
    ]
    reranker = _Reranker([0.1, 0.95])
    cascade = RerankCascade(
        RetrievalPolicy(field_reranking_intents=("concept_method",)),
        field_reranker=reranker,
    )

    assert cascade.field_scores("how", chunks, intent="concept_method") == {
        "a": 0.1,
        "b": 0.95,
    }
    assert "Body:" in reranker.calls[0][1][0]


def test_field_scores_fall_back_to_empty_map_when_disabled_or_malformed() -> None:
    chunks = [_chunk("a"), _chunk("b")]
    unavailable = RerankCascade(RetrievalPolicy())
    malformed = RerankCascade(
        RetrievalPolicy(field_reranking_intents=("concept_method",)),
        field_reranker=_Reranker([0.1]),
    )

    assert unavailable.field_scores("how", chunks, intent="concept_method") == {}
    assert malformed.field_scores("how", chunks, intent="concept_method") == {}


def test_field_rerank_passage_includes_structured_fields() -> None:
    chunk = _chunk(
        "tbl",
        chunk_type="table",
        content="[Table 1]\nCaption: Accuracy results.\nRows: ours 95.",
        metadata={
            "caption_text": "Accuracy results.",
            "rows": [{"model": "ours", "accuracy": "95"}],
            "columns": ["model", "accuracy"],
            "visual_description": "A table comparing model accuracy.",
            "referenced_text": ["The result paragraph discusses the table."],
        },
    ).model_copy(update={"formula_latex": "s = x + y", "has_formula": True})

    passage = field_rerank_passage(chunk)

    assert "Section: Method" in passage
    assert "Chunk type: table" in passage
    assert "Caption:" in passage
    assert "Equation:" in passage
    assert "Table rows:" in passage
    assert "Table columns:" in passage
    assert "Visual description:" in passage
    assert "Referenced text:" in passage
    assert "Body:" in passage
