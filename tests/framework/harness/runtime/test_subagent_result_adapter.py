from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from framework.events.canonical import checksum_for, thaw_canonical_json
from framework.harness import (
    FakeSubAgentWorker,
    HarnessValidationError,
    HarnessWorkerResult,
    SubAgentContextBuilder,
    SubAgentInvocation,
    SubAgentRuntime,
    SubAgentSpec,
    SubAgentStatus,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.policy import (
    HarnessBudget,
    HarnessBudgetSnapshot,
)
from framework.harness.context.models import ContextEnvelope
from framework.harness.runtime import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    HarnessGraphResultRuntime,
    PersistenceMode,
)
from framework.harness.runtime.subagent_result_adapter import (
    HarnessSubAgentActivityRuntime,
    HarnessSubAgentResultAdapter,
    VerifiedSubAgentMaterializedBundle,
    verify_subagent_materialized_bundle,
)
from framework.harness.subagents.models import SubAgentHandoff
from framework.harness.subagents.transcript import FakeSubAgentTranscriptStore
from framework.shared.json import stable_json_dumps
from tests.framework.harness.runtime.test_graph_result_runtime import (
    NOW,
    TENANT_ID,
    TENANT_SCOPE_REF,
    _dispatched,
)
from tests.framework.harness.runtime.test_materializer import (
    RecordingArtifactPort,
    RecordingAttempts,
    RecordingCache,
    RecordingCatalog,
    RecordingQuota,
    _materializer,
)


def _spec() -> SubAgentSpec:
    return SubAgentSpec(
        subagent_id="critic",
        role="critic",
        purpose="Review a candidate.",
        input_schema={
            "required": ["input_refs"],
            "properties": {"input_refs": {"type": "array"}},
        },
        output_schema={
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        allowed_tools=("search.read",),
        allowed_memory_namespaces=("research.public",),
        budget={"max_turns": 2, "max_tool_calls": 1, "max_memory_ops": 1},
    )


def _invocation(fixture, spec: SubAgentSpec) -> SubAgentInvocation:
    budget = HarnessBudgetSnapshot.from_budget(HarnessBudget.safe_default())
    child_run_id = f"{fixture.activity.run_id}:{fixture.activity.node_id}:task-1"
    context = SubAgentContextBuilder().build(
        parent_run_id=fixture.activity.run_id,
        child_run_id=child_run_id,
        spec=spec,
        context_pack=ContextEnvelope(
            envelope_id="context://subagent-result",
            token_estimate=10,
        ),
        input_refs=("artifact://research/input-1",),
        memory_context_refs=("memory://research/context-1",),
        budget_snapshot=budget,
    )
    return SubAgentInvocation(
        invocation_id=f"invocation://{child_run_id}",
        parent_run_id=fixture.activity.run_id,
        child_run_id=child_run_id,
        workflow_id=fixture.graph.workflow_id,
        step_id=fixture.activity.node_id,
        task_id="task-1",
        task_instance_id="task-instance-1",
        attempt=1,
        observed_at=NOW,
        subagent_spec=spec,
        input_refs=("artifact://research/input-1",),
        context_envelope=context,
        budget_snapshot=budget,
        metadata={"input_refs": ["artifact://research/input-1"]},
    )


def _stack(fixture, worker_result: HarnessWorkerResult):
    spec = _spec()
    store = FakeSubAgentTranscriptStore()
    runtime = SubAgentRuntime(
        workers={spec.subagent_id: FakeSubAgentWorker((worker_result,))},
        transcript_store=store,
    )
    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    catalog = RecordingCatalog()
    materializer = _materializer(
        artifact=artifact,
        attempts=attempts,
        cache=RecordingCache(),
        catalog=catalog,
        quota=RecordingQuota(),
    )
    graph_runtime = HarnessGraphControlPlaneRuntime(fixture.port)
    adapter = HarnessSubAgentResultAdapter(
        materializer=materializer,
        graph_result_runtime=HarnessGraphResultRuntime(graph_runtime),
        transcript_store=store,
        clock=lambda: NOW,
    )
    return (
        HarnessSubAgentActivityRuntime(runtime=runtime, adapter=adapter),
        adapter,
        runtime,
        store,
        artifact,
        attempts,
        catalog,
        _invocation(fixture, spec),
    )


def _execute(activity_runtime, fixture, invocation, **kwargs):
    return activity_runtime.execute_and_accept(
        invocation=invocation,
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=1),
        **kwargs,
    )


