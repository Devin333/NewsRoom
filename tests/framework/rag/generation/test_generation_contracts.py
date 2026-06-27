from __future__ import annotations

from framework.rag.generation import (
    GeneratedRAGAnswer,
    RAGGenerationContext,
    build_numbered_context_prompt,
    cited_context_indexes,
)


def test_generation_contracts_serialize_context_and_answer():
    context = RAGGenerationContext(context_id="chunk-1", text="Context.", metadata={"bucket": "child"})
    answer = GeneratedRAGAnswer(
        question="Q?",
        answer="A. [1]",
        context_ids=("chunk-1",),
        contexts=("Context.",),
        metadata={"source": "test"},
    )

    assert context.to_dict() == {
        "context_id": "chunk-1",
        "text": "Context.",
        "metadata": {"bucket": "child"},
    }
    assert answer.to_dict()["context_ids"] == ["chunk-1"]


def test_build_numbered_context_prompt_uses_grounding_instruction_and_citations():
    prompt = build_numbered_context_prompt(
        question="What happened?",
        contexts=["First context.", "Second context."],
    )

    assert "Answer ONLY from the numbered context passages below." in prompt
    assert "[1] First context." in prompt
    assert "[2] Second context." in prompt
    assert "Question: What happened?" in prompt
    assert prompt.endswith("Answer (with citations):")


def test_cited_context_indexes_returns_unique_valid_zero_based_indexes():
    assert cited_context_indexes("Use [2], [1], [2], and [9].", context_count=3) == (1, 0)
