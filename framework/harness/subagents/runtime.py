from __future__ import annotations

from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.subagents.gates import FakeSubAgentGateSuite, all_subagent_gates_passed
from framework.harness.subagents.models import SubAgentInvocation, SubAgentResult, SubAgentStatus
from framework.harness.subagents.transcript import FakeSubAgentTranscriptStore, SubAgentTranscript
from framework.harness.workers.result import HarnessWorkerResult


class SubAgentRuntime:
    def __init__(
        self,
        *,
        workers: dict[str, Any],
        transcript_store: FakeSubAgentTranscriptStore | None = None,
        gates: FakeSubAgentGateSuite | None = None,
    ) -> None:
        self.workers = dict(workers)
        self.transcript_store = transcript_store or FakeSubAgentTranscriptStore()
        self.gates = gates or FakeSubAgentGateSuite()

    def invoke(self, invocation: SubAgentInvocation) -> SubAgentResult:
        spec = invocation.subagent_spec
        context_result = self.gates.context_boundary.evaluate(invocation.context_envelope)
        input_result = self.gates.input_schema.evaluate(spec, {"input_refs": list(invocation.input_refs), **invocation.metadata})
        if not all_subagent_gates_passed((context_result, input_result)):
            return self._halted_result(invocation, (context_result, input_result), errors=("subagent plan gates failed",))

        worker = self.workers.get(spec.subagent_id)
        if worker is None:
            raise HarnessValidationError("subagent worker is not registered", details={"subagent_id": spec.subagent_id})
        task = {
            "invocation": invocation.to_dict(),
            "context": invocation.context_envelope.to_dict(),
            "input_refs": list(invocation.input_refs),
            "budget": spec.budget,
        }
        worker_result = _call_worker(worker, spec.subagent_id, task)
        output = dict(worker_result.output)
        requested_tools = tuple(str(tool) for tool in output.get("requested_tools", ()))
        requested_namespaces = tuple(str(namespace) for namespace in output.get("memory_namespaces", ()))
        usage = {
            "turns": int(output.get("turns_used", 1)),
            "tool_calls": len(requested_tools),
            "memory_ops": len(requested_namespaces),
        }

        base_result = SubAgentResult(
            invocation_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            subagent_id=spec.subagent_id,
            status=worker_result.status.value,
            output={key: value for key, value in output.items() if key not in {"requested_tools", "memory_namespaces"}},
            artifact_refs=worker_result.artifacts,
            memory_write_candidates=tuple(output.get("memory_write_candidates", ())),
            tool_call_refs=tuple(f"tool-call://{invocation.child_run_id}/{tool}" for tool in requested_tools),
            warnings=tuple(worker_result.diagnostics.get("warnings", ())),
            errors=(worker_result.error,) if worker_result.error else (),
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
            return self._halted_result(invocation, gate_results, errors=("subagent verify gates failed",), worker_result=base_result)

        transcript_ref = self._write_transcript(invocation, base_result, gate_results)
        final_result = SubAgentResult(
            invocation_id=base_result.invocation_id,
            child_run_id=base_result.child_run_id,
            subagent_id=base_result.subagent_id,
            status=base_result.status,
            output=base_result.output,
            artifact_refs=base_result.artifact_refs,
            memory_write_candidates=base_result.memory_write_candidates,
            tool_call_refs=base_result.tool_call_refs,
            warnings=base_result.warnings,
            errors=base_result.errors,
            transcript_ref=transcript_ref,
            metadata=base_result.metadata,
        )
        transcript_result = self.gates.transcript.evaluate(final_result)
        if not transcript_result.passed:
            return self._halted_result(invocation, (*gate_results, transcript_result), errors=("subagent transcript missing",))
        return final_result

    def _halted_result(
        self,
        invocation: SubAgentInvocation,
        gate_results: tuple,
        *,
        errors: tuple[str, ...],
        worker_result: SubAgentResult | None = None,
    ) -> SubAgentResult:
        transcript_ref = self._write_transcript(invocation, worker_result, gate_results, errors=errors)
        return SubAgentResult(
            invocation_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            subagent_id=invocation.subagent_spec.subagent_id,
            status=SubAgentStatus.HALTED,
            output=worker_result.output if worker_result else {},
            artifact_refs=worker_result.artifact_refs if worker_result else (),
            memory_write_candidates=worker_result.memory_write_candidates if worker_result else (),
            tool_call_refs=worker_result.tool_call_refs if worker_result else (),
            errors=errors,
            transcript_ref=transcript_ref,
            metadata={"gate_results": [result.to_dict() for result in gate_results]},
        )

    def _write_transcript(
        self,
        invocation: SubAgentInvocation,
        result: SubAgentResult | None,
        gate_results: tuple,
        *,
        errors: tuple[str, ...] = (),
    ) -> str:
        transcript = SubAgentTranscript(
            transcript_id=invocation.invocation_id,
            child_run_id=invocation.child_run_id,
            parent_run_id=invocation.parent_run_id,
            subagent_id=invocation.subagent_spec.subagent_id,
            context_envelope_ref=f"subagent-context://{invocation.child_run_id}",
            input_refs=invocation.input_refs,
            tool_call_refs=result.tool_call_refs if result else (),
            memory_context_refs=invocation.context_envelope.memory_context_refs,
            output_ref=f"subagent-output://{invocation.child_run_id}" if result else None,
            gate_results=tuple(gate_result.to_dict() for gate_result in gate_results),
            budget_snapshot=invocation.budget_snapshot.to_dict(),
            errors=errors or (result.errors if result else ()),
            events=(
                {"event_type": "subagent_invocation_planned", "child_run_id": invocation.child_run_id},
                {"event_type": "subagent_completed" if result and result.status == SubAgentStatus.SUCCEEDED else "subagent_halted"},
            ),
        )
        return self.transcript_store.write(transcript)


def _call_worker(worker: Any, subagent_id: str, task: dict[str, Any]) -> HarnessWorkerResult:
    execute = getattr(worker, "execute", None)
    if callable(execute):
        return execute(task)
    run_subagent = getattr(worker, "run_subagent", None)
    if callable(run_subagent):
        return run_subagent(subagent_id, task, dict(task.get("budget", {})))
    if callable(worker):
        return worker(task)
    raise HarnessValidationError("subagent worker must be callable or implement SubAgentWorkerPort")


__all__ = ["SubAgentRuntime"]
