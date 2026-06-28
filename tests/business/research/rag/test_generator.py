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


def test_answer_generator_falls_back_when_llm_returns_unrelated_uncited_text() -> None:
    async def fake_llm(prompt: str) -> str:
        return '{"suppress_yolo_no_helmet":true,"hazard_summary":"unrelated"}'

    paragraph = _chunk(
        "claim-para",
        "paragraph",
        "Large language models trained on web-scale datasets support zero-shot generalization.",
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[paragraph],
        ref_chunks=[],
        intent="citation_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "Which evidence supports the claim about web-scale language models?",
        retrieval,
    ))

    assert "Large language models trained on web-scale datasets" in answer.answer
    assert "[1]" in answer.answer
    assert answer.context_metadata["answer_repair_reasons"] == ["extractive_fallback"]


def test_answer_generator_appends_missing_required_context_citation() -> None:
    async def fake_llm(prompt: str) -> str:
        return "The table shows higher accuracy. [1]"

    table = _chunk("table-1", "table", "Table 1 reports accuracy.")
    result = _chunk("result-para", "paragraph", "The result paragraph says accuracy improves over baseline.")
    retrieval = RetrievalResult(
        parent_chunks=[result],
        child_chunks=[table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "What do the experimental results show?",
        retrieval,
        required_context_ids=["table-1", "result-para"],
    ))

    assert "[1]" in answer.answer
    assert "[2]" in answer.answer
    assert "accuracy improves over baseline" in answer.answer
    assert "required_citation_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_appends_citation_claim_when_answer_paraphrases_support() -> None:
    async def fake_llm(prompt: str) -> str:
        return (
            "The support is that these models generalize beyond training data "
            "and perform well in few-shot settings. [1]"
        )

    paragraph = _chunk(
        "claim-para",
        "paragraph",
        (
            "Large language models pre-trained on web-scale datasets are "
            "revolutionizing NLP with strong zero-shot and few-shot generalization. "
            "These foundation models can transfer to many downstream tasks."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[paragraph],
        ref_chunks=[],
        intent="citation_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        (
            "Which evidence supports the claim: Large language models pre-trained "
            "on web-scale datasets are revolutionizing NLP with strong zero-shot "
            "and few-shot generalization."
        ),
        retrieval,
        required_context_ids=["claim-para"],
    ))

    assert "Large language models pre-trained on web-scale datasets" in answer.answer
    assert "[1]" in answer.answer
    assert "citation_claim_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_appends_formula_anchor_when_answer_uses_neighbor_formula() -> None:
    async def fake_llm(prompt: str) -> str:
        return "The equation builds q, k, and v vectors from token embeddings. [2]"

    target = _chunk(
        "eq-attn",
        "formula",
        (
            "Title: Preliminary Equation: a_{m,n}=exp(q_m k_n / sqrt(d)) / "
            "sum_j exp(q_m k_j / sqrt(d)); o_m=sum_n a_{m,n} v_n"
        ),
    )
    neighbor = _chunk(
        "eq-qkv",
        "formula",
        "Title: Preliminary Equation: q_m=f_q(x_m,m); k_n=f_k(x_n,n); v_n=f_v(x_n,n)",
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[target, neighbor],
        ref_chunks=[],
        intent="formula_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "What does Equation 8bb3508a510a mean in this paper?",
        retrieval,
        required_context_ids=["eq-attn"],
    ))

    assert "a_{m,n}" in answer.answer
    assert "o_m=sum_n" in answer.answer
    assert "[1]" in answer.answer
    assert "token embeddings" not in answer.answer
    assert "formula_anchor_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_appends_table_anchor_when_answer_uses_neighbor_formula() -> None:
    async def fake_llm(prompt: str) -> str:
        return "Equation 8bb3508a510a explains attention weights from q and k vectors. [2]"

    target_table = _chunk(
        "table-4",
        "table",
        (
            "Table 4: Pre-training strategy of RoFormer on Chinese dataset. "
            "The training procedure is divided into consecutive stages. "
            "Stage Max seq length Batch size Training steps Loss Accuracy "
            "1 512 256 200k 1.73 65.0% 5 1536 256 10k 1.58 67.4%."
        ),
    )
    neighbor_formula = _chunk(
        "eq-attn",
        "formula",
        "Equation: a_{m,n}=exp(q_m k_n / sqrt(d)); o_m=sum_n a_{m,n} v_n",
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[target_table, neighbor_formula],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        (
            "What do the experiment results around Table 4, about Pre-training "
            "strategy of RoFormer on Chinese dataset, show overall?"
        ),
        retrieval,
        required_context_ids=["table-4"],
    ))

    assert "Pre-training strategy of RoFormer" in answer.answer
    assert "Stage Max seq length" in answer.answer
    assert "[1]" in answer.answer
    assert "Equation 8bb3508a510a" not in answer.answer
    assert "table_anchor_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_does_not_add_table_anchor_when_answer_matches_table() -> None:
    async def fake_llm(prompt: str) -> str:
        return (
            "The RoFormer pre-training strategy uses multiple training stages "
            "with different sequence lengths, batch sizes, losses, and accuracy values. [1]"
        )

    target_table = _chunk(
        "table-4",
        "table",
        (
            "Table 4: Pre-training strategy of RoFormer on Chinese dataset. "
            "Stage Max seq length Batch size Training steps Loss Accuracy."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[target_table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        (
            "What do the experiment results around Table 4, about Pre-training "
            "strategy of RoFormer on Chinese dataset, show overall?"
        ),
        retrieval,
        required_context_ids=["table-4"],
    ))

    assert answer.context_metadata["answer_repair_reasons"] == []


def test_answer_generator_appends_table_caption_when_answer_misses_caption_semantics() -> None:
    async def fake_llm(prompt: str) -> str:
        return (
            "The best score is 99.8 for Mamba with S6, while weaker pairings "
            "score much lower. [1]"
        )

    table = _chunk(
        "table-selective-copying",
        "table",
        (
            "Caption: Table 1: (Selective Copying.) Accuracy for combinations "
            "of architectures and inner sequence layers. Rows: S4 18.3; "
            "Mamba S6 99.8."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[table],
        ref_chunks=[],
        intent="table_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "What do the experimental results around Table 1 show?",
        retrieval,
        required_context_ids=["table-selective-copying"],
    ))

    assert "Selective Copying" in answer.answer
    assert "inner sequence layers" in answer.answer
    assert "[1]" in answer.answer
    assert "table_caption_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_abstains_for_negative_presence_question() -> None:
    async def fake_llm(prompt: str) -> str:
        return "The paper discusses a future model. [1]"

    paragraph = _chunk("para-1", "paragraph", "The paper discusses rotary position embeddings.")
    retrieval = RetrievalResult(
        parent_chunks=[],
        child_chunks=[paragraph],
        ref_chunks=[],
        intent="concept_method",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "Does this paper discuss an unrelated future model not present in the text?",
        retrieval,
    ))

    assert "does not mention" in answer.answer
    assert answer.context_metadata["answer_repair_reasons"] == ["negative_abstention_fallback"]


