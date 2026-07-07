from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from business.research.rag.cli.run_evidence_eval import (
    EvidenceEvalOptions,
    run_evidence_eval_core,
)
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
    papers_dir: Path
    evidence_exit_code: int
    corpus_mode: str = "fixture"
    fixture_papers_dir: Path | None = None

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
            "papers_dir": str(self.papers_dir),
            "corpus_mode": self.corpus_mode,
            "fixture_papers_dir": str(self.fixture_papers_dir) if self.fixture_papers_dir else None,
        }


def run_live_answer_eval(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    golden_set_path: str | Path | None = None,
    papers_dir: str | Path | None = None,
    retrieval_policy: str = DEFAULT_RETRIEVAL_POLICY,
    thresholds: Mapping[str, float] | None = None,
    max_pairs_per_type: int = 2,
    live_answer_ask: Callable[[EvidenceQAPair], dict[str, Any]] | None = None,
) -> LiveAnswerEvalResult:
    output = Path(output_dir)
    fixture_papers_dir = output / "fixtures" / "papers"
    external_golden_set = Path(golden_set_path) if golden_set_path is not None else None
    external_papers_dir = Path(papers_dir) if papers_dir is not None else None
    if (external_golden_set is None) != (external_papers_dir is None):
        raise ValueError("golden_set_path and papers_dir must be provided together")
    effective_golden_set_path = external_golden_set or output / "golden_set.json"
    effective_papers_dir = external_papers_dir or fixture_papers_dir
    evidence_output_dir = output / "evidence"
    evidence_report_path = evidence_output_dir / "evidence_regression_report.json"
    evidence_markdown_path = evidence_output_dir / "evidence_regression_report.md"
    corpus_mode = "external" if external_golden_set is not None else "fixture"

    effective_thresholds = dict(DEFAULT_LIVE_ANSWER_THRESHOLDS)
    effective_thresholds.update(dict(thresholds or {}))

    if external_golden_set is None:
        write_ci_eval_fixture_papers(fixture_papers_dir)
    evidence_exit_code = run_evidence_eval_core(
        _evidence_eval_options(
            papers_dir=effective_papers_dir,
            golden_set_path=effective_golden_set_path,
            retrieval_policy=retrieval_policy,
            output_dir=evidence_output_dir,
            thresholds=effective_thresholds,
            max_pairs_per_type=max_pairs_per_type,
            build_golden_set=external_golden_set is None,
        ),
        live_answer_ask=live_answer_ask,
    )
    return LiveAnswerEvalResult(
        output_dir=output,
        evidence_report_path=evidence_report_path,
        evidence_markdown_path=evidence_markdown_path,
        golden_set_path=effective_golden_set_path,
        papers_dir=effective_papers_dir,
        corpus_mode=corpus_mode,
        fixture_papers_dir=fixture_papers_dir if external_golden_set is None else None,
        evidence_exit_code=evidence_exit_code,
    )


def _evidence_eval_options(
    *,
    papers_dir: Path,
    golden_set_path: Path,
    retrieval_policy: str,
    output_dir: Path,
    thresholds: Mapping[str, float],
    max_pairs_per_type: int,
    build_golden_set: bool,
) -> EvidenceEvalOptions:
    return EvidenceEvalOptions(
        papers_dir=papers_dir,
        golden_set=golden_set_path,
        live_retrieval=True,
        retrieval_policy=retrieval_policy,
        output_dir=output_dir,
        domain="live-answer",
        live_answer_eval=True,
        build_golden_set=build_golden_set,
        max_pairs_per_type=max_pairs_per_type,
        thresholds=dict(thresholds),
    )


__all__ = [
    "DEFAULT_LIVE_ANSWER_THRESHOLDS",
    "DEFAULT_OUTPUT_DIR",
    "LiveAnswerEvalResult",
    "run_live_answer_eval",
]
