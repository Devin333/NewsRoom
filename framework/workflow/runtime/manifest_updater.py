from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any

from framework.events.trace import TraceContext
from framework.specs import StepSpec, StepStatus
from framework.workflow.buffer import DataBuffer
from framework.artifacts import ArtifactManager, ArtifactRef
from framework.workflow.runtime.execution_context import utc_now
from framework.workflow.runtime.manifest import (
    register_manifest_artifact,
    register_manifest_step_artifact,
)
from framework.workflow.runtime.result import StepOutcome
from framework.workflow.runtime.runtime_quality import apply_step_gate, record_gate_summary


class ManifestUpdater:
    def __init__(
        self,
        *,
        artifact_manager: ArtifactManager,
        run_id: str,
        manifest: dict[str, Any],
    ) -> None:
        self._artifact_manager = artifact_manager
        self._run_id = run_id
        self._manifest = manifest

    @property
    def manifest(self) -> dict[str, Any]:
        return self._manifest

    def apply_resume_metadata(
        self,
        *,
        checkpoint_id: str | None,
        resume_metadata: dict[str, Any] | None,
    ) -> None:
        if checkpoint_id is not None:
            self._manifest["resumed_from_checkpoint_id"] = checkpoint_id
        if not resume_metadata:
            return
        self._manifest["resume_metadata"] = public_resume_metadata(resume_metadata)
        apply_resume_metadata_to_manifest(self._manifest, resume_metadata)
        apply_human_review_resume_metadata_to_manifest(self._manifest, resume_metadata)

    def write_step_policy_input_artifact(
        self,
        step: StepSpec,
        buffer: DataBuffer,
    ) -> None:
        policy = step.artifact_policy
        if policy is None or not policy.write_step_input:
            return
        payload = {
            key: buffer.read(key)
            for key in step.read_keys
            if buffer.exists(key)
        }
        if policy.redacted:
            payload = {
                key: "[REDACTED]" if sensitive_key(key) else value
                for key, value in payload.items()
            }
        relative_path = f"steps/{step.step_id}/input.json"
        self._artifact_manager.write_json(self._run_id, relative_path, payload)
        register_manifest_artifact(self._manifest, f"step.{step.step_id}.input", relative_path)

    def write_step_policy_terminal_artifact(
        self,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        policy = step.artifact_policy
        if policy is None:
            return
        if policy.write_step_output:
            relative_path = f"steps/{step.step_id}/output.json"
            self._artifact_manager.write_json(self._run_id, relative_path, outcome.outputs)
            register_manifest_artifact(self._manifest, f"step.{step.step_id}.output", relative_path)
        if policy.write_step_error and outcome.status not in {StepStatus.SUCCEEDED, StepStatus.PAUSED}:
            relative_path = f"steps/{step.step_id}/error.json"
            self._artifact_manager.write_json(
                self._run_id,
                relative_path,
                {
                    "status": outcome.status.value,
                    "error_type": outcome.error_type,
                    "error_message": outcome.error_message,
                    "error_details": outcome.error_details,
                },
            )
            register_manifest_artifact(self._manifest, f"step.{step.step_id}.error", relative_path)

    def write_llm_call_artifacts(
        self,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> StepOutcome:
        llm_call_artifacts = outcome.outputs.get("llm_call_artifacts")
        if not isinstance(llm_call_artifacts, list) or not llm_call_artifacts:
            return outcome

        artifact_refs: list[ArtifactRef] = []
        written_payloads: list[dict[str, Any]] = []
        for index, payload in enumerate(llm_call_artifacts, start=1):
            if not isinstance(payload, dict):
                continue
            artifact_payload = dict(payload)
            artifact_id = str(
                artifact_payload.get("artifact_id")
                or f"{step.step_id}:llm_call:{index}"
            )
            relative_path = f"llm_calls/{step.step_id}_{index:03d}.json"
            path = self._artifact_manager.write_json(self._run_id, relative_path, artifact_payload)
            data = path.read_bytes()
            artifact_ref = ArtifactRef(
                artifact_id=artifact_id,
                run_id=self._run_id,
                step_id=step.step_id,
                artifact_type="llm_call",
                path=relative_path,
                content_type="application/json",
                size_bytes=len(data),
                checksum=sha256(data).hexdigest(),
                redacted=True,
                metadata={
                    "iteration": artifact_payload.get("iteration"),
                    "agent_id": (artifact_payload.get("metadata") or {}).get("agent_id")
                    if isinstance(artifact_payload.get("metadata"), dict)
                    else None,
                },
            )
            artifact_refs.append(artifact_ref)
            written_payloads.append({**artifact_payload, "artifact_ref": artifact_ref.to_dict()})

        if not artifact_refs:
            return outcome
        outputs = dict(outcome.outputs)
        outputs["llm_call_artifacts"] = written_payloads
        return replace(
            outcome,
            outputs=outputs,
            artifacts=[*outcome.artifacts, *artifact_refs],
            artifact_refs=[*outcome.artifact_refs, *artifact_refs],
        )

    def sync_llm_call_artifacts_to_buffer(
        self,
        buffer: DataBuffer,
        step: StepSpec,
        outcome: StepOutcome,
    ) -> None:
        artifacts = outcome.outputs.get("llm_call_artifacts")
        if "llm_call_artifacts" in step.write_keys and isinstance(artifacts, list):
            buffer.write(
                key="llm_call_artifacts",
                value=artifacts,
                step_id=step.step_id,
                lineage={"step_id": step.step_id, "post_processed": True},
            )

    def finalize_step_outcome_contract(
        self,
        workflow: Any,
        step: StepSpec,
        outcome: StepOutcome,
        *,
        trace_context: TraceContext | None = None,
        checkpoint_available: bool = False,
    ) -> StepOutcome:
        outcome = finalize_step_outcome_contract(step, outcome, trace_context=trace_context)
        return apply_step_gate(
            workflow=workflow,
            step=step,
            outcome=outcome,
            manifest=self._manifest,
            checkpoint_available=checkpoint_available,
        )

    def record_step_outcome(
        self,
        *,
        step: StepSpec,
        outcome: StepOutcome,
        path: list[str],
        step_results: dict[str, StepOutcome],
    ) -> None:
        step_results[step.step_id] = outcome
        self._manifest["steps"][step.step_id] = outcome.to_dict()
        summary = step_outcome_summary(step.step_id, outcome)
        self._manifest.setdefault("step_outcome_summary", {})[step.step_id] = summary
        sync_step_summaries(self._manifest, summary)
        record_gate_summary(self._manifest, step.step_id, outcome.gate_result)
        record_step_artifacts(self._manifest, outcome)
        record_child_runs(self._manifest, outcome)
        self._manifest["path"] = list(path)

    def record_policy_violation(self, outcome: StepOutcome) -> None:
        record_policy_violation(self._manifest, outcome)


def apply_resume_metadata_to_manifest(
    manifest: dict[str, Any],
    resume_metadata: dict[str, Any],
) -> None:
    for key in (
        "resume_mode",
        "resume_original_run_id",
        "resume_patch_keys",
        "resume_actor_id",
        "resume_approval_id",
        "resume_human_decision",
        "resume_human_review_request_id",
        "resume_current_step_ids",
        "resume_target_step_id",
        "checkpoint_schema_version",
        "checkpoint_checksum",
        "checkpoint_migrations",
        "operation_id",
        "operation_type",
        "original_run_id",
        "rerun_from_run_id",
        "rerun_from_step_id",
        "skip_step_id",
        "skip_reason",
        "skip_next_step_ids",
        "resume_budget_inherited",
    ):
        if key in resume_metadata:
            manifest[key] = resume_metadata[key]


def apply_human_review_resume_metadata_to_manifest(
    manifest: dict[str, Any],
    resume_metadata: dict[str, Any],
) -> None:
    decision = resume_metadata.get("resume_human_decision")
    if decision is None:
        return
    reviews = manifest.setdefault("human_reviews", [])
    if not isinstance(reviews, list):
        return
    reviews.append(
        {
            "request_id": resume_metadata.get("resume_human_review_request_id"),
            "approval_id": resume_metadata.get("resume_approval_id"),
            "step_id": resume_current_step_id(resume_metadata),
            "decision": decision,
            "actor_id": resume_metadata.get("resume_actor_id"),
            "decided_at": utc_now(),
        }
    )


def resume_current_step_id(resume_metadata: dict[str, Any]) -> str | None:
    current_step_ids = resume_metadata.get("resume_current_step_ids")
    if isinstance(current_step_ids, list) and current_step_ids:
        return str(current_step_ids[0])
    return None


def public_resume_metadata(resume_metadata: dict[str, Any]) -> dict[str, Any]:
    public_metadata = resume_metadata.get("_public_resume_metadata")
    if isinstance(public_metadata, dict):
        return dict(public_metadata)
    return dict(resume_metadata)


def record_step_artifacts(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    if not outcome.artifacts:
        return
    for artifact_ref in outcome.artifacts:
        register_manifest_step_artifact(manifest, artifact_ref)


def record_child_runs(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    raw_child_runs = outcome.outputs.get("child_runs")
    if not isinstance(raw_child_runs, list):
        return
    child_runs = manifest.setdefault("child_runs", [])
    if not isinstance(child_runs, list):
        return
    child_run_ids = manifest.setdefault("child_run_ids", [])
    if not isinstance(child_run_ids, list):
        return
    existing_ids = {
        item.get("child_run_id")
        for item in child_runs
        if isinstance(item, dict)
    }
    for item in raw_child_runs:
        if not isinstance(item, dict):
            continue
        child_run_id = item.get("child_run_id")
        if child_run_id is None:
            continue
        if child_run_id not in existing_ids:
            child_runs.append(dict(item))
            existing_ids.add(child_run_id)
        if child_run_id not in child_run_ids:
            child_run_ids.append(child_run_id)


def record_policy_violation(manifest: dict[str, Any], outcome: StepOutcome) -> None:
    if outcome.error_type not in {
        "WorkflowResourcePolicyViolation",
        "WorkflowRuntimeSafetyViolation",
    }:
        return
    violations = manifest.setdefault("policy_violations", [])
    if not isinstance(violations, list):
        return
    violations.append(dict(outcome.error_details))


def finalize_step_outcome_contract(
    step: StepSpec,
    outcome: StepOutcome,
    *,
    trace_context: TraceContext | None = None,
) -> StepOutcome:
    allowed_output_keys = set(step.write_keys)
    filtered_outputs = {
        key: value
        for key, value in outcome.outputs.items()
        if key in allowed_output_keys
    }
    outcome = replace(
        outcome,
        step_id=outcome.step_id or step.step_id,
        trace_id=outcome.trace_id or (trace_context.trace_id if trace_context else None),
        span_id=outcome.span_id or (trace_context.span_id if trace_context else None),
        artifact_refs=list(outcome.artifact_refs or outcome.artifacts),
    )
    if outcome.status == StepStatus.SUCCEEDED:
        missing = sorted(set(step.required_output_keys) - set(filtered_outputs))
        if missing:
            error_details = {
                **dict(outcome.error_details),
                "missing_required_output_keys": missing,
            }
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs=filtered_outputs,
                error_type="StepOutputContractViolation",
                error_message=(
                    f"step {step.step_id} did not return required output keys: "
                    f"{', '.join(missing)}"
                ),
                error_details=error_details,
                metrics=ensure_contract_metrics(step, outcome, filtered_outputs),
                artifacts=list(outcome.artifacts),
                lineage=[dict(item) for item in outcome.lineage],
                next_hint=outcome.next_hint,
                step_id=outcome.step_id,
                trace_id=outcome.trace_id,
                span_id=outcome.span_id,
                trace_events=list(outcome.trace_events),
                artifact_refs=list(outcome.artifact_refs),
                evidence_refs=list(outcome.evidence_refs),
                gate_result=outcome.gate_result,
                checkpoint_ref=outcome.checkpoint_ref,
                started_at=outcome.started_at,
                completed_at=outcome.completed_at,
                duration_ms=outcome.duration_ms,
                warnings=list(outcome.warnings),
                metadata=dict(outcome.metadata),
                error_envelope=outcome.error_envelope,
            )
    if filtered_outputs == outcome.outputs and has_contract_metrics(outcome.metrics):
        return outcome
    return replace(
        outcome,
        outputs=filtered_outputs,
        metrics=ensure_contract_metrics(step, outcome, filtered_outputs),
    )


def ensure_contract_metrics(
    step: StepSpec,
    outcome: StepOutcome,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    metrics = dict(outcome.metrics)
    metrics.setdefault("duration_ms", 0.0)
    metrics.setdefault("attempt", int(metrics.get("attempt") or 1))
    metrics.setdefault("input_key_count", len(step.read_keys))
    metrics["output_key_count"] = len(outputs)
    metrics.setdefault("artifact_count", len(outcome.artifacts))
    return metrics


def has_contract_metrics(metrics: dict[str, Any]) -> bool:
    return all(
        key in metrics
        for key in (
            "duration_ms",
            "attempt",
            "input_key_count",
            "output_key_count",
            "artifact_count",
        )
    )


def step_outcome_summary(step_id: str, outcome: StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id or step_id,
        "status": outcome.status.value,
        "duration_ms": outcome.duration_ms,
        "trace_id": outcome.trace_id,
        "span_id": outcome.span_id,
        "artifact_refs": to_summary_artifact_refs(outcome.artifact_refs or outcome.artifacts),
        "checkpoint_ref": outcome.checkpoint_ref,
        "error_type": outcome.error_type,
        "warnings": list(outcome.warnings),
        "gate_result": gate_summary_for_manifest(outcome.gate_result),
    }


def sync_step_summaries(manifest: dict[str, Any], summary: dict[str, Any]) -> None:
    step_id = summary.get("step_id")
    if step_id is None:
        return
    summaries = manifest.setdefault("step_summaries", [])
    if not isinstance(summaries, list):
        return
    replacement = dict(summary)
    for index, item in enumerate(summaries):
        if isinstance(item, dict) and item.get("step_id") == step_id:
            summaries[index] = replacement
            return
    summaries.append(replacement)


def to_summary_artifact_refs(artifact_refs: list[Any]) -> list[Any]:
    summary: list[Any] = []
    for artifact_ref in artifact_refs:
        if hasattr(artifact_ref, "to_dict"):
            payload = artifact_ref.to_dict()
            summary.append(
                {
                    "artifact_id": payload.get("artifact_id"),
                    "path": payload.get("path") or payload.get("uri"),
                    "artifact_type": payload.get("artifact_type"),
                }
            )
        elif isinstance(artifact_ref, dict):
            summary.append(
                {
                    "artifact_id": artifact_ref.get("artifact_id"),
                    "path": artifact_ref.get("path") or artifact_ref.get("uri"),
                    "artifact_type": artifact_ref.get("artifact_type"),
                }
            )
        else:
            summary.append(artifact_ref)
    return summary


def gate_summary_for_manifest(gate_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(gate_result, dict):
        return None
    return {
        "gate_id": gate_result.get("gate_id"),
        "passed": gate_result.get("passed"),
        "decision": gate_result.get("decision"),
        "failed_dimensions": list(gate_result.get("failed_dimensions") or []),
        "reason": gate_result.get("reason"),
    }


def sensitive_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(
        token in key_lower
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "client_secret",
            "password",
            "secret",
            "token",
        )
    )
