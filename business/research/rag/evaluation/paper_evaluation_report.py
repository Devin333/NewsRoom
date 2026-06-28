from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.rag.evaluation import RAGEvaluationReport, summarize_score_breakdowns

from business.research.rag.adapters.evaluation_scorecard_adapter import evidence_results_to_rag_report
from business.research.rag.evaluation.paper_answer_eval import EvidenceAnswerEvalResult
from business.research.rag.evaluation.paper_evaluation_compare import EvidenceABResult
from business.research.rag.evaluation.paper_evidence_eval import EvidenceEvalResult, iter_ranked_score_breakdowns
from business.research.rag.evaluation.paper_generation_eval import GenerationEvalResult


@dataclass
class EvidenceRegressionReport:
    retrieval: EvidenceEvalResult | None = None
    answer: EvidenceAnswerEvalResult | None = None
    generation: GenerationEvalResult | None = None
    ab: EvidenceABResult | None = None
    thresholds: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metadata": dict(self.metadata),
            "thresholds": dict(self.thresholds),
            "passed": self.passed(),
            "issues": self.issues(),
            "rag_evaluation_report": self.to_rag_evaluation_report().to_dict(),
        }
        if self.retrieval is not None:
            payload["retrieval"] = _retrieval_result_to_dict(self.retrieval)
        if self.answer is not None:
            payload["answer"] = _answer_result_to_dict(self.answer)
        if self.generation is not None:
            payload["generation"] = _generation_result_to_dict(self.generation)
        if self.ab is not None:
            payload["ab"] = _ab_result_to_dict(self.ab)
        return payload

    def to_markdown(self) -> str:
        lines = ["# Paper RAG Evidence Regression Report", ""]
        lines.extend([
            f"**Status:** {'PASS' if self.passed() else 'FAIL'}",
            "",
        ])
        if self.thresholds:
            lines.extend(["## Thresholds", ""])
            for key in sorted(self.thresholds):
                lines.append(f"- `{key}` >= {self.thresholds[key]:.3f}")
            lines.append("")
        issues = self.issues()
        if issues:
            lines.extend(["## Issues", ""])
            for issue in issues:
                lines.append(f"- {issue}")
            lines.append("")
        if self.metadata:
            lines.extend(["## Metadata", ""])
            for key in sorted(self.metadata):
                lines.append(f"- `{key}`: {self.metadata[key]}")
            lines.append("")
        lines.extend(["## RAG Scorecard", "", _code_block(self.to_rag_evaluation_report().to_markdown()), ""])
        if self.retrieval is not None:
            lines.extend(["## Retrieval", "", _code_block(self.retrieval.report()), ""])
        if self.answer is not None:
            lines.extend(["## Answer", "", _code_block(self.answer.report()), ""])
        if self.generation is not None:
            lines.extend(["## Generation", "", _code_block(self.generation.report()), ""])
        if self.ab is not None:
            lines.extend(["## A/B", "", _code_block(self.ab.report()), ""])
        return "\n".join(lines).rstrip() + "\n"

    def write(self, output_dir: str | Path) -> None:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "evidence_regression_report.json").write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (target / "evidence_regression_report.md").write_text(
            self.to_markdown(),
            encoding="utf-8",
        )

    def to_rag_evaluation_report(self) -> RAGEvaluationReport:
        return evidence_results_to_rag_report(
            retrieval=self.retrieval,
            answer=self.answer,
            generation=self.generation,
            thresholds=self.thresholds,
            metadata=self.metadata,
        )

    def passed(self) -> bool:
        return not self.issues()

    def issues(self) -> list[str]:
        issues: list[str] = []
        values = _threshold_values(self)
        for metric, threshold in self.thresholds.items():
            actual = values.get(metric)
            if actual is None:
                issues.append(f"threshold metric {metric!r} is unavailable")
                continue
            if actual < threshold:
                issues.append(f"{metric}={actual:.3f} is below threshold {threshold:.3f}")
        return issues


def _retrieval_result_to_dict(result: EvidenceEvalResult) -> dict[str, Any]:
    return {
        "total": result.total,
        "answerable_total": result.answerable_total,
        "abstain_total": result.abstain_total,
        "mrr": result.mrr(),
        "by_k": {
            str(k): {
                "hit_rate": result.hit_rate(k),
                "evidence_coverage": result.evidence_coverage(k),
                "required_type_coverage": result.required_type_coverage(k),
                "source_locator_coverage": result.source_locator_coverage(k),
                "citation_accuracy": result.citation_accuracy(k),
                "image_recall": result.image_recall(k),
                "visual_evidence_coverage": result.visual_evidence_coverage(k),
                "over_retrieval_rate": result.over_retrieval_rate(k),
                "ndcg": result.ndcg(k),
            }
            for k in result.ks
        },
        "score_breakdown_summary": _score_breakdown_summary(result),
        "intent_distribution": dict(result.intent_distribution),
        "route_distribution": dict(result.route_distribution),
        "intent_confusion": {
            qa_type: dict(counts)
            for qa_type, counts in sorted(result.intent_confusion.items())
        },
        "by_qa_type": {
            qa_type: _retrieval_result_to_dict(sub)
            for qa_type, sub in result.by_qa_type.items()
        },
    }