def test_answer_generator_adds_formula_explanation_excerpt_from_required_contexts() -> None:
    async def fake_llm(prompt: str) -> str:
        return "The equation defines q, k, and v projections. [1]"

    formula = _chunk(
        "eq-qkv",
        "formula",
        "Equation: q_m=f_q(x_m,m); k_n=f_k(x_n,n); v_n=f_v(x_n,n)",
    )
    explanation = _chunk(
        "para-qkv",
        "paragraph",
        (
            "where q_m, k_n and v_n incorporate the mth and nth positions through "
            "f_q, f_k and f_v, respectively. The query and key values are then used "
            "to compute attention weights, while the output is a weighted sum."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[explanation],
        child_chunks=[formula],
        ref_chunks=[],
        intent="formula_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "How is Equation 5e7b4a508e19 explained in the surrounding text?",
        retrieval,
        required_context_ids=["eq-qkv", "para-qkv"],
    ))

    assert "attention weights" in answer.answer
    assert "weighted sum" in answer.answer
    assert "[2]" in answer.answer
    assert "required_citation_excerpt" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_extractive_fallback_preserves_formula_explanation_text() -> None:
    async def fake_llm(prompt: str) -> str:
        return ""

    formula = _chunk(
        "eq-pos",
        "formula",
        "Equation: f_t(x_i,i):=W_t(x_i+p_i)",
    )
    explanation = _chunk(
        "para-pos",
        "paragraph",
        (
            "A typical choice uses a trainable position vector p_i. "
            "Previous work introduced the use of a set of trainable vectors "
            "p_i in {p_t}_{t=1}^{L}, where L is the maximum sequence length."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[explanation],
        child_chunks=[formula],
        ref_chunks=[],
        intent="formula_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "How is Equation dd7633a3523b explained in the surrounding text?",
        retrieval,
        required_context_ids=["eq-pos", "para-pos"],
    ))

    assert "Previous work introduced" in answer.answer
    assert "maximum sequence length" in answer.answer
    assert "[2]" in answer.answer
    assert "extractive_fallback" in answer.context_metadata["answer_repair_reasons"]


def test_answer_generator_extractive_fallback_preserves_preferred_response_definition() -> None:
    async def fake_llm(prompt: str) -> str:
        return ""

    formula = _chunk(
        "eq-ranking",
        "formula",
        (
            "Equation: L_ranking=-log(sigma(r_theta(x,y_c)-"
            "r_theta(x,y_r)-m(r)))"
        ),
    )
    explanation = _chunk(
        "para-ranking",
        "paragraph",
        (
            "Equation: L_ranking=-log(sigma(r_theta(x,y_c)-r_theta(x,y_r)-m(r))). "
            "$y_{c}$ is the preferred response that annotators choose and $y_{r}$ "
            "is the rejected counterpart. Built on top of this binary ranking loss, "
            "the margin $m(r)$ is a discrete function of the preference rating."
        ),
    )
    retrieval = RetrievalResult(
        parent_chunks=[explanation],
        child_chunks=[formula],
        ref_chunks=[],
        intent="formula_query",  # type: ignore[arg-type]
    )

    answer = asyncio.run(AnswerGenerator(fake_llm).generate(
        "How is Equation a3028792cf7f explained in the surrounding text?",
        retrieval,
        required_context_ids=["eq-ranking", "para-ranking"],
    ))

    assert "preferred response that annotators choose" in answer.answer
    assert "rejected counterpart" in answer.answer
    assert "[2]" in answer.answer
    assert "extractive_fallback" in answer.context_metadata["answer_repair_reasons"]


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
