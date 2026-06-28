from __future__ import annotations

import asyncio

from business.research.document.models import PaperChunk
from business.research.rag.retrieval.paper_answer_generator import AnswerContextAssembler, AnswerGenerator
from business.research.rag.retrieval.paper_retriever import RetrievalResult


def test_answer_context_assembler_interleaves_related_context() -> None:
    figure = _chunk(
        "fig-1",
        "figure",
        "[Figure 1] Caption: architecture.",
        metadata={"nearby_context_chunk_id": "para-near"},
    )
    unrelated = _chunk("para-other", "paragraph", "Other paragraph.")
    nearby = _chunk("para-near", "paragraph", "Figure 1 explains the architecture.")
    parent = _chunk("section-parent", "paragraph", "Parent section.")
    retrieval = RetrievalResult(
        parent_chunks=[nearby, parent],
        child_chunks=[figure, unrelated],
        ref_chunks=[],
        intent="figure_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=3).select(retrieval)

    assert [chunk.chunk_id for chunk in selection.chunks] == ["fig-1", "para-near", "para-other"]
    assert selection.metadata["context_source_buckets"] == {
        "fig-1": "child",
        "para-near": "parent",
        "para-other": "child",
    }
    assert selection.metadata["related_context_ids"] == ["para-near"]


def test_answer_context_assembler_uses_ref_chunks_before_leftover_candidates() -> None:
    table = _chunk(
        "table-1",
        "table",
        "[Table 1] Caption: results.",
        metadata={"referenced_by_chunks": [{"chunk_id": "result-para"}]},
    )
    result_para = _chunk("result-para", "paragraph", "The results improve accuracy.")
    other = _chunk("other", "paragraph", "Other paragraph.")
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[table, other],
        ref_chunks=[result_para],
        intent="table_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=3).select(retrieval)

    assert [chunk.chunk_id for chunk in selection.chunks] == ["table-1", "result-para", "other"]


def test_answer_context_assembler_prioritizes_required_context_ids() -> None:
    wrong_table = _chunk("table-wrong", "table", "[Table 3] Other reward model results.")
    target_table = _chunk(
        "table-target",
        "table",
        "[Table 3] Overall performance on grouped academic benchmarks.",
        metadata={"nearby_context_chunk_id": "target-result"},
    )
    target_result = _chunk("target-result", "paragraph", "The grouped benchmark results improve overall.")
    retrieval = RetrievalResult(
        parent_chunks=[target_result],
        child_chunks=[wrong_table, target_table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=3).select(
        retrieval,
        required_context_ids=["table-target", "target-result"],
    )

    assert [chunk.chunk_id for chunk in selection.chunks] == [
        "table-target",
        "target-result",
        "table-wrong",
    ]
    assert selection.metadata["required_context_ids"] == ["table-target", "target-result"]
    assert selection.metadata["selected_required_context_ids"] == ["table-target", "target-result"]
    assert selection.metadata["missing_required_context_ids"] == []
    assert selection.metadata["required_context_coverage"] == 1.0


def test_answer_context_assembler_records_missing_required_context_ids() -> None:
    table = _chunk("table-1", "table", "[Table 1] Results.")
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    selection = AnswerContextAssembler(max_context_chunks=2).select(
        retrieval,
        required_context_ids=["table-1", "missing-para"],
    )

    assert [chunk.chunk_id for chunk in selection.chunks] == ["table-1"]
    assert selection.metadata["selected_required_context_ids"] == ["table-1"]
    assert selection.metadata["missing_required_context_ids"] == ["missing-para"]
    assert selection.metadata["required_context_coverage"] == 0.5


def test_answer_generator_prompt_adds_table_result_instructions() -> None:
    async def fake_llm(prompt: str) -> str:
        return prompt

    generator = AnswerGenerator(fake_llm)

    prompt = generator._build_prompt(
        "What do the experiment results around Table 5 show overall?",
        ["Table 5 lists NLU and NLG averages."],
    )

    assert "concrete metrics" in prompt
    assert "averages" in prompt
    assert "deltas" in prompt


def test_answer_generator_context_includes_structured_metadata_fields() -> None:
    async def fake_llm(prompt: str) -> str:
        return prompt

    table = _chunk(
        "table-1",
        "table",
        "[Table 5] Caption: Raw benchmark rows. Rows: " + "x " * 900,
        metadata={
            "caption_text": (
                "Table 5 lists NLU and NLG averages. PaLM 540B improves the "
                "average score in both categories by more than 5 points."
            ),
            "table_text": "Task | Prior | PaLM\nAverage NLU | 70 | 76",
        },
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(
        fake_llm,
        max_context_chunks=1,
        max_chars_per_chunk=500,
    ).generate("What do the experiment results around Table 5 show?", retrieval))

    assert "PaLM 540B improves the average score" in answer.contexts[0]
    assert "Average NLU" in answer.contexts[0]


def _chunk(
    chunk_id: str,
    chunk_type: str,
    content: str,
    *,
    metadata: dict | None = None,
) -> PaperChunk:
    return PaperChunk(
        chunk_id=chunk_id,
        paper_id="p1",
        parse_source="latex",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        content=content,
        metadata=metadata or {},
    )
