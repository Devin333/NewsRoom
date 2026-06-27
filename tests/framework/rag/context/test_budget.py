from __future__ import annotations

from framework.rag.context import ContextBudget, trim_evidence_to_budget
from framework.rag.core import RAGEvidence, SourceLocator


def _evidence(evidence_id: str, text: str) -> RAGEvidence:
    return RAGEvidence(
        evidence_id=evidence_id,
        chunk_id=evidence_id,
        document_id="doc-1",
        text=text,
        source_locator=SourceLocator(source_id=f"source://{evidence_id}"),
        metadata={"source_locator": f"source://{evidence_id}"},
    )


def test_trim_evidence_to_budget_preserves_selected_evidence_provenance():
    first = _evidence("ev-1", "12345")
    second = _evidence("ev-2", "123456")
    third = _evidence("ev-3", "12")

    out = trim_evidence_to_budget(
        [first, second, third],
        ContextBudget(max_items=2, max_text_chars=8),
    )

    assert out == [first, third]
    assert out[0].source_locator is first.source_locator
    assert out[0].metadata == first.metadata
