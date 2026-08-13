from __future__ import annotations

from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.subagents.gates import (
    FakeSubAgentGateSuite,
    SubAgentGateResult,
    all_subagent_gates_passed,
)
from framework.harness.subagents.models import (
    SubAgentInvocation,
    SubAgentResult,
    SubAgentStatus,
)
from framework.harness.subagents.observability import (
    DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK,
    SUBAGENT_TRANSCRIPT_RECOVERY_REUSED_TOTAL,
    SubAgentTranscriptObservation,
    SubAgentTranscriptObservationSink,
    record_subagent_transcript_observation,
)
from framework.harness.subagents.transcript import (
    SubAgentAttemptIdentity,
    SubAgentContextEvidence,
    SubAgentOutputDocument,
    SubAgentTranscript,
    SubAgentTranscriptStorePort,
    sanitize_subagent_payload,
)
from framework.harness.workers.result import HarnessWorkerResult


class SubAgentRuntime:
    def __init__(
        self,
        *,
        workers: dict[str, Any],
        transcript_store: SubAgentTranscriptStorePort,
        gates: FakeSubAgentGateSuite | None = None,
        observation_sink: SubAgentTranscriptObservationSink | None = (
            DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK
        ),
    ) -> None:
        if not isinstance(transcript_store, SubAgentTranscriptStorePort):
            raise TypeError("transcript_store must implement SubAgentTranscriptStorePort")
        self.workers = dict(workers)
        self.transcript_store = transcript_store
        self.gates = gates or FakeSubAgentGateSuite()
        if observation_sink is not None and not isinstance(
            observation_sink,
            SubAgentTranscriptObservationSink,
        ):
            raise TypeError(
                "observation_sink must implement SubAgentTranscriptObservationSink"
            )
        self._observation_sink = observation_sink

    def invoke(self, invocation: SubAgentInvocation) -> SubAgentResult:
        if not isinstance(invocation, SubAgentInvocation):
            raise TypeError("invocation must be SubAgentInvocation")
        identity = _identity_for(invocation)
        recovered = self._recover(identity)
        if recovered is not None:
            return recovered

        spec = invocation.subagent_spec
        context_result = self.gates.context_boundary.evaluate(invocation.context_envelope)
        input_result = self.gates.input_schema.evaluate(
            spec,
            {"input_refs": list(invocation.input_refs), **invocation.metadata},
        )
        if not all_subagent_gates_passed((context_result, input_result)):
            return self._halted_result(
                invocation,
                (context_result, input_result),
                errors=("subagent_plan_gates_failed",),
            )

        worker = self.workers.get(spec.subagent_id)
        if worker is None:
            return self._halted_result(
                invocation,
                (context_result, input_result),
                errors=("subagent_worker_not_registered",),
            )
        task = {
            "invocation": invocation.to_dict(),
            "context": invocation.context_envelope.to_dict(),
            "input_refs": list(invocation.input_refs),
            "budget": spec.budget,
        }
        try:
            worker_result = _call_worker(worker, spec.subagent_id, task)
        except Exception:
            return self._halted_result(
                invocation,
                (context_result, input_result),
                errors=("subagent_worker_execution_failed",),
            )
        output = dict(worker_result.output)
        try:
            requested_tools = tuple(str(tool) for tool in output.get("requested_tools", ()))
            requested_namespaces = tuple(str(namespace) for namespace in output.get("memory_namespaces", ()))
            usage = {
                "turns": int(output.get("turns_used", 1)),
                "tool_calls": len(requested_tools),
                "memory_ops": len(requested_namespaces),
            }
            sanitized_output = sanitize_subagent_payload(
                {
                    key: value
                    for key, value in output.items()
                    if key not in {"requested_tools", "memory_namespaces", "memory_write_candidates"}
                }
            )
            memory_write_candidates = _sanitize_memory_write_candidates(
                output.get("memory_write_candidates", ())
            )
        except (HarnessValidationError, TypeError, ValueError, OverflowError):
            return self._halted_result(
                invocation,
                (context_result, input_result),
                errors=("subagent_worker_output_invalid",),
            )
        warning_count = _warning_count(worker_result.diagnostics.get("warnings", ()))
        base_result = SubAgentResult(
            invocation_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            subagent_id=spec.subagent_id,
            status=worker_result.status.value,
            output=sanitized_output,
            artifact_refs=worker_result.artifacts,
            memory_write_candidates=memory_write_candidates,
            # Requested tool ids are authorization input, not proof that a
            # canonical ToolRuntime call record exists.
            tool_call_refs=(),
            warnings=tuple(
                f"subagent_worker_warning_{index}"
                for index in range(1, min(warning_count, 128) + 1)
            ),
            errors=("subagent_worker_failed",) if worker_result.error else (),
            metadata={"worker_metrics": worker_result.metrics},
        )
        gate_results = (
            context_result,
            self.gates.tool_allowlist.evaluate(spec, requested_tools),
            self.gates.memory_namespace.evaluate(spec, requested_namespaces),
            self.gates.output_schema.evaluate(spec, base_result),
            self.gates.budget.evaluate(invocation, usage),
        )
        if not all_subagent_gates_passed(gate_results):
            return self._halted_result(
                invocation,
                gate_results,
                errors=("subagent_verify_gates_failed",),
                worker_result=base_result,
            )

        receipt = self._write_bundle(invocation, base_result, gate_results)
        final_result = _with_receipt(base_result, receipt)
        transcript_result = self.gates.transcript.evaluate(
            final_result,
            store=self.transcript_store,
            identity=identity,
        )
        if not transcript_result.passed:
            return self._halted_result(
                invocation,
                (*gate_results, transcript_result),
                errors=("subagent_transcript_verify_failed",),
            )
        return final_result

    def recover(self, invocation: SubAgentInvocation) -> SubAgentResult | None:
        """Read a previously committed outcome without invoking a worker."""

        if not isinstance(invocation, SubAgentInvocation):
            raise TypeError("invocation must be SubAgentInvocation")
        return self._recover(_identity_for(invocation))

    def _recover(self, identity: SubAgentAttemptIdentity) -> SubAgentResult | None:
        receipt = self.transcript_store.find_by_identity(identity)
        if receipt is None:
            return None
        self.transcript_store.verify(receipt)
        output = self.transcript_store.read_output(receipt.output_ref)
        transcript = self.transcript_store.read(receipt.transcript_ref)
        record_subagent_transcript_observation(
            self._observation_sink,
            SubAgentTranscriptObservation.from_identity(
                SUBAGENT_TRANSCRIPT_RECOVERY_REUSED_TOTAL,
                identity,
                receipt=receipt,
                value=1,
            ),
        )
        return SubAgentResult(
            invocation_id=identity.invocation_id,
            child_run_id=identity.child_run_id,
            subagent_id=identity.subagent_id,
            status=SubAgentStatus(output.status),
            output=dict(output.output),
            artifact_refs=output.artifact_refs,
            errors=tuple(transcript.errors),
            warnings=tuple(transcript.warnings),
            tool_call_refs=transcript.tool_call_refs,
            transcript_receipt=receipt,
            metadata={
                "recovered": True,
                "gate_results": [dict(item) for item in transcript.gate_results],
            },
        )

    def _halted_result(
        self,
        invocation: SubAgentInvocation,
        gate_results: tuple[SubAgentGateResult, ...],
        *,
        errors: tuple[str, ...],
        worker_result: SubAgentResult | None = None,
    ) -> SubAgentResult:
        result = worker_result or SubAgentResult(
            invocation_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            subagent_id=invocation.subagent_spec.subagent_id,
            status=SubAgentStatus.HALTED,
            errors=errors,
        )
        halted = SubAgentResult(
            invocation_id=result.invocation_id,
            child_run_id=result.child_run_id,
            subagent_id=result.subagent_id,
            status=SubAgentStatus.HALTED,
            output=result.output,
            artifact_refs=result.artifact_refs,
            memory_write_candidates=result.memory_write_candidates,
            tool_call_refs=result.tool_call_refs,
            warnings=result.warnings,
            errors=errors,
            metadata={"gate_results": [item.to_dict() for item in gate_results]},
        )
        receipt = self._write_bundle(invocation, halted, gate_results, errors=errors)
        return _with_receipt(halted, receipt)

    def _write_bundle(
        self,
        invocation: SubAgentInvocation,
        result: SubAgentResult,
        gate_results: tuple[SubAgentGateResult, ...],
        *,
        errors: tuple[str, ...] = (),
    ):
        identity = _identity_for(invocation)
        context = SubAgentContextEvidence(
            identity=identity,
            context_envelope_ref=f"subagent-context://v1/{identity.parent_run_id}/{identity.transcript_id}",
            input_refs=invocation.input_refs,
            memory_context_refs=invocation.context_envelope.memory_context_refs,
            redaction_report={"raw_parent_messages_included": False, "sibling_history_included": False},
        )
        output = SubAgentOutputDocument(
            identity=identity,
            status=result.status.value,
            output=result.output,
            artifact_refs=result.artifact_refs,
            error_code=(errors or result.errors)[0]
            if errors or result.errors
            else None,
        )
        transcript = SubAgentTranscript(
            identity=identity,
            context_envelope_ref=context.context_envelope_ref,
            input_refs=invocation.input_refs,
            tool_call_refs=result.tool_call_refs,
            memory_context_refs=invocation.context_envelope.memory_context_refs,
            output_ref=output.ref,
            output_checksum=output.output_checksum,
            artifact_refs=result.artifact_refs,
            gate_results=tuple(_transcript_gate_dict(item) for item in gate_results),
            budget_snapshot=invocation.budget_snapshot.to_dict(),
            redaction_report={"raw_parent_messages_included": False, "sibling_history_included": False},
            warnings=result.warnings,
            errors=errors or result.errors,
            events=(
                {"event_type": "subagent_invocation_planned"},
                {"event_type": "subagent_completed" if result.status is SubAgentStatus.SUCCEEDED else "subagent_halted"},
            ),
            observed_at=invocation.observed_at,
        )
        receipt = self.transcript_store.write(context, output, transcript)
        return self.transcript_store.verify(receipt)