def _stored_bundle(artifact, result) -> dict:
    ref = result.outcome.materialization.envelope.materialized_refs[0].ref
    stored = artifact.read_artifact(ref)["payload"]
    return stored["value"]


def _lineage(result, fixture) -> dict:
    node = next(
        item
        for item in result.graph_state.node_instances
        if item.instance_id == fixture.activity.node_instance_id
    )
    return thaw_canonical_json(node.output_refs["activity_result_lineage"])


def test_verified_bundle_materializes_all_documents_and_projects_only_lineage() -> None:
    fixture = _dispatched("run-subagent-materialized")
    large_result = "x" * (48 * 1024)
    (
        activity_runtime,
        _adapter,
        _runtime,
        _store,
        artifact,
        _attempts,
        catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(
            status="succeeded",
            output={"result": large_result},
            artifacts=("artifact://research/analysis-1",),
        ),
    )
    handoff = SubAgentHandoff(
        handoff_id="handoff-1",
        from_subagent_id="critic",
        to_subagent_id="aggregator",
        parent_run_id=fixture.activity.run_id,
        payload={"claim": "bounded"},
        payload_schema={
            "required": ["claim"],
            "properties": {"claim": {"type": "string"}},
        },
        input_refs=("artifact://research/input-1",),
        artifact_refs=("artifact://research/analysis-1",),
        created_at=NOW,
    )

    result = _execute(
        activity_runtime,
        fixture,
        invocation,
        handoff=handoff,
    )
    envelope = result.outcome.materialization.envelope
    stored = _stored_bundle(artifact, result)
    verified = verify_subagent_materialized_bundle(
        stored,
        expected_binding=envelope.binding,
    )
    lineage = _lineage(result, fixture)

    assert envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert verified.output.output["result"] == large_result
    assert verified.context.input_refs == invocation.input_refs
    assert verified.transcript.output_checksum == verified.output.output_checksum
    assert verified.handoff == handoff
    assert len(catalog.requests) == 1
    projection = lineage["inline_projection"]
    assert projection["subagent_status"] == "succeeded"
    assert projection["transcript_checksum"] == verified.transcript.transcript_checksum
    assert projection["handoff"]["handoff_id"] == "handoff-1"
    assert projection["result_summary"] == "x" * 2048
    graph_payload = stable_json_dumps(result.graph_state.to_dict())
    assert "x" * 2049 not in graph_payload
    assert "transcript_body" not in graph_payload
    assert "context_evidence" not in graph_payload


def test_halted_attempt_is_materialized_with_failed_gate_evidence() -> None:
    fixture = _dispatched("run-subagent-halted")
    (
        activity_runtime,
        _adapter,
        _runtime,
        _store,
        artifact,
        _attempts,
        _catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(
            status="succeeded",
            output={"result": "ok", "requested_tools": ["admin.write"]},
        ),
    )

    result = _execute(activity_runtime, fixture, invocation)
    stored = verify_subagent_materialized_bundle(
        _stored_bundle(artifact, result),
        expected_binding=result.outcome.materialization.envelope.binding,
    )
    projection = _lineage(result, fixture)["inline_projection"]

    assert result.outcome.result.status is SubAgentStatus.HALTED
    assert result.outcome.materialization.envelope.status.value == "halted"
    assert projection["failed_gate_count"] == 1
    assert any(gate["passed"] is False for gate in stored.transcript.gate_results)


