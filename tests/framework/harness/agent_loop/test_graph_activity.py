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
    AgentAction,
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
    AGENT_LOOP_GRAPH_APPROVAL_WAIT_FACT_SCHEMA,
    AGENT_LOOP_GRAPH_ACTIVITY_TASK_SCHEMA,
    AGENT_LOOP_GRAPH_WAIT_EVIDENCE_TYPE,
    AgentLoopGraphActivityOutput,
    AgentLoopGraphApprovalWaitBinding,
    AgentLoopGraphApprovalWaitFact,
    AgentLoopGraphWaitCandidate,
    AgentLoopGraphArtifactRecorder,
    build_agent_loop_graph_activity_binding_bundle,
)
from framework.harness.artifacts import ArtifactRef, ArtifactWriteRequest
from framework.harness.control_plane.activity import (
    harness_activity_input_checksum,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.gate_registry import (
    DeterministicGateRegistry,
)
from framework.harness.control_plane.gates import GateContext
from framework.harness.control_plane.harness import (
    HarnessControlPlane,
    InMemoryHarnessEventPort,
)
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    graph_reference,
)
from framework.harness.control_plane.graph_state import (
    HarnessGraphNodeKind,
    HarnessGraphReference,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceStatus,
    HarnessWaitStatus,
    RunLifecycle,
    RunOutcome,
)
from framework.harness.control_plane.state import HarnessRunSpec, HarnessState
from framework.harness.control_plane.transitions import get_step_state
from framework.harness.control_plane.node_output import (
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.graph.activity import (
    HarnessLeafActivityKind,
    HarnessStepSpec,
)
from framework.harness.graph.bindings import HarnessActivityUsage
from framework.harness.graph.dsl import (
    Choice,
    ChoiceBranch,
    HarnessGraphSpec,
    Sequence,
    StepRef,
)
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
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus
from framework.harness.waits.models import (
    HarnessWaitApprovalEvidenceRecord,
    HarnessWaitScope,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
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
_TENANT_SCOPE_REF = checksum_for({"tenant": "tenant-1"})
_IDENTITY_SCOPE_REF = checksum_for({"identity": "research-agent"})
_GRAPH_ID = "research.graph"
_GRAPH_VERSION = "2"
_GRAPH_CHECKSUM = checksum_for({"graph": _GRAPH_ID, "version": _GRAPH_VERSION})


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
    assert result.diagnostics["requested_tools"] == ["memory.search"]
    assert len(port.requests) == 1
    assert port.manifest_calls == 0
    output = AgentLoopGraphActivityOutput.from_dict(
        result.output["agent_loop_result"]
    )
    assert output.agent_id == "research-agent"
    assert output.waiting is False
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
        "schema_version": "newsroom.agent-loop-graph-activity-binding/v2",
        "installs_runtime_authority": False,
        "worker_ref": _WORKER_REF.to_dict(),
        "activity_ref": _ACTIVITY_REF.to_dict(),
        "leaf_activity_kind": "agent_loop",
        "required_usage": "serial",
        "agent_id": "research-agent",
        "result_output_key": "agent_loop_result",
        "artifact_owner_required": True,
        "wait_candidate_gate_ref": "agent_loop_wait_candidate@1",
        "tenant_scope_input_key": "tenant_scope_ref",
        "identity_scope_input_key": "identity_scope_ref",
        "waiting_candidate_worker_status": "succeeded",
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


def test_physical_executor_commits_waiting_candidate_as_node_output() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    port = _ArtifactPort()
    bundle = _bundle(_Runner(_waiting_result()), port)
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

    receipt = executor.execute(activity, attempt_id="agent-loop-wait-attempt-1")

    assert receipt.worker_result is not None
    assert receipt.worker_result.status is HarnessWorkerStatus.SUCCEEDED
    assert receipt.node_output_commit is not None
    assert receipt.graph_result is not None
    output = AgentLoopGraphActivityOutput.from_dict(
        receipt.worker_result.output["agent_loop_result"]
    )
    assert output.approval_wait is not None
    assert output.approval_wait.approval_id == "approval-1"
    assert bundle.wait_gate_registration.gate.evaluate(
        _gate_context(receipt.worker_result)
    ).passed is True
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


def test_waiting_result_produces_successful_candidate_for_explicit_graph_wait() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    runner = _Runner(_waiting_result())
    port = _ArtifactPort()

    result = _bundle(runner, port).worker_binding.implementation.execute(
        _worker_task(raw_task, activity)
    )

    assert result.status is HarnessWorkerStatus.SUCCEEDED
    assert result.error is None
    assert result.diagnostics["requested_tools"] == ["report.publish"]
    wait_evidence = next(
        item
        for item in result.evidence
        if item.evidence_type == AGENT_LOOP_GRAPH_WAIT_EVIDENCE_TYPE
    )
    candidate = AgentLoopGraphWaitCandidate.from_dict(wait_evidence.payload)
    assert candidate.run_id == activity.run_id
    assert candidate.graph_id == activity.graph_ref.graph_id
    assert candidate.graph_version == activity.graph_ref.workflow_ref.version
    assert candidate.graph_checksum == activity.graph_ref.checksum
    assert candidate.node_instance_id == activity.node_instance_id
    assert candidate.graph_checkpoint_ref == _CHECKPOINT_REF
    assert candidate.task_context_checksum == HarnessGraphActivityTaskContext(
        activity=activity,
        graph_checkpoint_ref=_CHECKPOINT_REF,
    ).context_checksum
    assert candidate.approval_requests[0].approval_id == "approval-1"
    assert candidate.approval_requests[0].approval_kind == "tool_approval"
    assert candidate.tenant_scope_ref == _TENANT_SCOPE_REF
    assert candidate.identity_scope_ref == _IDENTITY_SCOPE_REF
    output = AgentLoopGraphActivityOutput.from_dict(
        result.output["agent_loop_result"]
    )
    assert output.wait_candidate_checksum == candidate.candidate_checksum
    assert output.waiting is True
    assert output.approval_wait == AgentLoopGraphApprovalWaitFact.from_candidate(
        candidate
    )
    gate_result = _bundle(
        _Runner(_waiting_result()),
        _ArtifactPort(),
    ).wait_gate_registration.gate.evaluate(_gate_context(result))
    assert gate_result.passed is True
    assert gate_result.details["reason_code"] == (
        "agent_loop_wait_candidate_verified"
    )
    assert gate_result.details["correlation_ref"] == (
        output.approval_wait.correlation_ref
    )
    assert port.manifest_calls == 0


def test_verified_wait_candidate_registers_and_resumes_explicit_graph_wait() -> None:
    binding = AgentLoopGraphApprovalWaitBinding(
        source_node_id="agent_loop",
        result_output_key="agent_loop_result",
        wait_id="agent-loop-approval",
    )
    source = HarnessStepSpec(
        "agent_loop",
        "agent_loop",
        output_key="agent_loop_result",
        quality_gate=binding.gate_ref,
        metadata={
            "step_version": "1",
            "worker_version": "1",
            "tool_allowlist": ("report.publish",),
            "control_fact_paths": binding.control_fact_paths,
        },
    )
    after = HarnessStepSpec(
        "after",
        "function",
        metadata={"step_version": "1", "worker_version": "1"},
    )
    binding.assert_step_contract(source)
    binding_manifest = binding.to_manifest()
    assert binding_manifest["registers_graph_wait"] is False
    assert binding_manifest["requires_deterministic_wait_branch"] is True
    assert binding_manifest["wait"]["wait_kind"] == "approval"
    assert binding_manifest["waiting_condition"] == (
        binding.waiting_condition().to_dict()
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="agent-loop-approval-graph",
        workflow_version="2",
        steps=(source, after),
        entry_step_id=source.step_id,
        graph=HarnessGraphSpec(
            graph_id="agent-loop-approval-graph",
            root=Sequence(
                (
                    StepRef(source.step_id),
                    Choice(
                        "agent-loop-wait-choice",
                        (
                            ChoiceBranch(
                                "wait-for-approval",
                                Sequence(
                                    (
                                        binding.wait_expression(),
                                        StepRef(
                                            after.step_id,
                                            node_id="after-wait",
                                        ),
                                    )
                                ),
                                priority=0,
                                condition=binding.waiting_condition(),
                            ),
                            ChoiceBranch(
                                "continue",
                                StepRef(
                                    after.step_id,
                                    node_id="after-immediate",
                                ),
                                priority=1,
                                is_default=True,
                            ),
                        ),
                    ),
                )
            ),
            input_keys=("identity_scope_ref", "tenant_scope_ref"),
        ),
    )
    bundle = _bundle(_Runner(_waiting_result()), _ArtifactPort())
    calls: list[str] = []
    event_port = InMemoryHarnessEventPort()
    control_plane = HarnessControlPlane(
        event_port=event_port,
        gate_registry=DeterministicGateRegistry(
            (bundle.wait_gate_registration,)
        ),
        worker_registry={
            "after": lambda _task: (
                calls.append("after") or _successful_worker_result()
            ),
        },
    )
    run_spec = HarnessRunSpec(
        "agent-loop-approval-run",
        workflow,
        inputs={
            "tenant_scope_ref": _TENANT_SCOPE_REF,
            "identity_scope_ref": _IDENTITY_SCOPE_REF,
        },
        metadata={
            "tenant_scope_ref": _TENANT_SCOPE_REF,
            "identity_scope_ref": _IDENTITY_SCOPE_REF,
        },
        created_at=_NOW,
    )
    normalized_graph = control_plane._graph_replay_recovery(
        run_spec,
        compile_only=True,
    )
    source_instance_id = HarnessNodeInstanceIdentity(
        run_id="agent-loop-approval-run",
        graph_checksum=normalized_graph.checksum,
        node_id="agent_loop",
        activation_ordinal=1,
    ).instance_id
    raw_task = _raw_task()
    candidate_result = bundle.worker_binding.implementation.execute(
        _worker_task(
            raw_task,
            _activity(
                raw_task,
                run_id="agent-loop-approval-run",
                node_id="agent_loop",
                node_instance_id=source_instance_id,
                graph_ref=graph_reference(normalized_graph),
            ),
        )
    )
    activity_output = AgentLoopGraphActivityOutput.from_dict(
        candidate_result.output["agent_loop_result"]
    )
    wait_fact = activity_output.approval_wait
    assert wait_fact is not None
    control_plane.worker_registry["agent_loop"] = lambda _task: candidate_result

    waiting = control_plane.run(run_spec).graph_state

    assert waiting is not None
    assert waiting.lifecycle is RunLifecycle.WAITING
    source_node = next(
        item
        for item in waiting.node_instances
        if item.identity.node_id == source.step_id
    )
    assert source_node.status is HarnessNodeInstanceStatus.SUCCEEDED
    registration = waiting.wait_registrations[0]
    wait_node = next(
        item
        for item in waiting.node_instances
        if item.instance_id == registration.node_instance_id
    )
    assert wait_node.node_kind is HarnessGraphNodeKind.WAIT
    assert wait_node.identity.node_id == binding.wait_id
    assert registration.status is HarnessWaitStatus.REGISTERED
    assert registration.tenant_scope_ref == _TENANT_SCOPE_REF
    assert registration.identity_scope_ref == _IDENTITY_SCOPE_REF
    assert registration.signal_schema_ref == "newsroom.agent-loop.approval@1"
    assert registration.correlation_ref == checksum_for(
        {
            **wait_fact.correlation_projection(),
            "schema_version": AGENT_LOOP_GRAPH_APPROVAL_WAIT_FACT_SCHEMA,
            "tenant_scope_ref": wait_fact.tenant_scope_ref,
            "identity_scope_ref": wait_fact.identity_scope_ref,
            "correlation_ref": wait_fact.correlation_ref,
        }
    )
    assert calls == []
    scope = HarnessWaitScope(
        wait_id=registration.wait_id,
        run_id=run_spec.run_id,
        node_instance_id=registration.node_instance_id,
        tenant_scope_ref=registration.tenant_scope_ref,
        identity_scope_ref=registration.identity_scope_ref,
        signal_schema_ref=registration.signal_schema_ref,
        correlation_ref=registration.correlation_ref,
    )
    resumed = control_plane.accept_graph_wait_cause(
        run_spec,
        HarnessWaitApprovalEvidenceRecord(
            scope=scope,
            approval_event_ref=checksum_for(
                {"approval_id": wait_fact.approval_id}
            ),
            actor_identity_scope_ref=checksum_for({"actor": "reviewer"}),
            approved=True,
            recorded_sequence=0,
        ),
        occurred_at=_NOW,
    )

    assert resumed.wait_registrations[0].status is HarnessWaitStatus.RESUMED
    completed = control_plane.recover_and_run(run_spec).graph_state
    assert completed is not None
    assert completed.outcome is RunOutcome.SUCCEEDED
    assert calls == ["after"]


def test_approval_wait_binding_rejects_legacy_or_unverified_step_contract() -> None:
    binding = AgentLoopGraphApprovalWaitBinding(
        source_node_id="agent_loop",
        result_output_key="agent_loop_result",
        wait_id="agent-loop-approval",
    )
    legacy = HarnessStepSpec(
        "agent_loop",
        "agent_loop",
        output_key="agent_loop_result",
        quality_gate=binding.gate_ref,
        metadata={
            "control_fact_paths": binding.control_fact_paths,
            "approval_required": True,
        },
    )
    unverified = HarnessStepSpec(
        "agent_loop",
        "agent_loop",
        output_key="agent_loop_result",
        metadata={"control_fact_paths": binding.control_fact_paths},
    )

    with pytest.raises(HarnessValidationError) as legacy_error:
        binding.assert_step_contract(legacy)
    with pytest.raises(HarnessValidationError) as gate_error:
        binding.assert_step_contract(unverified)

    assert legacy_error.value.code == "agent_loop_graph_wait_binding_mismatch"
    assert legacy_error.value.details["mismatches"] == [
        "legacy_approval_required"
    ]
    assert gate_error.value.details["mismatches"] == ["gate_ref"]


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


def test_waiting_result_requires_scoped_single_approval_before_artifact_write() -> None:
    raw_task = _raw_task()
    unscoped = _activity(raw_task, include_scope=False)
    runner = _Runner(_waiting_result())
    port = _ArtifactPort()

    with pytest.raises(HarnessValidationError) as scope_error:
        _bundle(runner, port).worker_binding.implementation.execute(
            _worker_task(raw_task, unscoped)
        )

    waiting = _waiting_result()
    assert waiting.diagnostics is not None
    duplicate = replace(
        waiting,
        diagnostics=replace(
            waiting.diagnostics,
            issues=(
                *waiting.diagnostics.issues,
                AgentLoopIssue(
                    severity=AgentLoopDiagnosticSeverity.WARNING,
                    code="tool_approval_required",
                    message="second approval required",
                    tool_name="second_tool",
                    metadata={
                        "approval_id": "approval-2",
                        "approval_kind": "tool_approval",
                    },
                ),
            ),
        ),
    )
    with pytest.raises(HarnessValidationError) as count_error:
        _bundle(_Runner(duplicate), port).worker_binding.implementation.execute(
            _worker_task(raw_task, _activity(raw_task))
        )

    assert scope_error.value.code == "agent_loop_graph_activity_contract_invalid"
    assert count_error.value.code == "agent_loop_graph_wait_candidate_invalid"
    assert port.requests == {}


def test_wait_gate_rejects_output_evidence_mismatch() -> None:
    raw_task = _raw_task()
    activity = _activity(raw_task)
    bundle = _bundle(_Runner(_waiting_result()), _ArtifactPort())
    worker_result = bundle.worker_binding.implementation.execute(
        _worker_task(raw_task, activity)
    )
    raw_output = deepcopy(worker_result.output["agent_loop_result"])
    assert isinstance(raw_output["approval_wait"], dict)
    raw_output["approval_wait"]["approval_id"] = "forged-approval"
    forged = replace(
        worker_result,
        output={"agent_loop_result": raw_output},
    )

    result = bundle.wait_gate_registration.gate.evaluate(_gate_context(forged))

    assert result.passed is False
    assert result.details["reason_code"] == "agent_loop_wait_output_invalid"

    cross_run = bundle.wait_gate_registration.gate.evaluate(
        _gate_context(worker_result, run_id="another-run")
    )
    cross_scope = bundle.wait_gate_registration.gate.evaluate(
        _gate_context(
            worker_result,
            tenant_scope_ref=checksum_for({"tenant": "another"}),
        )
    )
    cross_graph = bundle.wait_gate_registration.gate.evaluate(
        _gate_context(
            worker_result,
            graph_id="another.graph",
            graph_checksum=checksum_for({"graph": "another.graph"}),
        )
    )
    cross_node_attempt = bundle.wait_gate_registration.gate.evaluate(
        _gate_context(
            worker_result,
            node_instance_id="compose:2",
            activity_attempt=2,
        )
    )
    assert cross_run.passed is False
    assert cross_run.details["reason_code"] == (
        "agent_loop_wait_output_evidence_mismatch"
    )
    assert cross_run.details["mismatches"] == ["run_id"]
    assert cross_scope.passed is False
    assert cross_scope.details["mismatches"] == ["tenant_scope_ref"]
    assert cross_graph.passed is False
    assert cross_graph.details["mismatches"] == [
        "graph_id",
        "graph_checksum",
    ]
    assert cross_node_attempt.passed is False
    assert cross_node_attempt.details["mismatches"] == [
        "node_instance_id",
        "activity_attempt",
    ]


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


def _gate_context(
    worker_result,
    *,
    run_id: str = "run-1",
    step_id: str = "compose",
    graph_id: str = _GRAPH_ID,
    graph_version: str = _GRAPH_VERSION,
    graph_checksum: str = _GRAPH_CHECKSUM,
    node_instance_id: str = "compose:1",
    activity_attempt: int = 1,
    tenant_scope_ref: str = _TENANT_SCOPE_REF,
    identity_scope_ref: str = _IDENTITY_SCOPE_REF,
) -> GateContext:
    step = HarnessStepSpec(
        step_id,
        "agent_loop",
        output_key="agent_loop_result",
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=graph_id,
        workflow_version=graph_version,
        steps=(step,),
        entry_step_id=step.step_id,
    )
    initial = HarnessState.initial(
        HarnessRunSpec(
            run_id,
            workflow,
            inputs={
                "tenant_scope_ref": tenant_scope_ref,
                "identity_scope_ref": identity_scope_ref,
            },
        )
    )
    step_state = replace(
        get_step_state(initial, step.step_id),
        attempts=activity_attempt,
        metadata={"node_instance_id": node_instance_id},
    )
    state = replace(
        initial,
        step_states=(step_state,),
        metadata={
            "graph_id": graph_id,
            "graph_version": graph_version,
            "graph_checksum": graph_checksum,
        },
    )
    return GateContext(
        state=state,
        step_spec=step,
        step_state=get_step_state(state, step.step_id),
        worker_result=worker_result,
    )


def _successful_worker_result() -> HarnessWorkerResult:
    return HarnessWorkerResult(HarnessWorkerStatus.SUCCEEDED)


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
    graph_ref: HarnessGraphReference | None = None,
    include_scope: bool = True,
    run_id: str = "run-1",
    node_id: str = "compose",
    node_instance_id: str = "compose:1",
    activity_attempt: int = 1,
) -> HarnessGraphActivity:
    accepted_graph_ref = graph_ref or HarnessGraphReference(
        graph_id=_GRAPH_ID,
        workflow_ref=HarnessContractReference(
            HarnessContractKind.WORKFLOW,
            _GRAPH_ID,
            _GRAPH_VERSION,
        ),
        schema_version=NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=_GRAPH_CHECKSUM,
    )
    return HarnessGraphActivity(
        run_id=run_id,
        graph_ref=accepted_graph_ref,
        node_id=node_id,
        node_instance_id=node_instance_id,
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            node_id,
            "1",
        ),
        worker_ref=worker_ref,
        activity_ref=activity_ref,
        attempt=activity_attempt,
        input_ref=harness_activity_input_checksum(raw_task),
        causal_decision_checksum=checksum_for({"decision": "dispatch"}),
        causal_decision_sequence=7,
        fencing_generation=3,
        tenant_scope_ref=_TENANT_SCOPE_REF if include_scope else None,
        identity_scope_ref=_IDENTITY_SCOPE_REF if include_scope else None,
    )


def _success_result(
    *,
    output: dict[str, Any] | None = None,
) -> AgentLoopResult:
    return AgentLoopResult(
        success=True,
        status=AgentLoopStatus.SUCCEEDED,
        output=output or {"summary": "done"},
        actions=[AgentAction.tool_call("memory.search", {"query": "topic"})],
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
        tool_calls=[
            {
                "tool_name": "memory.search",
                "arguments": {"value": "raw-stream-secret"},
            }
        ],
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
