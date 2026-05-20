from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.governance import CompositeAndGate, GateCheckResult, GateResult, gate_summary
from framework.specs import RuntimeQualityPolicySpec, StepSpec, StepStatus, WorkflowSpec
from framework.workflow.runtime.result import StepOutcome


def effective_runtime_quality_policy(
    workflow: WorkflowSpec,
    step: StepSpec,
) -> RuntimeQualityPolicySpec:
    base = workflow.policies.runtime_quality
    override = step.runtime_quality
    if override is None:
        return base
    return RuntimeQualityPolicySpec(
        trace=override.trace if override.trace is not None else base.trace,
        evaluation=override.evaluation if override.evaluation is not None else base.evaluation,
        gate=override.gate if override.gate is not None else base.gate,
    )


def apply_step_gate(
    *,
    workflow: WorkflowSpec,
    step: StepSpec,
    outcome: StepOutcome,
    manifest: dict[str, Any],
    checkpoint_available: bool,
) -> StepOutcome:
    policy = effective_runtime_quality_policy(workflow, step)
    if not policy.gate.enabled:
        return replace(
            outcome,
            gate_result=GateResult.pass_result(
                f"step:{step.step_id}:gate",
                mode=policy.gate.mode,
                metadata={"enabled": False},
            ).to_dict(),
        )
    checks = step_gate_checks(
        step=step,
        outcome=outcome,
        manifest=manifest,
        checkpoint_available=checkpoint_available,
        policy=policy,
    )
    result = CompositeAndGate(
        f"step:{step.step_id}:gate",
        mode=policy.gate.mode,
    ).evaluate(
        checks,
        metadata={
            "step_id": step.step_id,
            "step_type": step.step_type.value,
            "policy": policy.to_dict(),
            "original_status": outcome.status.value,
        },
    )
    updated = replace(outcome, gate_result=result.to_dict())
    if result.decision == "warn":
        updated = replace(updated, warnings=[*updated.warnings, result.reason])
    if result.decision != "block":
        return updated
    return replace(
        updated,
        status=StepStatus.BLOCKED,
        error_type="WorkflowGateBlocked",
        error_message=result.reason or f"step gate blocked: {step.step_id}",
        error_details={
            **dict(updated.error_details),
            "step_id": step.step_id,
            "gate_result": result.to_dict(),
            "original_status": outcome.status.value,
        },
    )


def step_gate_checks(
    *,
    step: StepSpec,
    outcome: StepOutcome,
    manifest: dict[str, Any],
    checkpoint_available: bool,
    policy: RuntimeQualityPolicySpec,
) -> list[GateCheckResult]:
    checks: list[GateCheckResult] = []
    dimensions = set(policy.gate.dimensions)
    if "trace" in dimensions or policy.gate.require_trace:
        checks.append(
            GateCheckResult(
                check_id="trace.present",
                dimension="trace",
                passed=not policy.gate.require_trace or bool(outcome.trace_id and outcome.span_id),
                reason="" if outcome.trace_id and outcome.span_id else "step trace context is missing",
            )
        )
    if "compatibility" in dimensions or "correctness" in dimensions:
        required_outputs = set(step.required_output_keys)
        if policy.evaluation.enabled:
            required_outputs |= set(policy.evaluation.required_output_keys)
        missing_outputs = sorted(required_outputs - set(outcome.outputs))
        should_fail = (
            bool(step.required_output_keys)
            or policy.evaluation.fail_on_missing_required_output
        )
        checks.append(
            GateCheckResult(
                check_id="outputs.required",
                dimension="correctness",
                passed=not missing_outputs or not should_fail,
                severity="error" if should_fail else "warning",
                reason=(
                    f"missing required output keys: {missing_outputs}"
                    if missing_outputs
                    else ""
                ),
                metadata={"missing_keys": missing_outputs},
            )
        )
    if "artifact" in dimensions:
        required_kinds = set(policy.evaluation.required_artifact_kinds)
        actual_kinds = {
            str(getattr(ref, "artifact_type", "") or ref.get("artifact_type", ""))
            for ref in outcome.artifact_refs
            if hasattr(ref, "artifact_type") or isinstance(ref, dict)
        }
        missing_kinds = sorted(required_kinds - actual_kinds)
        checks.append(
            GateCheckResult(
                check_id="artifacts.required",
                dimension="artifact",
                passed=not missing_kinds,
                reason=(
                    f"missing required artifact kinds: {missing_kinds}"
                    if missing_kinds
                    else ""
                ),
                metadata={"missing_kinds": missing_kinds},
            )
        )
    if "checkpoint" in dimensions or policy.gate.require_checkpoint_for_pause:
        needs_checkpoint = (
            policy.gate.require_checkpoint_for_pause
            and outcome.status == StepStatus.PAUSED
        )
        checks.append(
            GateCheckResult(
                check_id="checkpoint.pause",
                dimension="checkpoint",
                passed=not needs_checkpoint or checkpoint_available or bool(outcome.checkpoint_ref),
                reason="paused step requires checkpoint" if needs_checkpoint else "",
            )
        )
    if "safety" in dimensions or "resource" in dimensions:
        policy_violation = outcome.error_type in {
            "WorkflowResourcePolicyViolation",
            "WorkflowRuntimeSafetyViolation",
        }
        dimension = "resource" if outcome.error_type == "WorkflowResourcePolicyViolation" else "safety"
        checks.append(
            GateCheckResult(
                check_id="policy.violation",
                dimension=dimension,
                passed=not (policy.gate.fail_on_policy_violation and policy_violation),
                reason=outcome.error_message or "policy violation" if policy_violation else "",
                metadata=dict(outcome.error_details),
            )
        )
    if not checks:
        checks.append(
            GateCheckResult(
                check_id="gate.compatibility",
                dimension="compatibility",
                passed=True,
                reason="default compatibility gate passed",
            )
        )
    return checks


def record_gate_summary(manifest: dict[str, Any], step_id: str, gate_result: dict[str, Any] | None) -> None:
    summary = gate_summary(gate_result)
    if summary is None:
        return
    gate_summary_list = manifest.setdefault("gate_summary", [])
    if isinstance(gate_summary_list, list):
        gate_summary_list.append({"step_id": step_id, **summary})