def test_restart_reuses_transcript_and_attempt_without_invoking_worker() -> None:
    fixture = _dispatched("run-subagent-restart")
    (
        _activity_runtime,
        adapter,
        runtime,
        store,
        artifact,
        attempts,
        _catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(status="succeeded", output={"result": "ok"}),
    )
    binding = adapter.binding_for_activity(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        invocation=invocation,
    )
    first_result = runtime.invoke(invocation)
    first = adapter.materialize(
        first_result,
        invocation=invocation,
        binding=binding,
        created_at=NOW + timedelta(minutes=1),
    )

    class ExplodingWorker:
        calls = 0

        def execute(self, _task):
            self.calls += 1
            raise AssertionError("recovery must not invoke a worker")

    worker = ExplodingWorker()
    restarted_runtime = SubAgentRuntime(
        workers={invocation.subagent_spec.subagent_id: worker},
        transcript_store=store,
    )
    restarted_adapter = HarnessSubAgentResultAdapter(
        materializer=_materializer(
            artifact=artifact,
            attempts=attempts,
            cache=RecordingCache(),
            catalog=RecordingCatalog(),
            quota=RecordingQuota(),
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(fixture.port)
        ),
        transcript_store=store,
        clock=lambda: NOW,
    )
    restarted = HarnessSubAgentActivityRuntime(
        runtime=restarted_runtime,
        adapter=restarted_adapter,
    ).recover_and_accept(
        invocation=invocation,
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert restarted.outcome.recovered is True
    assert restarted.outcome.materialization.envelope == first.materialization.envelope
    assert worker.calls == 0
    assert artifact.write_count == 1
    assert attempts.put_count == 1


def test_conflicting_same_attempt_fails_without_second_artifact_or_graph_commit() -> None:
    fixture = _dispatched("run-subagent-conflict")
    (
        _activity_runtime,
        adapter,
        runtime,
        _store,
        artifact,
        _attempts,
        _catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(status="succeeded", output={"result": "first"}),
    )
    binding = adapter.binding_for_activity(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        invocation=invocation,
    )
    result = runtime.invoke(invocation)
    adapter.materialize(
        result,
        invocation=invocation,
        binding=binding,
        created_at=NOW + timedelta(minutes=1),
    )
    conflicting_handoff = SubAgentHandoff(
        handoff_id="handoff-conflict",
        from_subagent_id="critic",
        to_subagent_id="aggregator",
        parent_run_id=fixture.activity.run_id,
        payload={"claim": "different"},
        payload_schema={"required": ["claim"]},
        created_at=NOW,
    )

    with pytest.raises(GraphArtifactResultError) as captured:
        adapter.materialize(
            result,
            invocation=invocation,
            binding=binding,
            handoff=conflicting_handoff,
            created_at=NOW + timedelta(minutes=2),
        )

    assert captured.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT
    assert artifact.write_count == 1
    assert fixture.port.recover_graph(fixture.activity.run_id).activity_result_commits == ()


@pytest.mark.parametrize(
    ("tenant_id", "tenant_scope_ref", "parent_run_id", "expected_code"),
    (
        (
            "tenant-other",
            TENANT_SCOPE_REF,
            "run-subagent-cross-scope",
            "graph_result_lineage_scope_mismatch",
        ),
        (
            TENANT_ID,
            checksum_for("tenant-other"),
            "run-subagent-cross-scope",
            "graph_result_lineage_scope_mismatch",
        ),
        (
            TENANT_ID,
            TENANT_SCOPE_REF,
            "run-other",
            "subagent_result_scope_mismatch",
        ),
    ),
)
def test_cross_tenant_or_run_is_rejected_before_materialization(
    tenant_id,
    tenant_scope_ref,
    parent_run_id,
    expected_code,
) -> None:
    fixture = _dispatched("run-subagent-cross-scope")
    (
        _activity_runtime,
        adapter,
        _runtime,
        _store,
        artifact,
        attempts,
        _catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(status="succeeded", output={"result": "ok"}),
    )
    invocation = replace(
        invocation,
        parent_run_id=parent_run_id,
        child_run_id=f"{parent_run_id}:analyze:task-1",
        invocation_id=f"invocation://{parent_run_id}:analyze:task-1",
    )

    with pytest.raises(HarnessValidationError) as captured:
        adapter.binding_for_activity(
            activity=fixture.activity,
            graph=fixture.graph,
            tenant_id=tenant_id,
            tenant_scope_ref=tenant_scope_ref,
            run_spec_checksum=fixture.run_spec_checksum,
            invocation=invocation,
        )

    assert captured.value.code == expected_code
    assert artifact.write_count == 0
    assert attempts.put_count == 0


def test_bundle_parser_rejects_scope_tampering() -> None:
    fixture = _dispatched("run-subagent-tamper")
    (
        _activity_runtime,
        adapter,
        runtime,
        _store,
        _artifact,
        _attempts,
        _catalog,
        invocation,
    ) = _stack(
        fixture,
        HarnessWorkerResult(status="succeeded", output={"result": "ok"}),
    )
    binding = adapter.binding_for_activity(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        invocation=invocation,
    )
    request, bundle = adapter.request_from_verified_result(
        runtime.invoke(invocation),
        invocation=invocation,
        binding=binding,
        created_at=NOW,
    )
    payload = bundle.to_dict()
    payload["graph_binding"]["run_id"] = "run-other"
    payload["bundle_checksum"] = checksum_for(
        {key: value for key, value in payload.items() if key != "bundle_checksum"}
    )

    with pytest.raises(HarnessValidationError) as captured:
        VerifiedSubAgentMaterializedBundle.from_dict(payload)

    assert captured.value.code == "subagent_result_scope_mismatch"
    assert request.binding == binding
