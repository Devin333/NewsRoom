"""Quality gate step runner."""

from __future__ import annotations

import time

from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runners._utils import (
    buffer_metric,
    buffer_value,
    contract_metrics,
    failed_outcome,
    metadata_float,
    validated_outputs,
)
from framework.workflow.runners.base import (
    StepExecutionError,
    StepRunnerCapability,
    StepRunnerSideEffectLevel,
    ValidationErrorItem,
    default_runner_can_resolve,
)


class QualityGateStepRunner:
    capability = StepRunnerCapability(
        step_type=StepType.QUALITY_GATE,
        runner_id="builtin.quality_gate",
        version="1.0.0",
        supports_checkpoint=True,
        supports_resume=True,
        supports_timeout=True,
        supports_retry=False,
        side_effect_level=StepRunnerSideEffectLevel.NONE,
        required_dependencies=[],
        description="Evaluates deterministic report quality gate rules.",
    )

    def can_resolve(self, step: StepSpec) -> bool:
        return default_runner_can_resolve(self.capability, step)

    def validate_step(self, step: StepSpec) -> list[ValidationErrorItem]:
        return []

    def run(self, step: StepSpec, buffer: StepScopedDataBufferView) -> StepOutcome:
        started = time.perf_counter()
        try:
            if step.step_type != StepType.QUALITY_GATE:
                raise StepExecutionError(
                    f"unsupported step type for QualityGateStepRunner: {step.step_type}"
                )

            policy = step.quality_policy
            min_citation_coverage = metadata_float(
                step,
                "min_citation_coverage",
                policy.min_citation_coverage if policy else None,
            )
            min_editor_score = metadata_float(
                step,
                "min_editor_score",
                policy.min_editor_score if policy else None,
            )
            citation_coverage = buffer_metric(
                buffer, step, "citation_coverage", "citation_coverage_score"
            )
            editor_score = buffer_metric(buffer, step, "editor_score", "editor_score")
            unsupported_claims = buffer_value(
                buffer, step.metadata.get("unsupported_claims_key"), []
            )

            blocked_reasons: list[str] = []
            rewrite_reasons: list[str] = []
            if min_citation_coverage is not None and (
                citation_coverage is None or citation_coverage < min_citation_coverage
            ):
                rewrite_reasons.append("citation_coverage_below_threshold")
            if min_editor_score is not None and (
                editor_score is None or editor_score < min_editor_score
            ):
                rewrite_reasons.append("editor_score_below_threshold")
            if (
                policy is not None
                and policy.block_on_unsupported_claims
                and unsupported_claims
            ):
                blocked_reasons.append("unsupported_claims")

            if blocked_reasons:
                decision = "blocked"
            elif rewrite_reasons:
                decision = "rewrite_required"
            else:
                decision = "pass"

            output_key = str(step.metadata.get("output_key") or "quality_gate_metrics")
            quality_metrics = {
                "decision": decision,
                "citation_coverage": citation_coverage,
                "editor_score": editor_score,
                "blocked_reasons": blocked_reasons,
                "rewrite_reasons": rewrite_reasons,
            }
            outputs = validated_outputs(
                step,
                {output_key: quality_metrics},
                runner_name="quality_gate step",
            )
            if output_key in buffer.list_allowed_writes():
                buffer.write(output_key, quality_metrics)
            return StepOutcome(
                status=StepStatus.SUCCEEDED,
                outputs=outputs,
                metrics=contract_metrics(step, started=started, outputs=outputs),
                next_hint=decision,
            )
        except Exception as exc:
            return failed_outcome(
                step,
                exc,
                started=started,
                runner_name="QualityGateStepRunner",
            )

__all__ = ["QualityGateStepRunner"]


