from __future__ import annotations

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.paper_claim_index import PaperClaimIndex, extract_claim_records


def test_extract_claim_records_from_abstract_and_maps_to_source_chunk() -> None:
    chunk = _chunk(
        "abs-1",
        chunk_type="abstract",
        section_title="Abstract",
        content=(
            "We introduce a controllable retrieval model for scientific papers. "
            "The appendix lists prompts and examples."
        ),
        metadata={"source_locator": "paper://p1/abstract"},
    )

    records = extract_claim_records(chunk)

    assert len(records) == 1
    assert records[0].chunk_id == "abs-1"
    assert records[0].claim_id.startswith("claim_")
    assert records[0].claim_type == "abstract_claim"
    assert records[0].source_locator == "paper://p1/abstract"


def test_claim_index_search_returns_best_claim_hit() -> None:
    claim_chunk = _chunk(
        "para-claim",
        section_title="Introduction",
        content=(
            "Large language models pre-trained on web-scale datasets are "
            "revolutionizing NLP with strong zero-shot and few-shot generalization."
        ),
    )
    unrelated = _chunk(
        "para-other",
        section_title="Related Work",
        content="Segmentation datasets contain masks, labels, and image prompts.",
    )
    index = PaperClaimIndex.from_chunks([unrelated, claim_chunk])

    hits = index.search_claims(
        "p1",
        "Which passage grounds the claim about zero-shot and few-shot generalization?",
        limit=3,
    )

    assert hits
    assert hits[0].record.chunk_id == "para-claim"
    assert hits[0].score > 0


def _chunk(
    chunk_id: str,
    *,
    chunk_type: str = "paragraph",
    section_title: str = "Introduction",
    content: str,
    metadata: dict | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        section_title=section_title,
        section_role=["background"],  # type: ignore[list-item]
        content=content,
        metadata=metadata or {},
    )