def _identity_for(invocation: SubAgentInvocation) -> SubAgentAttemptIdentity:
    return SubAgentAttemptIdentity(
        invocation_id=invocation.invocation_id,
        parent_run_id=invocation.parent_run_id,
        child_run_id=invocation.child_run_id,
        workflow_id=invocation.workflow_id,
        stage_id=invocation.step_id,
        task_id=invocation.task_id,
        task_instance_id=invocation.task_instance_id,
        attempt=invocation.attempt,
        subagent_id=invocation.subagent_spec.subagent_id,
    )


def _with_receipt(result: SubAgentResult, receipt) -> SubAgentResult:
    return SubAgentResult(
        invocation_id=result.invocation_id,
        child_run_id=result.child_run_id,
        subagent_id=result.subagent_id,
        status=result.status,
        output=result.output,
        artifact_refs=result.artifact_refs,
        memory_write_candidates=result.memory_write_candidates,
        tool_call_refs=result.tool_call_refs,
        warnings=result.warnings,
        errors=result.errors,
        transcript_receipt=receipt,
        metadata=result.metadata,
    )


def _transcript_gate_dict(result: SubAgentGateResult) -> dict[str, Any]:
    return {**result.evidence_projection(), "evidence_checksum": result.evidence_checksum}


def _warning_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple)):
        return min(len(value), 128)
    return 1


