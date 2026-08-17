from __future__ import annotations

from copy import deepcopy

import pytest

from framework.events.canonical import checksum_for
from framework.harness import (
    CONTEXT_ENVELOPE_SCHEMA_V2,
    CONTEXT_SNAPSHOT_SCHEMA_V2,
    ContextBudget,
    ContextCachePolicy,
    ContextCacheScope,
    ContextEnvelope,
    ContextGraphIdentity,
    ContextSegment,
    ContextSegmentType,
    ContextSnapshot,
    ContextTaskExecutionIdentity,
    HarnessValidationError,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.shared.json import stable_json_dumps


def _graph_identity(*, graph_id: str = "research.graph") -> ContextGraphIdentity:
    values = {
        "schema_version": "newsroom.harness-task-plan-stage-identity/v2",
        "run_id": "run-graph-context",
        "graph_schema_version": GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        "compiler_version": HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        "condition_policy_version": HARNESS_CONDITION_POLICY_VERSION,
        "graph_id": graph_id,
        "graph_version": "2",
        "graph_checksum": "sha256:" + "1" * 64,
        "stage_id": "dynamic_stage",
        "stage_binding_checksum": "sha256:" + "2" * 64,
        "graph_ref": f"{graph_id}@2",
    }
    return ContextGraphIdentity(
        run_id=values["run_id"],
        graph_id=values["graph_id"],
        graph_version=values["graph_version"],
        graph_ref=values["graph_ref"],
        graph_schema_version=values["graph_schema_version"],
        compiler_version=values["compiler_version"],
        condition_policy_version=values["condition_policy_version"],
        graph_checksum=values["graph_checksum"],
        stage_id=values["stage_id"],
        stage_binding_checksum=values["stage_binding_checksum"],
        stage_identity_schema=values["schema_version"],
        stage_identity_checksum=checksum_for(values),
    )


def _task_identity() -> ContextTaskExecutionIdentity:
    return ContextTaskExecutionIdentity(
        plan_id="plan-graph-context",
        plan_version=2,
        plan_checksum="sha256:" + "3" * 64,
        task_id="analyze",
        task_definition_checksum="sha256:" + "4" * 64,
        task_instance_id="analyze-attempt-1",
        attempt=1,
    )


def test_context_envelope_is_serializable_with_segments_budget_and_refs() -> None:
    budget = ContextBudget.safe_default()
    segment = ContextSegment(
        segment_id="global-policy",
        segment_type=ContextSegmentType.GLOBAL_POLICY,
        content_ref="policy://harness/global",
        summary="Harness controls workflow routing and tool authorization.",
        token_estimate=64,
        provenance_refs=("policy://harness/global",),
        cache_scope=ContextCacheScope.STABLE_PREFIX,
    )
    envelope = ContextEnvelope(
        envelope_id="context://run/step",
        run_id="run-1",
        workflow_id="workflow-1",
        step_id="collect",
        phase="plan",
        worker_id="llm.collect",
        worker_type="llm",
        segments=(segment,),
        budget=budget,
        artifact_refs=("artifact://accepted-report",),
        token_estimate=64,
    )

    payload = envelope.to_dict()

    assert payload["segments"][0]["segment_type"] == "global_policy"
    assert payload["budget"]["max_input_tokens"] == budget.max_input_tokens
    assert set(payload) == {
        "artifact_refs",
        "budget",
        "cache_policy",
        "dynamic_tail",
        "envelope_id",
        "evidence_refs",
        "memory_refs",
        "metadata",
        "phase",
        "run_id",
        "segments",
        "snapshot_ref",
        "stable_prefix",
        "step_id",
        "token_estimate",
        "worker_id",
        "worker_type",
        "workflow_id",
    }
    assert "schema_version" not in payload
    assert stable_json_dumps(payload)


def test_context_envelope_and_snapshot_round_trip_from_typed_payloads() -> None:
    envelope = ContextEnvelope(
        envelope_id="context://run-persist/step",
        run_id="run-persist",
        workflow_id="workflow-persist",
        step_id="verify",
        phase="verify",
        worker_id="worker-persist",
        worker_type="script",
        segments=(
            ContextSegment(
                segment_id="current-task",
                segment_type=ContextSegmentType.CURRENT_TASK,
                content_ref="task://verify",
                summary="Verify the persisted result.",
                token_estimate=12,
                provenance_refs=("source://paper",),
            ),
        ),
        budget=ContextBudget.safe_default(),
        cache_policy=ContextCachePolicy(
            cache_enabled=True,
            stable_prefix_segments=("global-policy",),
            dynamic_tail_segments=("current-task",),
            cache_key="sha256:context-cache",
        ),
        snapshot_ref="context-snapshot://run-persist",
        stable_prefix={"policy": "bounded"},
        dynamic_tail={"task": "verify"},
        artifact_refs=("artifact://run-persist/report",),
        memory_refs=("memory://run-persist",),
        evidence_refs=("evidence://run-persist",),
        token_estimate=12,
    )
    snapshot = ContextSnapshot(
        snapshot_id="context-snapshot://run-persist",
        envelope_id=envelope.envelope_id,
        run_id="run-persist",
        step_id="verify",
        phase="verify",
        segment_refs=("current-task",),
        assembled_prompt_ref="artifact://run-persist/prompt",
        refs=("source://paper",),
        token_estimate=12,
        cache_key="sha256:context-cache",
        checksum="sha256:context-snapshot",
    )

    assert ContextEnvelope.from_dict(envelope.to_dict()).to_dict() == envelope.to_dict()
    assert ContextSnapshot.from_dict(snapshot.to_dict()).to_dict() == snapshot.to_dict()


def test_graph_context_envelope_uses_strict_v2_identity_and_checksum() -> None:
    envelope = ContextEnvelope.for_graph(
        envelope_id="context://run-graph-context/dynamic-stage/analyze",
        graph_identity=_graph_identity(),
        task_execution_identity=_task_identity(),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
        stable_prefix={"policy": "bounded"},
        dynamic_tail={"input_refs": ["document"]},
        artifact_refs=("artifact://accepted-input",),
        token_estimate=12,
    )

    payload = envelope.to_dict()

    assert payload["schema_version"] == CONTEXT_ENVELOPE_SCHEMA_V2
    assert set(payload) == {
        "artifact_refs",
        "budget",
        "cache_policy",
        "checksum",
        "dynamic_tail",
        "envelope_id",
        "evidence_refs",
        "graph_identity",
        "memory_refs",
        "metadata",
        "phase",
        "schema_version",
        "segments",
        "snapshot_ref",
        "stable_prefix",
        "task_execution_identity",
        "token_estimate",
        "worker_id",
        "worker_type",
    }
    assert not {"workflow_id", "workflow_ref", "step_id"}.intersection(payload)
    assert ContextEnvelope.from_dict(payload) == envelope

    policy = ContextCachePolicy(
        cache_enabled=True,
        stable_prefix_segments=("policy",),
        dynamic_tail_segments=(),
        cache_key="context-cache:graph",
    )
    cached = envelope.bind_cache_policy(policy)
    snapshotted = cached.bind_snapshot_ref("context-snapshot://graph-context")
    assert cached.checksum != envelope.checksum
    assert snapshotted.checksum != cached.checksum


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    (
        (lambda value: value.update({"workflow_id": None}), "context_schema_fields_invalid"),
        (
            lambda value: value.update({"schema_version": "newsroom.context-envelope/v99"}),
            "context_envelope_schema_unsupported",
        ),
        (
            lambda value: value["graph_identity"].update(
                {"compiler_version": "newsroom.harness-graph-compiler/v1"}
            ),
            "context_graph_identity_schema_mismatch",
        ),
        (
            lambda value: value.update({"checksum": "sha256:" + "0" * 64}),
            "context_envelope_checksum_mismatch",
        ),
    ),
)
def test_graph_context_envelope_rejects_alias_schema_and_checksum_tampering(
    mutation,
    error_code: str,
) -> None:
    payload = ContextEnvelope.for_graph(
        envelope_id="context://run-graph-context/dynamic-stage/analyze",
        graph_identity=_graph_identity(),
        task_execution_identity=_task_identity(),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
    ).to_dict()
    tampered = deepcopy(payload)
    mutation(tampered)

    with pytest.raises(HarnessValidationError) as error:
        ContextEnvelope.from_dict(tampered)

    assert error.value.code == error_code


