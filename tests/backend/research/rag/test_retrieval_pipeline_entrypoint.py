from __future__ import annotations

from typing import Any

from backend.research.document.models import PaperChunk
from backend.research.rag.retrieval import RetrievalPipeline
from backend.research.rag.retrieval.paper_retriever import (
    ResearchRetriever,
    RetrievalRequest,
    RetrievalResult,
)


def _chunk(chunk_id: str = "para-1") -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type="paragraph",
        section_title="Method",
        section_role=["method"],
        section_index=1,
        content="The method uses attention.",
        metadata={},
    )


class _Store:
    def __init__(self) -> None:
        self.chunk = _chunk()

    def ensure_collection(self) -> None:
        return None

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        return [self.chunk]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        return [(self.chunk, 1.0)]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        return self.chunk if chunk_id == self.chunk.chunk_id else None

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return None

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        return [self.chunk] if paper_id == "p1" else []


class _FakePipeline:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result
        self.requests: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.requests.append(request)
        return self.result


def test_research_retriever_delegates_to_configured_pipeline() -> None:
    expected = RetrievalResult(
        parent_chunks=[],
        child_chunks=[_chunk("delegated")],
        ref_chunks=[],
        intent="concept_method",
        metadata={"pipeline": "fake"},
    )
    retriever = ResearchRetriever(_Store())  # type: ignore[arg-type]
    fake_pipeline = _FakePipeline(expected)
    retriever._pipeline = fake_pipeline  # type: ignore[attr-defined]
    request = RetrievalRequest(paper_id="p1", question="how does it work?")

    result = retriever.retrieve(request)

    assert result is expected
    assert fake_pipeline.requests == [request]


def test_retrieval_package_exports_pipeline() -> None:
    assert RetrievalPipeline.__name__ == "RetrievalPipeline"
