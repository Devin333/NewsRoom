from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.skills.evolution.gates import SkillStaticGateSuite, failed_skill_gate_dicts
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillCandidateStatus,
    SkillEvaluationCase,
    SkillEvaluationResult,
    SkillStaticValidationResult,
)


class SkillStaticValidator:
    def __init__(self, gates: SkillStaticGateSuite | None = None) -> None:
        self.gates = gates or SkillStaticGateSuite()

    def validate(self, candidate: SkillCandidate) -> SkillStaticValidationResult:
        results = self.gates.evaluate(candidate)
        failed = failed_skill_gate_dicts(results)
        return SkillStaticValidationResult(
            candidate_id=candidate.candidate_id,
            passed=not failed,
            gate_results=tuple(result.to_dict() for result in results),
            issues=tuple(result["reason"] for result in failed if result.get("reason")),
        )


class SkillEvalReplayRunner:
    def run_eval_suite(self, candidate: SkillCandidate, eval_request: dict[str, Any]) -> SkillEvaluationResult:
        cases = tuple(
            item if isinstance(item, SkillEvaluationCase) else SkillEvaluationCase(**item)
            for item in eval_request.get("cases", ())
        )
        if not cases:
            cases = (
                SkillEvaluationCase(
                    case_id=f"eval-case:{candidate.candidate_id}:held-out",
                    split="held_out",
                    input_refs=(candidate.package_ref or candidate.base_version.immutable_ref,),
                    expected_refs=(candidate.base_version.immutable_ref,),
                ),
            )
        max_eval_cases = int(eval_request.get("max_eval_cases", len(cases)))
        cases = cases[:max_eval_cases]
        baseline_score = float(eval_request.get("baseline_score", 0.0))
        score = float(eval_request.get("candidate_score", eval_request.get("score", 0.0)))
        minimum_improvement = float(eval_request.get("minimum_improvement", 0.0))
        regression_tolerance = float(eval_request.get("regression_tolerance", 0.0))
        metrics = dict(eval_request.get("metrics", {}))
        passed = score - baseline_score >= minimum_improvement and not metrics.get("evidence_coverage_regressed", False)
        result = SkillEvaluationResult(
            candidate_id=candidate.candidate_id,
            passed=passed,
            score=score,
            baseline_score=baseline_score,
            held_out_score=float(eval_request.get("held_out_score", score)),
            minimum_improvement=minimum_improvement,
            regression_tolerance=regression_tolerance,
            eval_case_count=len(cases),
            issues=() if passed else ("held-out eval did not strictly improve",),
            metrics=metrics,
            case_results=tuple({"case_id": case.case_id, "split": case.split.value, "passed": passed} for case in cases),
        )
        return result

    def attach_result(self, candidate: SkillCandidate, evaluation: SkillEvaluationResult) -> SkillCandidate:
        status = SkillCandidateStatus.PROMOTION_PENDING if evaluation.passed else SkillCandidateStatus.EVAL_REJECTED
        return replace(candidate, status=status, evaluation_results=(*candidate.evaluation_results, evaluation))


class SkillSandboxTrialRunner:
    def run_sandbox_trial(self, candidate: SkillCandidate, sandbox_request: dict[str, Any]) -> SkillEvaluationResult:
        return SkillEvaluationResult(
            candidate_id=candidate.candidate_id,
            passed=bool(sandbox_request.get("passed", True)),
            score=float(sandbox_request.get("score", 0.8)),
            baseline_score=float(sandbox_request.get("baseline_score", 0.7)),
            held_out_score=float(sandbox_request.get("score", 0.8)),
            minimum_improvement=float(sandbox_request.get("minimum_improvement", 0.01)),
            regression_tolerance=float(sandbox_request.get("regression_tolerance", 0.0)),
            eval_case_count=int(sandbox_request.get("eval_case_count", 1)),
            metrics=dict(sandbox_request.get("metrics", {"sandbox": True})),
        )


__all__ = ["SkillEvalReplayRunner", "SkillSandboxTrialRunner", "SkillStaticValidator"]
