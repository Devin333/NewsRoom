from __future__ import annotations

from dataclasses import replace

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
    ContextAssembler,
    ContextEnvelope,
    ContextGraphIdentity,
    ContextReplayGate,
    ContextSnapshot,
    ContextSnapshotStore,
    ContextTaskExecutionIdentity,
    HarnessValidationError,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)


def _graph_envelope(*, graph_id: str = "context.graph") -> ContextEnvelope:
    graph_checksum = "sha256:" + "1" * 64
    stage_binding_checksum = "sha256:" + "2" * 64
    projection = {
        "schema_version": CONTEXT_GRAPH_TASK_PLAN_STAGE_IDENTITY_SCHEMA_V2,
        "run_id": "run-context-snapshot",
        "graph_schema_version": GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "graph_id": graph_id,
        "graph_version": "2",
        "graph_checksum": graph_checksum,
        "stage_id": "dynamic_stage",
        "stage_binding_checksum": stage_binding_checksum,
        "graph_ref": f"{graph_id}@2",
    }
    graph_identity = ContextGraphIdentity(
        run_id=projection["run_id"],
        graph_id=graph_id,
        graph_version="2",
        graph_ref=f"{graph_id}@2",
        graph_schema_version=projection["graph_schema_version"],
        compiler_version=projection["compiler_version"],
        condition_policy_version=projection["condition_policy_version"],
        graph_checksum=graph_checksum,
        stage_id=projection["stage_id"],
        stage_binding_checksum=stage_binding_checksum,
        stage_identity_schema=projection["schema_version"],
        stage_identity_checksum=checksum_for(projection),
    )
    return ContextEnvelope.for_graph(
        envelope_id="context://run-context-snapshot/dynamic-stage/task",
        graph_identity=graph_identity,
        task_execution_identity=ContextTaskExecutionIdentity(
            plan_id="plan-context-snapshot",
            plan_version=1,
            plan_checksum="sha256:" + "3" * 64,
            task_id="task",
            task_definition_checksum="sha256:" + "4" * 64,
            task_instance_id="task-attempt-1",
            attempt=1,
        ),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
    )


def test_context_snapshot_supports_replay_from_refs() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble(
        {
            "graph_identity": _graph_envelope().graph_identity,
            "phase": "VERIFY",
            "worker_id": "context-worker",
            "worker_type": "function",
        }
    )
    snapshot = assembler.snapshot_store.load(envelope.snapshot_ref or "")
    replayed = assembler.snapshot_store.replay(envelope.snapshot_ref or "")

    assert ContextReplayGate().evaluate(snapshot).passed is True
    assert replayed.envelope_id == envelope.envelope_id
    assert snapshot.assembled_prompt_ref.startswith("artifact://assembled-context/")
    assert snapshot.metadata["payload_saved"] is False


def test_context_replay_rejects_checksum_mismatch() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble(
        {
            "graph_identity": _graph_envelope().graph_identity,
            "phase": "VERIFY",
            "worker_id": "context-worker",
            "worker_type": "function",
        }
    )
    assembler.snapshot_store.envelopes[envelope.envelope_id] = replace(
        envelope,
        token_estimate=envelope.token_estimate + 1,
        checksum=None,
    )

    with pytest.raises(HarnessValidationError):
        assembler.snapshot_store.replay(envelope.snapshot_ref or "")


def test_graph_context_snapshot_store_binds_identity_and_never_downgrades() -> None:
    store = ContextSnapshotStore()
    envelope, snapshot = store.save_bound(_graph_envelope())

    assert envelope.is_graph_only is True
    assert snapshot.is_graph_only is True
    assert snapshot.envelope_checksum == envelope.checksum
    assert store.replay(snapshot.snapshot_id) == envelope

def test_graph_context_snapshot_store_rejects_cross_graph_replay() -> None:
    store = ContextSnapshotStore()
    envelope, snapshot = store.save_bound(_graph_envelope())
    other = _graph_envelope(graph_id="other.context.graph").bind_snapshot_ref(
        snapshot.snapshot_id
    )
    store.envelopes[envelope.envelope_id] = other

    with pytest.raises(HarnessValidationError) as error:
        store.replay(snapshot.snapshot_id)

    assert error.value.code == "context_snapshot_replay_identity_mismatch"


def test_context_snapshot_reader_rejects_legacy_schema() -> None:
    store = ContextSnapshotStore()
    _, snapshot = store.save_bound(_graph_envelope())
    payload = snapshot.to_dict()
    payload.pop("schema_version")
    with pytest.raises(HarnessValidationError) as error:
        ContextSnapshot.from_dict(payload)

    assert error.value.code == "context_snapshot_schema_unsupported"