def _score_breakdown_summary(result: EvidenceEvalResult) -> dict[str, Any]:
    top_k = max(result.ks) if result.ks else None
    summary = summarize_score_breakdowns(iter_ranked_score_breakdowns(result, top_k=top_k))
    summary["top_k"] = top_k
    return summary


def _answer_result_to_dict(result: EvidenceAnswerEvalResult) -> dict[str, Any]:
    return {
        "total": result.total,
        "answer_fact_coverage": result.answer_fact_coverage(),
        "fact_match_coverage": result.answer_fact_coverage(),
        "retrieval_context_coverage": result.retrieval_context_coverage_score(),
        "citation_grounding_score": result.citation_grounding_score(),
        "citation_gold_coverage": result.citation_gold_coverage_score(),
        "source_locator_grounding_score": result.source_locator_grounding_score(),
        "abstention_accuracy": result.abstention_accuracy(),
        "success_rate": result.success_rate(),
        "failure_reason_counts": result.failure_reason_counts(),
        "by_qa_type": {
            qa_type: _answer_result_to_dict(sub)
            for qa_type, sub in result.by_qa_type.items()
        },
    }


def _generation_result_to_dict(result: GenerationEvalResult) -> dict[str, Any]:
    return {
        "total": len(result.per_sample),
        "faithfulness": result.faithfulness_score(),
        "answer_relevancy": result.answer_relevancy_score(),
        "context_precision": result.context_precision_score(),
        "per_sample": [score.to_dict() for score in result.per_sample],
    }


def _ab_result_to_dict(result: EvidenceABResult) -> dict[str, Any]:
    return {
        "baseline_name": result.baseline_name,
        "candidate_name": result.candidate_name,
        "deltas": [
            {
                "metric": delta.metric,
                "k": delta.k,
                "baseline_value": delta.baseline_value,
                "candidate_value": delta.candidate_value,
                "delta": delta.delta,
            }
            for delta in result.deltas
        ],
    }


def _threshold_values(report: EvidenceRegressionReport) -> dict[str, float]:
    values: dict[str, float] = {}
    if report.retrieval is not None:
        best_k = max(report.retrieval.ks) if report.retrieval.ks else 0
        if best_k:
            values.update({
                "retrieval.hit_rate": report.retrieval.hit_rate(best_k),
                "retrieval.evidence_coverage": report.retrieval.evidence_coverage(best_k),
                "retrieval.required_type_coverage": report.retrieval.required_type_coverage(best_k),
                "retrieval.source_locator_coverage": report.retrieval.source_locator_coverage(best_k),
                "retrieval.citation_accuracy": report.retrieval.citation_accuracy(best_k),
                "retrieval.image_recall": report.retrieval.image_recall(best_k),
            })
        values["retrieval.mrr"] = report.retrieval.mrr()
    if report.answer is not None:
        values.update({
            "answer.fact_coverage": report.answer.answer_fact_coverage(),
            "answer.fact_match_coverage": report.answer.answer_fact_coverage(),
            "answer.retrieval_context_coverage": report.answer.retrieval_context_coverage_score(),
            "answer.citation_grounding": report.answer.citation_grounding_score(),
            "answer.citation_gold_coverage": report.answer.citation_gold_coverage_score(),
            "answer.source_locator_grounding": report.answer.source_locator_grounding_score(),
            "answer.abstention_accuracy": report.answer.abstention_accuracy(),
            "answer.success_rate": report.answer.success_rate(),
        })
    if report.generation is not None:
        values.update({
            "generation.faithfulness": report.generation.faithfulness_score(),
            "generation.answer_relevancy": report.generation.answer_relevancy_score(),
            "generation.context_precision": report.generation.context_precision_score(),
        })
    if report.ab is not None:
        for delta in report.ab.deltas:
            suffix = f"@{delta.k}" if delta.k is not None else ""
            values[f"ab.{delta.metric}{suffix}.delta"] = delta.delta
    return values


def _code_block(text: str) -> str:
    return f"```text\n{text}\n```"


__all__ = ["EvidenceRegressionReport"]
