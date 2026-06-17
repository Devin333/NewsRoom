from __future__ import annotations

from dataclasses import dataclass

from framework.harness.retrieval.request import RetrievalRequest

from business.research.document.models import PaperChunk
from business.research.rag.retrieval_port import PaperChunkRetrievalPort
from business.research.rag.retriever import RetrievalResult


@dataclass
class _SpyRetriever:
    """Records the section_index it was asked to retrieve with."""
    seen_section_index: int | None = None

    def retrieve(self, request) -> RetrievalResult:
        self.seen_section_index = request.current_section_index
        chunk = PaperChunk(
            chunk_id="c1",
            paper_id=request.paper_id,
            parse_source="latex",
            chunk_type="paragraph",
            section_title="Method",
            section_role=["method"],
            section_index=request.current_section_index,
            content="content",
            metadata={"source_ref": f"arxiv://{request.paper_id}/c1"},
        )
        return RetrievalResult(parent_chunks=[chunk], child_chunks=[chunk], ref_chunks=[], intent="concept_method")


def _request(metadata: dict | None = None) -> RetrievalRequest:
    return RetrievalRequest(
        query="how does attention work",
        scope="default",
        context_refs=("arxiv://1706.03762/latex",),
        limit=5,
        metadata=metadata or {},
    )


def test_request_metadata_takes_precedence():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=2)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": 7}))
    assert spy.seen_section_index == 7


def test_falls_back_to_default_when_metadata_absent():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=4)  # type: ignore[arg-type]
    port.retrieve(_request({}))
    assert spy.seen_section_index == 4


def test_invalid_metadata_falls_back_to_default():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=3)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": "bad"}))
    assert spy.seen_section_index == 3


def test_negative_metadata_falls_back_to_default():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=6)  # type: ignore[arg-type]
    port.retrieve(_request({"current_section_index": -1}))
    assert spy.seen_section_index == 6


def test_default_zero_when_nothing_provided():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    port.retrieve(_request({}))
    assert spy.seen_section_index == 0


def test_paper_id_extracted_from_context_refs():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))
    assert result.packs
    assert result.packs[0].lineage == ("1706.03762",)


def test_section_index_echoed_in_collection_metadata():
    spy = _SpyRetriever()
    port = PaperChunkRetrievalPort(spy, default_section_index=5)  # type: ignore[arg-type]
    result = port.retrieve(_request({}))
    assert result.metadata["section_index"] == 5
