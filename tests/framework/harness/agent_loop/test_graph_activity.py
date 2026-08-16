from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from framework.agent.models import (
    AgentLoopDiagnosticSeverity,
    AgentLoopDiagnostics,
    AgentLoopIssue,
    AgentLoopMetrics,
    AgentLoopResult,
    AgentLoopStatus,
    AgentLoopStopReason,
    AgentSpec,
    LLMCallArtifact,
)
from framework.agent.loop.runner import AgentRunner
from framework.events.canonical import checksum_for
from framework.harness.agent_loop import (
    AGENT_LOOP_GRAPH_ACTIVITY_TASK_SCHEMA,
    AGENT_LOOP_GRAPH_WAIT_EVIDENCE_TYPE,
    AgentLoopGraphActivityOutput,
    AgentLoopGraphWaitCandidate,
    AgentLoopGraphArtifactRecorder,
    build_agent_loop_graph_activity_binding_bundle,
)
from framework.harness.artifacts import ArtifactRef, ArtifactWriteRequest
from framework.harness.control_plane.activity import (
    harness_activity_input_checksum,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.graph_state import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.graph.activity import HarnessLeafActivityKind
from framework.harness.graph.bindings import HarnessActivityUsage
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)
from framework.harness.runtime.activity_executor import (
    HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY,
    HarnessGraphActivityExecutionInput,
    HarnessGraphActivityTaskContext,
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.workers.result import HarnessWorkerStatus
from framework.llm import FakeLLMClient
from framework.shared.attempts import AttemptSupervisor
from framework.shared.redaction import REDACTED_VALUE
from framework.tool import ToolRegistry
from infrastructure.storage.conversation import LocalJsonConversationStore


_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
_WORKER_REF = HarnessContractReference(
    HarnessContractKind.WORKER,
    "research.agent-loop",
    "1",
)
_ACTIVITY_REF = HarnessContractReference(
    HarnessContractKind.ACTIVITY,
    "harness.agent-loop-activity",
    "1",
)
_CHECKPOINT_REF = "checkpoint://run-1/decision-7"


class _Runner:
    def __init__(self, result: AgentLoopResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def run(self, agent: AgentSpec, inputs: dict[str, Any], **kwargs: Any) -> AgentLoopResult:
        self.calls.append({"agent": agent, "inputs": inputs, "kwargs": kwargs})
        return self.result


class _ArtifactPort:
    def __init__(self) -> None:
        self.bound_run_id: str | None = None
        self.requests: dict[str, ArtifactWriteRequest] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.manifest_calls = 0

    @contextmanager
    def bind_run(self, run_id: str) -> Iterator[str]:
        assert self.bound_run_id is None
        self.bound_run_id = run_id
        try:
            yield run_id
        finally:
            self.bound_run_id = None

    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        assert self.bound_run_id is not None
        ref = f"artifact://test/{self.bound_run_id}/{request.artifact_type}"
        existing = self.requests.get(ref)
        if existing is not None and existing != request:
            raise AssertionError("conflicting artifact write")
        self.requests[ref] = request
        self.payloads[ref] = request.to_dict()
        return ArtifactRef(
            ref=ref,
            artifact_type=request.artifact_type,
            checksum=checksum_for(request.to_dict()),
            media_type=request.media_type,
            metadata=request.metadata,
        )

    def read_artifact(self, ref: str) -> dict[str, Any]:
        return deepcopy(self.payloads[ref])

    def write_terminal_manifest(self, _manifest: object) -> None:
        self.manifest_calls += 1
        raise AssertionError("Graph AgentLoop worker cannot publish a manifest")


class _InputResolver:
    def __init__(self, value: HarnessGraphActivityExecutionInput) -> None:
        self.value = value

    def resolve_execution_input(
        self,
        _activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        return self.value


class _ResultCommitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def commit_execution_result(self, **values: Any):
        self.calls.append(values)
        return values["result"]


def test_graph_worker_binds_agent_runner_artifacts_and_graph_identity() -> None:
    raw_task = _raw_task(resume_from_cursor=True)
    activity = _activity(raw_task)
    runner = _Runner(_success_result())
    port = _ArtifactPort()
    bundle = _bundle(runner, port)

    result = bundle.worker_binding.implementation.execute(
        _worker_task(raw_task, activity)
    )

    assert result.status is HarnessWorkerStatus.SUCCEEDED
    assert len(runner.calls) == 1
    assert runner.calls[0]["agent"] == _agent()
    assert runner.calls[0]["inputs"] == {"topic": "graph-only"}
    assert runner.calls[0]["kwargs"] == {
        "conversation_id": "conversation-1",
        "run_id": "run-1",
        "node_instance_id": "compose:1",
        "graph_checkpoint_ref": _CHECKPOINT_REF,
        "resume_from_cursor": True,
    }
    assert "step_id" not in runner.calls[0]["kwargs"]
    assert "workflow_checkpoint_id" not in runner.calls[0]["kwargs"]
    assert len(result.artifacts) == 1
    assert len(port.requests) == 1
    assert port.manifest_calls == 0
    output = AgentLoopGraphActivityOutput.from_dict(
        result.output["agent_loop_result"]
    )
    assert output.agent_id == "research-agent"
    assert output.artifact_refs == result.artifacts
    assert output.result["llm_call_artifact_count"] == 1
    assert "llm_call_artifacts" not in output.result
    assert "events" not in output.result
    assert "trace" not in output.result
    assert "trajectory" not in output.result
    assert "tool_calls" not in output.result
    assert output.result["event_types"] == ("llm_stream_event",)
    assert "raw-stream-secret" not in str(output.to_dict())
    assert output.task_context_checksum == HarnessGraphActivityTaskContext(
        activity=activity,
        graph_checkpoint_ref=_CHECKPOINT_REF,
    ).context_checksum
    assert {item.evidence_type for item in result.evidence} == {
        "agent_loop_llm_call_artifacts"
    }


def test_binding_bundle_is_exact_serial_and_never_installs_or_dispatches() -> None:
    bundle = _bundle(_Runner(_success_result()), _ArtifactPort())

    resolved = bundle.authority.resolve_leaf_activity(
        worker_ref=_WORKER_REF,
        activity_ref=_ACTIVITY_REF,
        expected_leaf_activity_kind=HarnessLeafActivityKind.AGENT_LOOP,
        required_usage=HarnessActivityUsage.SERIAL,
    )

    assert resolved.worker == bundle.worker_binding
    assert resolved.activity == bundle.activity_binding
    assert bundle.to_manifest() == {
        "schema_version": "newsroom.agent-loop-graph-activity-binding/v1",
        "installs_runtime_authority": False,
        "worker_ref": _WORKER_REF.to_dict(),
        "activity_ref": _ACTIVITY_REF.to_dict(),
        "leaf_activity_kind": "agent_loop",
        "required_usage": "serial",
        "agent_id": "research-agent",
        "result_output_key": "agent_loop_result",
        "artifact_owner_required": True,
        "publishes_terminal_manifest": False,
        "registers_graph_wait": False,
    }
    with pytest.raises(HarnessValidationError) as parallel_error:
        bundle.authority.resolve_leaf_activity(
            worker_ref=_WORKER_REF,
            activity_ref=_ACTIVITY_REF,
            expected_leaf_activity_kind=HarnessLeafActivityKind.AGENT_LOOP,
            required_usage=HarnessActivityUsage.PARALLEL,
        )
    assert parallel_error.value.code == "activity_contract_safety_unproven"
    with pytest.raises(HarnessValidationError) as dispatch_error:
        bundle.activity_binding.implementation.dispatch({})
    assert dispatch_error.value.code == "agent_loop_legacy_dispatch_forbidden"


def test_physical_graph_executor_commits_agent_loop_candidate_output() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    runner = _Runner(_success_result())
    port = _ArtifactPort()
    bundle = _bundle(runner, port)
    execution_input = HarnessGraphActivityExecutionInput.for_activity(
        activity,
        task=raw_task,
        leaf_activity_kind=HarnessLeafActivityKind.AGENT_LOOP,
        required_usage=HarnessActivityUsage.SERIAL,
        graph_checkpoint_ref=_CHECKPOINT_REF,
        output_keys=("agent_loop_result",),
    )
    resource = InMemoryHarnessNodeOutputResource()
    committer = _ResultCommitter()
    executor = HarnessGraphPhysicalActivityExecutor(
        binding_authority=bundle.authority,
        input_resolver=_InputResolver(execution_input),
        node_output_resource=resource,
        result_committer=committer,
        supervisor=AttemptSupervisor(clock=lambda: _NOW.timestamp()),
        clock=lambda: _NOW,
    )

    receipt = executor.execute(activity, attempt_id="agent-loop-attempt-1")

    assert receipt.worker_result is not None
    assert receipt.worker_result.status is HarnessWorkerStatus.SUCCEEDED
    assert receipt.node_output_commit is not None
    assert set(receipt.node_output_commit.candidate.output_refs) == {
        "agent_loop_result"
    }
    assert {
        item.evidence_checksum for item in receipt.worker_result.evidence
    }.issubset(set(receipt.node_output_commit.candidate.evidence_refs))
    assert receipt.graph_result == committer.calls[0]["result"]
    assert bundle.activity_binding.implementation.capabilities.parallel_safe is False
    assert port.manifest_calls == 0


def test_real_agent_runner_executes_offline_through_graph_worker(tmp_path) -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    store = LocalJsonConversationStore(tmp_path / "conversations")
    runner = AgentRunner(
        llm_client=FakeLLMClient(
            [
                json.dumps(
                        {
                            "action_type": "final_output",
                            "output": {"output": {"summary": "graph-bound"}},
                        }
                )
            ]
        ),
        tool_registry=ToolRegistry(),
        conversation_store=store,
    )
    port = _ArtifactPort()

    result = _bundle(runner, port).worker_binding.implementation.execute(
        _worker_task(raw_task, activity)
    )

    assert result.status is HarnessWorkerStatus.SUCCEEDED
    assert len(result.artifacts) == 1
    assert len(port.requests) == 1
    cursor = store.read_cursor("conversation-1")
    checkpoint = store.read_iteration_checkpoint("conversation-1")
    assert cursor is not None
    assert checkpoint is not None
    assert (
        cursor.run_id,
        cursor.node_instance_id,
        cursor.graph_checkpoint_ref,
    ) == ("run-1", "compose:1", _CHECKPOINT_REF)
    assert (
        checkpoint.run_id,
        checkpoint.node_instance_id,
        checkpoint.graph_checkpoint_ref,
    ) == ("run-1", "compose:1", _CHECKPOINT_REF)
    assert port.manifest_calls == 0


def test_waiting_result_produces_candidate_evidence_without_registering_wait() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    runner = _Runner(_waiting_result())
    port = _ArtifactPort()

    result = _bundle(runner, port).worker_binding.implementation.execute(
        _worker_task(raw_task, activity)
    )

    assert result.status is HarnessWorkerStatus.WAITING_APPROVAL
    wait_evidence = next(
        item
        for item in result.evidence
        if item.evidence_type == AGENT_LOOP_GRAPH_WAIT_EVIDENCE_TYPE
    )
    candidate = AgentLoopGraphWaitCandidate.from_dict(wait_evidence.payload)
    assert candidate.run_id == activity.run_id
    assert candidate.node_instance_id == activity.node_instance_id
    assert candidate.graph_checkpoint_ref == _CHECKPOINT_REF
    assert candidate.task_context_checksum == HarnessGraphActivityTaskContext(
        activity=activity,
        graph_checkpoint_ref=_CHECKPOINT_REF,
    ).context_checksum
    assert candidate.approval_requests[0].approval_id == "approval-1"
    assert candidate.approval_requests[0].approval_kind == "tool_approval"
    output = AgentLoopGraphActivityOutput.from_dict(
        result.output["agent_loop_result"]
    )
    assert output.wait_candidate_checksum == candidate.candidate_checksum
    assert port.manifest_calls == 0


def test_graph_worker_rejects_task_identity_alias_or_worker_substitution() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    runner = _Runner(_success_result())
    port = _ArtifactPort()
    worker = _bundle(runner, port).worker_binding.implementation
    injected = _worker_task(raw_task, activity)
    injected["run_id"] = "forged-run"

    with pytest.raises(HarnessValidationError) as task_error:
        worker.execute(injected)

    assert task_error.value.code == "agent_loop_graph_activity_contract_invalid"
    assert runner.calls == []
    assert port.requests == {}

    other_activity_contract = _activity(
        raw_task,
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            "harness.other-agent-loop-activity",
            "1",
        ),
    )
    with pytest.raises(HarnessValidationError) as activity_binding_error:
        worker.execute(_worker_task(raw_task, other_activity_contract))
    assert activity_binding_error.value.code == (
        "agent_loop_graph_activity_binding_mismatch"
    )
    assert runner.calls == []
    assert port.requests == {}

    other_activity = _activity(
        raw_task,
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            "research.other-agent-loop",
            "1",
        ),
    )
    with pytest.raises(HarnessValidationError) as binding_error:
        worker.execute(_worker_task(raw_task, other_activity))
    assert binding_error.value.code == "agent_loop_graph_activity_binding_mismatch"
    assert runner.calls == []
    assert port.requests == {}


def test_graph_worker_rejects_publication_shaped_agent_output_before_artifact_write() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    result = _success_result(output={"publication_decision": "publish"})
    runner = _Runner(result)
    port = _ArtifactPort()

    with pytest.raises(HarnessValidationError) as captured:
        _bundle(runner, port).worker_binding.implementation.execute(
            _worker_task(raw_task, activity)
        )

    assert captured.value.code == "worker_decision_field_rejected"
    assert len(runner.calls) == 1
    assert port.requests == {}
    assert port.manifest_calls == 0


def test_graph_worker_redacts_sensitive_candidate_output() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    result = _success_result(
        output={
            "summary": "done",
            "api_key": "candidate-secret",
            "message": "Authorization: Bearer secret-token",
        }
    )

    worker_result = _bundle(
        _Runner(result),
        _ArtifactPort(),
    ).worker_binding.implementation.execute(_worker_task(raw_task, activity))

    output = AgentLoopGraphActivityOutput.from_dict(
        worker_result.output["agent_loop_result"]
    )
    assert output.result["output"]["api_key"] == REDACTED_VALUE
    assert "secret-token" not in output.result["output"]["message"]


def test_waiting_result_without_durable_approval_identity_fails_closed() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    waiting = _waiting_result(approval_id=None)
    runner = _Runner(waiting)
    port = _ArtifactPort()

    with pytest.raises(HarnessValidationError):
        _bundle(runner, port).worker_binding.implementation.execute(
            _worker_task(raw_task, activity)
        )

    assert len(runner.calls) == 1
    assert port.requests == {}


def test_graph_activity_output_and_wait_candidate_reject_checksum_tamper() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    result = _bundle(
        _Runner(_waiting_result()),
        _ArtifactPort(),
    ).worker_binding.implementation.execute(_worker_task(raw_task, activity))
    output = deepcopy(result.output["agent_loop_result"])
    output["agent_id"] = "another-agent"
    wait_evidence = next(
        item
        for item in result.evidence
        if item.evidence_type == AGENT_LOOP_GRAPH_WAIT_EVIDENCE_TYPE
    )
    wait_candidate = deepcopy(dict(wait_evidence.payload))
    wait_candidate["node_instance_id"] = "another-node:1"

    with pytest.raises(HarnessValidationError) as output_error:
        AgentLoopGraphActivityOutput.from_dict(output)
    with pytest.raises(HarnessValidationError) as wait_error:
        AgentLoopGraphWaitCandidate.from_dict(wait_candidate)

    assert output_error.value.code == "agent_loop_graph_activity_contract_invalid"
    assert wait_error.value.code == "agent_loop_graph_wait_candidate_invalid"


def test_graph_worker_rejects_cross_agent_diagnostics() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    waiting = _waiting_result()
    assert waiting.diagnostics is not None
    mismatched = replace(
        waiting,
        diagnostics=replace(waiting.diagnostics, agent_id="another-agent"),
    )
    runner = _Runner(mismatched)
    port = _ArtifactPort()

    with pytest.raises(HarnessValidationError) as captured:
        _bundle(runner, port).worker_binding.implementation.execute(
            _worker_task(raw_task, activity)
        )

    assert captured.value.code == "agent_loop_graph_activity_result_invalid"
    assert port.requests == {}


def _bundle(runner: Any, port: _ArtifactPort):
    return build_agent_loop_graph_activity_binding_bundle(
        worker_ref=_WORKER_REF,
        activity_ref=_ACTIVITY_REF,
        agent_runner=runner,
        agent=_agent(),
        artifact_recorder=AgentLoopGraphArtifactRecorder(port),
    )


def _agent() -> AgentSpec:
    return AgentSpec(
        agent_id="research-agent",
        name="Research Agent",
        instructions="Analyze the supplied evidence.",
    )


def _raw_task(*, resume_from_cursor: bool = False) -> dict[str, Any]:
    return {
        "schema_version": AGENT_LOOP_GRAPH_ACTIVITY_TASK_SCHEMA,
        "inputs": {"topic": "graph-only"},
        "conversation_id": "conversation-1",
        "resume_from_cursor": resume_from_cursor,
    }


def _worker_task(
    raw_task: dict[str, Any],
    activity: HarnessGraphActivity,
) -> dict[str, Any]:
    return {
        **raw_task,
        HARNESS_GRAPH_ACTIVITY_TASK_CONTEXT_KEY: HarnessGraphActivityTaskContext(
            activity=activity,
            graph_checkpoint_ref=_CHECKPOINT_REF,
        ).to_dict(),
    }


def _activity(
    raw_task: dict[str, Any],
    *,
    worker_ref: HarnessContractReference = _WORKER_REF,
    activity_ref: HarnessContractReference = _ACTIVITY_REF,
) -> HarnessGraphActivity:
    graph_ref = HarnessGraphReference(
        graph_id="research.graph",
        workflow_ref=HarnessContractReference(
            HarnessContractKind.WORKFLOW,
            "research.graph",
            "2",
        ),
        schema_version=NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=checksum_for({"graph": "research.graph", "version": "2"}),
    )
    return HarnessGraphActivity(
        run_id="run-1",
        graph_ref=graph_ref,
        node_id="compose",
        node_instance_id="compose:1",
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            "compose",
            "1",
        ),
        worker_ref=worker_ref,
        activity_ref=activity_ref,
        attempt=1,
        input_ref=harness_activity_input_checksum(raw_task),
        causal_decision_checksum=checksum_for({"decision": "dispatch"}),
        causal_decision_sequence=7,
        fencing_generation=3,
    )