def test_graph_context_snapshot_round_trip_remains_v2_only() -> None:
    envelope = ContextEnvelope.for_graph(
        envelope_id="context://run-graph-context/dynamic-stage/analyze",
        graph_identity=_graph_identity(),
        task_execution_identity=_task_identity(),
        phase="EXECUTE",
        worker_id="task-plan-worker",
        worker_type="task_plan",
    ).bind_snapshot_ref("context-snapshot://graph-context")
    snapshot = ContextSnapshot.for_graph_envelope(
        snapshot_id="context-snapshot://graph-context",
        envelope=envelope,
        refs=("context://graph-context",),
        segment_refs=(),
        assembled_prompt_ref="artifact://assembled-context/graph-context",
        cache_key="context:graph-context",
        metadata={"payload_saved": False},
    )
    payload = snapshot.to_dict()

    assert payload["schema_version"] == CONTEXT_SNAPSHOT_SCHEMA_V2
    assert payload["phase"] == "EXECUTE"
    assert not {"workflow_id", "workflow_ref", "run_id", "step_id"}.intersection(payload)
    assert ContextSnapshot.from_dict(payload) == snapshot

    for mutation, error_code in (
        (
            lambda value: value.update({"workflow_id": None}),
            "context_schema_fields_invalid",
        ),
        (
            lambda value: value.update({"envelope_checksum": "sha256:" + "0" * 64}),
            "context_snapshot_checksum_mismatch",
        ),
        (
            lambda value: value["graph_identity"].update(
                {"graph_version": "3"}
            ),
            "context_graph_identity_mismatch",
        ),
    ):
        tampered = deepcopy(payload)
        mutation(tampered)
        with pytest.raises(HarnessValidationError) as error:
            ContextSnapshot.from_dict(tampered)
        assert error.value.code == error_code
