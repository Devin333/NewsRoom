from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy

import pytest

from framework.harness.agent_loop.artifacts import (
    AGENT_LOOP_GRAPH_ARTIFACT_EVIDENCE_TYPE,
    AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA,
    AgentLoopGraphArtifactContext,
    AgentLoopGraphArtifactReceipt,
    AgentLoopGraphArtifactRecorder,
)
from framework.agent.models import LLMCallArtifact
from framework.events.canonical import checksum_for
from framework.harness.artifacts import ArtifactRef, ArtifactWriteRequest
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.harness.control_plane.activity_execution import HarnessGraphActivityTaskContext
from framework.shared.redaction import REDACTED_VALUE
from infrastructure.research.artifact_port import (
    FilesystemHarnessArtifactPort,
    is_verified_internal_staged_artifact,
)


class _ArtifactPort:
    def __init__(self) -> None:
        self.bound_run_id: str | None = None
        self.bind_calls: list[str] = []
        self.requests: dict[str, ArtifactWriteRequest] = {}
        self.payloads: dict[str, dict] = {}
        self.manifest_calls = 0

    @contextmanager
    def bind_run(self, run_id: str) -> Iterator[str]:
        assert self.bound_run_id is None
        self.bound_run_id = run_id
        self.bind_calls.append(run_id)
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

    def read_artifact(self, ref: str) -> dict:
        return deepcopy(self.payloads[ref])

    def write_terminal_manifest(self, _manifest: object) -> None:
        self.manifest_calls += 1
        raise AssertionError("AgentLoop artifact recorder cannot publish a manifest")


class _TamperingArtifactPort(_ArtifactPort):
    def read_artifact(self, ref: str) -> dict:
        payload = super().read_artifact(ref)
        payload["payload"]["iteration"] = 999
        return payload


def _call(
    iteration: int,
    *,
    request: dict | None = None,
    response: dict | None = None,
    metadata: dict | None = None,
) -> LLMCallArtifact:
    return LLMCallArtifact(
        artifact_id=f"research-agent:llm_call:{iteration}",
        iteration=iteration,
        request=request or {"messages": []},
        response=response or {"content": f"answer-{iteration}"},
        metadata=metadata or {"agent_id": "research-agent", "provider": "test"},
    )


def test_recorder_persists_redacted_graph_bound_calls_without_publication() -> None:
    port = _ArtifactPort()
    context = _context()
    recorder = AgentLoopGraphArtifactRecorder(port)

    receipt = recorder.record(
        context=context,
        artifacts=(
            _call(
                1,
                request={
                    "messages": [{"role": "user", "content": "hello"}],
                    "api_key": "secret-request-key",
                },
                response={
                    "content": "answer",
                    "authorization": "Bearer response-token",
                },
                metadata={
                    "agent_id": "research-agent",
                    "provider": "test",
                    "client_secret": "metadata-secret",
                },
            ),
        ),
    )

    assert port.bind_calls == ["run-1"]
    assert port.manifest_calls == 0
    assert len(receipt.records) == 1
    assert receipt.artifact_refs == (receipt.records[0].artifact_ref.ref,)
    persisted = next(iter(port.payloads.values()))
    assert persisted["payload"]["schema_version"] == AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA
    assert persisted["payload"]["request"]["api_key"] == REDACTED_VALUE
    assert persisted["payload"]["response"]["authorization"] == REDACTED_VALUE
    assert persisted["payload"]["metadata"]["client_secret"] == REDACTED_VALUE
    metadata = persisted["metadata"]
    artifact_type = persisted["artifact_type"]
    assert artifact_type == (
        "graph-result-" + persisted["payload"]["call_checksum"].removeprefix("sha256:")
    )
    assert metadata["artifact_role"] == "agent_loop_llm_call"
    assert metadata["graph_result_ref_only"] is True
    assert metadata["identity_checksum"] == persisted["payload"]["call_checksum"]
    assert metadata["run_id"] == "run-1"
    assert metadata["graph_id"] == "research.graph"
    assert metadata["node_instance_id"] == "compose:1"
    assert metadata["graph_checkpoint_ref"] == "checkpoint://run-1/7"
    assert metadata["required_for_replay"] is True
    assert metadata["required_for_publication"] is False
    assert metadata["redacted"] is True
    assert "workflow_id" not in metadata
    assert "workflow_checkpoint_id" not in metadata
    evidence = receipt.worker_evidence()
    assert evidence.evidence_type == AGENT_LOOP_GRAPH_ARTIFACT_EVIDENCE_TYPE
    assert evidence.payload["receipt_checksum"] == receipt.receipt_checksum