def _success_result(
    *,
    output: dict[str, Any] | None = None,
) -> AgentLoopResult:
    return AgentLoopResult(
        success=True,
        status=AgentLoopStatus.SUCCEEDED,
        output=output or {"summary": "done"},
        iterations=1,
        metrics=AgentLoopMetrics(iterations=1, llm_calls=1),
        events=[
            {
                "event_type": "llm_stream_event",
                "stream_event": {"text_delta": "raw-stream-secret"},
            }
        ],
        trace={"response": "raw-stream-secret"},
        trajectory=[{"response": "raw-stream-secret"}],
        tool_calls=[{"arguments": {"value": "raw-stream-secret"}}],
        llm_call_artifacts=[
            LLMCallArtifact(
                artifact_id="research-agent:llm_call:1",
                iteration=1,
                request={"messages": [{"role": "user", "content": "topic"}]},
                response={"content": "done"},
                metadata={"agent_id": "research-agent", "provider": "fake"},
            )
        ],
        termination_reason=AgentLoopStopReason.FINAL_ANSWER.value,
    )


def _waiting_result(*, approval_id: str | None = "approval-1") -> AgentLoopResult:
    diagnostics = AgentLoopDiagnostics(
        agent_id="research-agent",
        status=AgentLoopStatus.WAITING_FOR_APPROVAL,
        stop_reason=AgentLoopStopReason.TOOL_APPROVAL_REQUIRED,
        summary="approval required",
        healthy=False,
        severity=AgentLoopDiagnosticSeverity.WARNING,
        iterations=1,
        approval_requests=1,
        issues=[
            AgentLoopIssue(
                code="tool_approval_required",
                message="approval required",
                severity=AgentLoopDiagnosticSeverity.WARNING,
                iteration=1,
                tool_name="report.publish",
                metadata={
                    "approval_id": approval_id,
                    "approval_kind": "tool_approval",
                },
            )
        ],
    )
    return AgentLoopResult(
        success=False,
        status=AgentLoopStatus.WAITING_FOR_APPROVAL,
        iterations=1,
        metrics=AgentLoopMetrics(
            iterations=1,
            llm_calls=1,
            tool_approval_requests=1,
        ),
        diagnostics=diagnostics,
        llm_call_artifacts=[
            LLMCallArtifact(
                artifact_id="research-agent:llm_call:1",
                iteration=1,
                request={"messages": []},
                response={"tool_call": "report.publish"},
                metadata={"agent_id": "research-agent", "provider": "fake"},
            )
        ],
        error="approval required",
        termination_reason=AgentLoopStopReason.TOOL_APPROVAL_REQUIRED.value,
    )
