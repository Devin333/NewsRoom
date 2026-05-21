from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal

from framework.shared.json import to_jsonable
from framework.specs import StepSpec, WorkflowStatus
from framework.workflow.runtime.execution_context import WorkflowExecutionContext
from framework.workflow.runtime.result import WorkflowError
from framework.workflow.runtime.runtime_quality import effective_runtime_quality_policy


RuntimeVerificationMode = Literal["off", "warn", "strict"]
_MODES = {"off", "warn", "strict"}


@dataclass(frozen=True)
class RuntimeVerificationIssue:
    code: str
    message: str
    severity: str = "error"
    step_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def blocks(self) -> bool:
        return self.severity in {"error", "critical"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "step_id": self.step_id,
            "details": to_jsonable(self.details),
        }


@dataclass(frozen=True)
class RuntimeVerificationReport:
    mode: str
    issues: list[RuntimeVerificationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.blocks() for issue in self.issues)

    @property
    def failed(self) -> bool:
        return not self.passed

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "passed": self.passed,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class WorkflowRuntimeVerifier:
    def __init__(self, mode: RuntimeVerificationMode = "off") -> None:
        if mode not in _MODES:
            raise ValueError(f"unsupported runtime_verification_mode: {mode}")
        self.mode = mode

    def verify_context(self, context: WorkflowExecutionContext) -> RuntimeVerificationReport:
        issues: list[RuntimeVerificationIssue] = []
        if self.mode == "off":
            return RuntimeVerificationReport(mode=self.mode, issues=issues)
        issues.extend(_manifest_issues(context))
        for step_id, outcome in context.step_results.items():
            step = context.workflow.step_by_id(step_id)
            policy = effective_runtime_quality_policy(context.workflow, step)
            issues.extend(_required_output_issues(step, outcome, policy))
            issues.extend(_trace_issues(step, outcome, policy))
            issues.extend(_gate_issues(step, outcome, policy))
            issues.extend(_artifact_ref_issues(step, outcome))
        return RuntimeVerificationReport(mode=self.mode, issues=issues)

    def apply(self, context: WorkflowExecutionContext) -> RuntimeVerificationReport | None:
        report = self.verify_context(context)
        if self.mode == "off":
            return None
        context.manifest["runtime_verification"] = report.to_dict()
        if report.issues:
            warnings = context.manifest.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.extend(
                    f"runtime_verification:{issue.severity}:{issue.message}"
                    for issue in report.issues
                )
        if self.mode == "strict" and report.failed:
            context.status = WorkflowStatus.FAILED
            context.error = WorkflowError(
                error_type="RuntimeVerificationFailed",
                message="runtime verification failed",
                details=report.to_dict(),
            )
            context.current_step_ids = []
        return report


def _manifest_issues(context: WorkflowExecutionContext) -> list[RuntimeVerificationIssue]:
    issues: list[RuntimeVerificationIssue] = []
    manifest = context.manifest
    required = ("run_id", "status", "started_at", "steps", "step_summaries", "artifacts")
    missing = [field for field in required if field not in manifest]
    if missing:
        issues.append(
            RuntimeVerificationIssue(
                code="manifest.required_fields_missing",
                message=f"run manifest is missing required fields: {missing}",
                details={"missing_fields": missing},
            )
        )
    if not isinstance(manifest.get("steps"), dict):
        issues.append(
            RuntimeVerificationIssue(
                code="manifest.steps_invalid",
                message="run manifest steps must be an object",
            )
        )
    if not isinstance(manifest.get("step_summaries"), list):
        issues.append(
            RuntimeVerificationIssue(
                code="manifest.step_summaries_invalid",
                message="run manifest step_summaries must be a list",
            )
        )
        return issues
    summary_step_ids = {
        str(item.get("step_id"))
        for item in manifest.get("step_summaries", [])
        if isinstance(item, dict) and item.get("step_id") is not None
    }
    for step_id in context.step_results:
        if step_id not in summary_step_ids:
            issues.append(
                RuntimeVerificationIssue(
                    code="manifest.step_summary_missing",
                    message=f"run manifest is missing step summary for: {step_id}",
                    step_id=step_id,
                )
            )
    if not isinstance(manifest.get("artifacts"), dict):
        issues.append(
            RuntimeVerificationIssue(
                code="manifest.artifacts_invalid",
                message="run manifest artifacts must be an object",
            )
        )
    return issues


def _required_output_issues(
    step: StepSpec,
    outcome: Any,
    policy: Any,
) -> list[RuntimeVerificationIssue]:
    required = set(step.required_output_keys)
    if policy.evaluation.enabled:
        required |= set(policy.evaluation.required_output_keys)
    missing = sorted(required - set(outcome.outputs))
    if not missing:
        return []
    return [
        RuntimeVerificationIssue(
            code="step.required_outputs_missing",
            message=f"step {step.step_id} is missing required output keys: {missing}",
            step_id=step.step_id,
            details={"missing_keys": missing},
        )
    ]


def _trace_issues(step: StepSpec, outcome: Any, policy: Any) -> list[RuntimeVerificationIssue]:
    if not (policy.trace.enabled or policy.gate.require_trace):
        return []
    if outcome.trace_id and outcome.span_id:
        return []
    return [
        RuntimeVerificationIssue(
            code="step.trace_missing",
            message=f"step {step.step_id} is missing trace_id/span_id",
            step_id=step.step_id,
        )
    ]


def _gate_issues(step: StepSpec, outcome: Any, policy: Any) -> list[RuntimeVerificationIssue]:
    if not policy.gate.enabled or isinstance(outcome.gate_result, dict):
        return []
    return [
        RuntimeVerificationIssue(
            code="step.gate_result_missing",
            message=f"step {step.step_id} is missing gate_result",
            step_id=step.step_id,
        )
    ]


def _artifact_ref_issues(step: StepSpec, outcome: Any) -> list[RuntimeVerificationIssue]:
    issues: list[RuntimeVerificationIssue] = []
    for artifact_ref in list(outcome.artifact_refs or outcome.artifacts or []):
        path = _artifact_path(artifact_ref)
        if path is None:
            continue
        if _unsafe_artifact_path(path):
            issues.append(
                RuntimeVerificationIssue(
                    code="step.artifact_ref_path_invalid",
                    message=f"step {step.step_id} has unsafe artifact path: {path}",
                    step_id=step.step_id,
                    details={"path": path},
                )
            )
    return issues


def _artifact_path(value: Any) -> str | None:
    if isinstance(value, dict):
        raw = value.get("path") or value.get("uri") or value.get("relative_path")
    else:
        raw = (
            getattr(value, "path", None)
            or getattr(value, "uri", None)
            or getattr(value, "relative_path", None)
        )
    if raw is None:
        return None
    return str(raw).replace("\\", "/")


def _unsafe_artifact_path(path: str) -> bool:
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return True
    return ".." in PurePosixPath(path).parts
