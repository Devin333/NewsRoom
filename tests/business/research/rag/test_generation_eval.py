from __future__ import annotations

import asyncio
import json

from business.research.rag.evaluation.paper_generation_eval import GenerationEvaluator
from business.research.rag.retrieval.paper_answer_generator import GeneratedAnswer


def test_generation_evaluator_parses_claim_level_json_and_citation_grounding() -> None:
    async def judge(_prompt: str) -> str:
        return json.dumps({
            "claims": [
                {
                    "claim_text": "Model A reaches 95 accuracy [1].",
                    "verdict": "supported",
                    "support_chunk_ids": ["tbl-1"],
                    "reason": "The table reports 95 accuracy.",
                },
                {
                    "claim_text": "Model B is worse [2].",
                    "verdict": "insufficient",
                    "support_chunk_ids": [],
                    "reason": "The context does not compare Model B.",
                },
            ],
            "citation_checks": [
                {
                    "claim_text": "Model A reaches 95 accuracy [1].",
                    "cited_chunk_ids": ["tbl-1"],
                    "support_chunk_ids": ["tbl-1"],
                    "citation_supports_claim": True,
                    "wrong_citation": False,
                    "missing_citation": False,
                    "reason": "Correct citation.",
                },
                {
                    "claim_text": "Model B is worse [2].",
                    "cited_chunk_ids": ["para-1"],
                    "support_chunk_ids": ["tbl-1"],
                    "citation_supports_claim": False,
                    "wrong_citation": True,
                    "missing_citation": False,
                    "reason": "The cited paragraph does not support the claim.",
                },
            ],
            "answer_relevance": 0.8,
            "context_precision": 0.75,
        })

    answer = GeneratedAnswer(
        question="What do the results show?",
        answer="Model A reaches 95 accuracy [1]. Model B is worse [2].",
        context_chunk_ids=["tbl-1", "para-1"],
        contexts=["Rows: Model A | 95 accuracy", "Related work paragraph."],
    )

    result = asyncio.run(GenerationEvaluator(judge).evaluate([answer]))
    judgment = result.sample_judgments[0]

    assert result.claim_support_rate_score() == 0.5
    assert result.unsupported_claim_rate_score() == 0.5
    assert result.citation_claim_support_rate_score() == 0.5
    assert result.wrong_citation_rate_score() == 0.5
    assert judgment.claims[0].support_chunk_ids == ("tbl-1",)
    assert judgment.citation_checks[1].wrong_citation is True


def test_generation_evaluator_reports_judge_error_on_malformed_json() -> None:
    async def judge(_prompt: str) -> str:
        return "not json"

    answer = GeneratedAnswer(
        question="What is stated?",
        answer="The answer states a fact.",
        context_chunk_ids=["para-1"],
        contexts=["Context."],
    )

    result = asyncio.run(GenerationEvaluator(judge).evaluate([answer]))

    assert result.judge_error_rate() == 1.0
    assert result.per_sample[0].judge_error is True
    assert result.sample_judgments[0].status == "error"


def test_generation_evaluator_falls_back_to_missing_citation_when_claim_has_support_but_no_citation() -> None:
    async def judge(_prompt: str) -> str:
        return json.dumps({
            "claims": [
                {
                    "claim_text": "The method improves accuracy.",
                    "verdict": "supported",
                    "support_chunk_ids": ["para-1"],
                    "reason": "The paragraph says this.",
                }
            ],
            "answer_relevance": 1.0,
            "context_precision": 1.0,
        })

    answer = GeneratedAnswer(
        question="What improves?",
        answer="The method improves accuracy.",
        context_chunk_ids=["para-1"],
        contexts=["The method improves accuracy."],
    )

    result = asyncio.run(GenerationEvaluator(judge).evaluate([answer]))

    assert result.missing_citation_rate_score() == 1.0
    assert result.citation_claim_support_rate_score() == 0.0