def test_recorder_round_trips_through_real_artifact_owner_before_terminal_commit(
    tmp_path,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)

    receipt = AgentLoopGraphArtifactRecorder(port).record(
        context=_context(),
        artifacts=(_call(1),),
    )

    record = receipt.records[0]
    persisted = port.read_graph_result_artifact(
        record.artifact_ref.ref,
        expected_run_id="run-1",
    )
    staged = port.list_staged_artifacts("run-1")
    assert persisted["payload"]["call_checksum"] == record.call_checksum
    assert tuple(item.artifact_key for item in staged) == (
        record.artifact_ref.artifact_type,
    )
    assert is_verified_internal_staged_artifact(staged[0]) is True
    assert not (tmp_path / "run-1" / "manifest.json").exists()


def test_receipt_round_trip_and_idempotent_recording() -> None:
    port = _ArtifactPort()
    context = _context()
    recorder = AgentLoopGraphArtifactRecorder(port)
    calls = (_call(2), _call(1))

    first = recorder.record(context=context, artifacts=calls)
    second = recorder.record(context=context, artifacts=calls)

    assert first == second
    assert len(port.requests) == 2
    assert [item.iteration for item in first.records] == [1, 2]
    assert AgentLoopGraphArtifactReceipt.from_dict(first.to_dict()) == first
    assert AgentLoopGraphArtifactContext.from_dict(context.to_dict()) == context


def test_empty_call_batch_returns_checksum_bound_empty_receipt() -> None:
    port = _ArtifactPort()

    receipt = AgentLoopGraphArtifactRecorder(port).record(
        context=_context(),
        artifacts=(),
    )

    assert receipt.records == ()
    assert receipt.artifact_refs == ()
    assert port.bind_calls == ["run-1"]
    assert receipt.worker_evidence().payload == receipt.to_dict()


@pytest.mark.parametrize(
    ("calls", "code"),
    [
        ((_call(1), _call(1)), "agent_loop_graph_artifact_batch_invalid"),
        (
            (
                _call(
                    1,
                    metadata={"agent_id": "another-agent"},
                ),
            ),
            "agent_loop_graph_artifact_context_mismatch",
        ),
    ],
)
def test_recorder_rejects_duplicate_or_cross_agent_calls(
    calls: tuple[LLMCallArtifact, ...],
    code: str,
) -> None:
    port = _ArtifactPort()

    with pytest.raises(HarnessValidationError) as captured:
        AgentLoopGraphArtifactRecorder(port).record(
            context=_context(),
            artifacts=calls,
        )

    assert captured.value.code == code
    assert port.bind_calls == []


def test_recorder_fails_closed_on_artifact_read_back_tamper() -> None:
    port = _TamperingArtifactPort()

    with pytest.raises(HarnessValidationError) as captured:
        AgentLoopGraphArtifactRecorder(port).record(
            context=_context(),
            artifacts=(_call(1),),
        )

    assert captured.value.code == "agent_loop_graph_artifact_integrity_mismatch"


def test_context_requires_explicit_graph_checkpoint_and_rejects_tamper() -> None:
    context = _context()
    tampered = context.to_dict()
    tampered["node_instance_id"] = "other:1"

    with pytest.raises(HarnessValidationError) as checksum_error:
        AgentLoopGraphArtifactContext.from_dict(tampered)

    assert checksum_error.value.code == "agent_loop_graph_artifact_context_invalid"
    with pytest.raises(HarnessValidationError) as checkpoint_error:
        AgentLoopGraphArtifactContext.from_activity(
            _activity(),
            graph_version="2",
            graph_checkpoint_ref=" ",
            agent_id="research-agent",
        )
    assert checkpoint_error.value.code == "agent_loop_graph_artifact_context_invalid"


def test_context_derives_graph_identity_from_harness_task_context() -> None:
    activity = _activity()
    task_context = HarnessGraphActivityTaskContext(
        activity=activity,
        graph_checkpoint_ref="checkpoint://run-1/7",
    )

    context = AgentLoopGraphArtifactContext.from_task_context(
        task_context,
        graph_version="2",
        agent_id="research-agent",
        conversation_id="conversation-1",
    )

    assert context == _context()
    assert context.activity_id == activity.activity_id
    assert context.normalized_graph_checksum == activity.graph_ref.checksum
    assert context.graph_checkpoint_ref == task_context.graph_checkpoint_ref


def _context() -> AgentLoopGraphArtifactContext:
    return AgentLoopGraphArtifactContext.from_activity(
        _activity(),
        graph_version="2",
        graph_checkpoint_ref="checkpoint://run-1/7",
        agent_id="research-agent",
        conversation_id="conversation-1",
    )


def _activity() -> HarnessGraphActivity:
    graph_ref = HarnessGraphReference(
        graph_id="research.graph",
        graph_ref=HarnessContractReference(
            HarnessContractKind.GRAPH,
            "research.graph",
            "2",
        ),
        schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
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
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            "research.agent-loop",
            "1",
        ),
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            "harness.agent-loop-activity",
            "1",
        ),
        attempt=1,
        input_ref=checksum_for({"inputs": {"topic": "graph"}}),
        causal_decision_checksum=checksum_for({"decision": "dispatch"}),
        causal_decision_sequence=7,
        fencing_generation=3,
    )
