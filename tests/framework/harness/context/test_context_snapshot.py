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
    ContextSnapshotReplayReader,
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
    envelope = assembler.assemble({"run_id": "run-replay", "step_id": "verify"})
    snapshot = assembler.snapshot_store.load(envelope.snapshot_ref or "")
    replayed = assembler.snapshot_store.replay(envelope.snapshot_ref or "")

    assert ContextReplayGate().evaluate(snapshot).passed is True
    assert replayed.envelope_id == envelope.envelope_id
    assert snapshot.assembled_prompt_ref.startswith("artifact://assembled-context/")
    assert snapshot.metadata["payload_saved"] is False


def test_context_replay_rejects_checksum_mismatch() -> None:
    assembler = ContextAssembler()
    envelope = assembler.assemble({"run_id": "run-replay", "step_id": "verify"})
    assembler.snapshot_store.envelopes[envelope.envelope_id] = replace(envelope, token_estimate=envelope.token_estimate + 1)

    with pytest.raises(HarnessValidationError):
        assembler.snapshot_store.replay(envelope.snapshot_ref or "")


def test_graph_context_snapshot_store_binds_identity_and_never_downgrades() -> None:
    store = ContextSnapshotStore()
    envelope, snapshot = store.save_bound(_graph_envelope())

    assert envelope.is_graph_only is True
    assert snapshot.is_graph_only is True
    assert snapshot.envelope_checksum == envelope.checksum
    assert store.replay(snapshot.snapshot_id) == envelope

    with pytest.raises(HarnessValidationError) as error:
        ContextSnapshotReplayReader().replay_snapshot(snapshot)
    assert error.value.code == "context_snapshot_v2_replay_unavailable"


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


@pytest.mark.parametrize("forged_schema", ("legacy", "graph"))
def test_context_snapshot_store_rejects_schema_downgrade_replay(
    forged_schema: str,
) -> None:
    store = ContextSnapshotStore()

    if forged_schema == "legacy":
        envelope, snapshot = store.save_bound(_graph_envelope())
        store.snapshots[snapshot.snapshot_id] = replace(
            snapshot,
            schema_version=None,
            graph_identity=None,
            task_execution_identity=None,
            envelope_checksum=None,
        )
    else:
        legacy_envelope = ContextEnvelope(
            envelope_id="context://legacy/snapshot",
            run_id="run-legacy-snapshot",
            workflow_id="legacy.workflow",
            step_id="legacy-stage",
            phase="EXECUTE",
            worker_id="legacy-worker",
            worker_type="task_plan",
        )
        envelope, snapshot = store.save_bound(legacy_envelope)
        graph_envelope = replace(
            _graph_envelope(),
            envelope_id=envelope.envelope_id,
            checksum=None,
        ).bind_snapshot_ref(snapshot.snapshot_id)
        store.snapshots[snapshot.snapshot_id] = ContextSnapshot.for_graph_envelope(
            snapshot_id=snapshot.snapshot_id,
            envelope=graph_envelope,
            refs=("artifact://legacy-context",),
            segment_refs=(),
            assembled_prompt_ref=None,
            cache_key="context-cache://graph-forgery",
        )

    with pytest.raises(HarnessValidationError) as error:
        store.replay(snapshot.snapshot_id)

    assert error.value.code == "context_snapshot_replay_identity_mismatch"