def _sanitize_memory_write_candidates(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise HarnessValidationError(
            "memory_write_candidates must be an array",
            code="subagent_memory_candidate_invalid",
        )
    if len(value) > 128:
        raise HarnessValidationError(
            "memory_write_candidates exceeds its item limit",
            code="subagent_memory_candidate_invalid",
        )
    candidates: list[dict[str, Any]] = []
    for candidate in value:
        if not isinstance(candidate, dict):
            raise HarnessValidationError(
                "memory_write_candidates must contain objects",
                code="subagent_memory_candidate_invalid",
            )
        candidates.append(
            sanitize_subagent_payload(
                candidate,
                field_name="memory_write_candidate",
                max_bytes=64 * 1024,
            )
        )
    return tuple(candidates)


def _call_worker(worker: Any, subagent_id: str, task: dict[str, Any]) -> HarnessWorkerResult:
    execute = getattr(worker, "execute", None)
    if callable(execute):
        value = execute(task)
    else:
        run_subagent = getattr(worker, "run_subagent", None)
        if callable(run_subagent):
            value = run_subagent(subagent_id, task, dict(task.get("budget", {})))
        elif callable(worker):
            value = worker(task)
        else:
            raise HarnessValidationError("subagent worker must be callable or implement SubAgentWorkerPort")
    if not isinstance(value, HarnessWorkerResult):
        raise HarnessValidationError("subagent worker must return HarnessWorkerResult")
    return value


__all__ = ["SubAgentRuntime"]
