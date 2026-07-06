from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from business.research.rag.cli.run_evidence_eval import main as run_evidence_eval
from business.research.rag.evaluation.ci_eval_gate import (
    DEFAULT_RETRIEVAL_POLICY,
    write_ci_eval_fixture_papers,
)
from business.research.rag.evaluation.paper_evidence_eval import EvidenceQAPair


DEFAULT_OUTPUT_DIR = Path(".newsroom/eval/live-answer")

DEFAULT_LIVE_ANSWER_THRESHOLDS: dict[str, float] = {
    "answer.abstention_accuracy": 0.80,
    "answer.success_rate": 0.50,
}


@dataclass(frozen=True)
class LiveAnswerEvalResult:
    output_dir: Path
    evidence_report_path: Path
    evidence_markdown_path: Path
    golden_set_path: Path
    fixture_papers_dir: Path
    evidence_exit_code: int

    @property
    def passed(self) -> bool:
        return self.evidence_exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "evidence_exit_code": self.evidence_exit_code,
            "output_dir": str(self.output_dir),
            "evidence_report_path": str(self.evidence_report_path),
            "evidence_markdown_path": str(self.evidence_markdown_path),
            "golden_set_path": str(self.golden_set_path),
            "fixture_papers_dir": str(self.fixture_papers_dir),
        }


def run_live_answer_eval(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    retrieval_policy: str = DEFAULT_RETRIEVAL_POLICY,
    thresholds: Mapping[str, float] | None = None,
    max_pairs_per_type: int = 2,
    live_answer_ask: Callable[[EvidenceQAPair], dict[str, Any]] | None = None,
) -> LiveAnswerEvalResult:
    output = Path(output_dir)
    fixture_papers_dir = output / "fixtures" / "papers"
    golden_set_path = output / "golden_set.json"
    evidence_output_dir = output / "evidence"
    evidence_report_path = evidence_output_dir / "evidence_regression_report.json"
    evidence_markdown_path = evidence_output_dir / "evidence_regression_report.md"

    effective_thresholds = dict(DEFAULT_LIVE_ANSWER_THRESHOLDS)
    effective_thresholds.update(dict(thresholds or {}))

    write_ci_eval_fixture_papers(fixture_papers_dir)
    evidence_exit_code = run_evidence_eval(
        [
            "--papers-dir",
            str(fixture_papers_dir),
            "--build-golden-set",
            "--golden-set",
            str(golden_set_path),
            "--live-retrieval",
            "--retrieval-policy",
            retrieval_policy,
            "--output-dir",
            str(evidence_output_dir),
            "--max-pairs-per-type",
            str(max_pairs_per_type),
            "--domain",
            "live-answer",
            "--live-answer-eval",
            *[
                item
                for metric, threshold in sorted(effective_thresholds.items())
                for item in ("--threshold", f"{metric}={threshold}")
            ],
        ],
        live_answer_ask=live_answer_ask,
    )
    return LiveAnswerEvalResult(
        output_dir=output,
        evidence_report_path=evidence_report_path,
        evidence_markdown_path=evidence_markdown_path,
        golden_set_path=golden_set_path,
        fixture_papers_dir=fixture_papers_dir,
        evidence_exit_code=evidence_exit_code,
    )


__all__ = [
    "DEFAULT_LIVE_ANSWER_THRESHOLDS",
    "DEFAULT_OUTPUT_DIR",
    "LiveAnswerEvalResult",
    "run_live_answer_eval",
]
