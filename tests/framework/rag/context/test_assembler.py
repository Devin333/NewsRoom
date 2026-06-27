from __future__ import annotations

from framework.rag.context import ContextBudget, RAGContextAssembler
from framework.rag.core import RAGEvidence, RAGQuery, SourceLocator


def _evidence(evidence_id: str, chunk_id: str, score: float, text: str = "text") -> RAGEvidence:
    return RAGEvidence(
        evidence_id=evidence_id,
        chunk_id=chunk_id,
        document_id="doc-1",
        text=text,
        score=score,
        source_locator=SourceLocator(source_id=f"source://{evidence_id}"),
        metadata={"marker": evidence_id},
    )


def test_context_assembler_sorts_dedupes_and_applies_budget_without_mutating_evidence():
    low_duplicate = _evidence("ev-low", "chunk-1", 0.1)
    high_duplicate = _evidence("ev-high", "chunk-1", 0.9)
    other = _evidence("ev-other", "chunk-2", 0.8)
    dropped_by_budget = _evidence("ev-drop", "chunk-3", 0.7)

    assembler = RAGContextAssembler(budget=ContextBudget(max_items=2))
    out = assembler.assemble(
        RAGQuery(query="question"),
        [low_duplicate, other, dropped_by_budget, high_duplicate],
    )

    assert out == [high_duplicate, other]
    assert out[0].metadata == {"marker": "ev-high"}
    assert out[0].source_locator is high_duplicate.source_locator
