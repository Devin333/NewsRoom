from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from business.research.rag.answer_eval import EvidenceAnswerEvalResult
from business.research.rag.evaluation_compare import EvidenceABResult
from business.research.rag.evidence_eval import EvidenceEvalResult


@dataclass
class EvidenceRegressionReport:
    retrieval: EvidenceEvalResult | None = None
    answer: EvidenceAnswerEvalResult | None = None
    ab: EvidenceABResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metadata": dict(self.metadata),
        }
        if self.retrieval is not None:
            payload["retrieval"] = _retrieval_result_to_dict(self.retrieval)
        if self.answer is not None:
            payload["answer"] = _answer_result_to_dict(self.answer)
        if self.ab is not None:
            payload["ab"] = _ab_result_to_dict(self.ab)
        return payload

    def to_markdown(self) -> str:
        lines = ["# Paper RAG Evidence Regression Report", ""]
        if self.metadata:
            lines.extend(["## Metadata", ""])
            for key in sorted(self.metadata):
                lines.append(f"- `{key}`: {self.metadata[key]}")
            lines.append("")
        if self.retrieval is not None:
            lines.extend(["## Retrieval", "", _code_block(self.retrieval.report()), ""])
        if self.answer is not None:
            lines.extend(["## Answer", "", _code_block(self.answer.report()), ""])
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
        "by_qa_type": {
            qa_type: _retrieval_result_to_dict(sub)
            for qa_type, sub in result.by_qa_type.items()
        },
    }


def _answer_result_to_dict(result: EvidenceAnswerEvalResult) -> dict[str, Any]:
    return {
        "total": result.total,
        "answer_fact_coverage": result.answer_fact_coverage(),
        "citation_grounding_score": result.citation_grounding_score(),
        "source_locator_grounding_score": result.source_locator_grounding_score(),
        "abstention_accuracy": result.abstention_accuracy(),
        "success_rate": result.success_rate(),
        "by_qa_type": {
            qa_type: _answer_result_to_dict(sub)
            for qa_type, sub in result.by_qa_type.items()
        },
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


def _code_block(text: str) -> str:
    return f"```text\n{text}\n```"


__all__ = ["EvidenceRegressionReport"]
