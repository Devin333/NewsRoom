from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend.research.application.graph_result_committer import (
    ResearchTaskPlanResultMaterializer,
)
from backend.research.graphs import RESEARCH_DYNAMIC_STAGE_ID
from framework.events.canonical import checksum_for
from framework.harness import (
    ContextEnvelope,
    HarnessBudget,
    HarnessBudgetSnapshot,
    HarnessValidationError,
    ResolvedSubAgentTaskAdapter,
    SubAgentRuntime,
    TaskLifecycle,
    TaskPlanResultVerificationRequest,
    task_plan_context_identities,
)
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.control_plane.harness import InMemoryHarnessEventPort
from framework.harness.runtime import (
    GraphArtifactPersistenceConfig,
    GraphArtifactRolloutMode,
    HarnessGraphResultRuntime,
    HarnessSubAgentResultAdapter,
    SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V3,
    SUBAGENT_NODE_RESULT_SCHEMA_V3,
    verify_subagent_materialized_bundle,
)
from framework.harness.graph import HarnessWorkerType
from framework.harness.subagents.transcript import SUBAGENT_RECEIPT_SCHEMA_V3
from framework.shared.json import stable_json_dumps
from tests.framework.harness.runtime.test_materializer import (
    RecordingArtifactPort,
    RecordingAttempts,
    RecordingCache,
    RecordingCatalog,
    RecordingQuota,
    _materializer,
)
from tests.framework.harness.task_plan.test_subagent_result_lineage import (
    _execution_identity,
    _graph_only_plan_for_fixture,
    _fixture as _task_plan_fixture,
    _worker_result_from_child,
)


def test_graph_only_dynamic_child_materialization_uses_versioned_identity_and_artifact_owner(
    tmp_path: Path,
) -> None:
    task_plan = _task_plan_fixture(tmp_path)
    plan, instance = _graph_only_plan_for_fixture(task_plan)
    policy = replace(task_plan["policy"], stage_id=RESEARCH_DYNAMIC_STAGE_ID)
    resolved = plan.tasks[0]
    binding = task_plan["registry"].resolve(
        resolved.task.worker_capability,
        policy,
    )
    execution_identity = _execution_identity(plan, instance)
    graph_identity, task_identity = task_plan_context_identities(
        plan,
        instance,
        execution_identity=execution_identity,
    )
    context_pack = ContextEnvelope.for_graph(
        envelope_id="research-graph-materialization-context",
        graph_identity=graph_identity,
        task_execution_identity=task_identity,
        phase="EXECUTE",
        worker_id="research-task-plan",
        worker_type=HarnessWorkerType.TASK_PLAN.value,
        dynamic_tail={"input_refs": ["document"]},
    )
    invocation = task_plan["adapter"].build_invocation(
        plan=plan,
        resolved_task=resolved,
        binding=binding,
        instance=instance,
        context_pack=context_pack,
        budget_snapshot=task_plan["budget"],
        execution_identity=execution_identity,
    )
    child = task_plan["adapter"].invoke(
        plan=plan,
        resolved_task=resolved,
        binding=binding,
        instance=instance,
        context_pack=context_pack,
        budget_snapshot=task_plan["budget"],
        execution_identity=execution_identity,
    )
    worker_result = _worker_result_from_child(child)
    assert task_plan["worker"].calls == 1

    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    config = GraphArtifactPersistenceConfig(mode=GraphArtifactRolloutMode.ENFORCE)
    common_adapter = HarnessSubAgentResultAdapter(
        materializer=_materializer(
            artifact=artifact,
            attempts=attempts,
            cache=RecordingCache(),
            catalog=RecordingCatalog(),
            quota=RecordingQuota(),
            config=config,
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(InMemoryHarnessEventPort())
        ),
        transcript_store=task_plan["transcript_store"],
    )
    tenant_id = "tenant-research-graph-only"
    materializer = ResearchTaskPlanResultMaterializer(
        verifier=task_plan["verifier"],
        adapter=common_adapter,
        config=config,
        tenant_id=tenant_id,
        tenant_scope_ref=checksum_for(tenant_id),
        invocation_factory=lambda active_plan, task, active, active_execution: invocation,
    )

    record = materializer.verify(
        worker_result,
        task=resolved,
        request=TaskPlanResultVerificationRequest(
            plan=plan,
            task=resolved,
            instance=instance,
            worker_result=worker_result,
            execution_identity=execution_identity,
        ),
    )

    assert record.is_graph_only is True
    assert "workflow_id" not in record.to_dict()
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    envelope = next(iter(attempts.envelopes.values()))
    assert envelope.binding.graph_id == plan.graph_id
    assert envelope.binding.graph_version == plan.graph_ref
    assert envelope.output_schema_ref == SUBAGENT_NODE_RESULT_SCHEMA_V3
    assert envelope.provenance.producer_revision == "harness-subagent-result-adapter@3"
    assert envelope.materialized_refs[0].ref in record.output_refs

    stored = artifact.read_artifact(envelope.materialized_refs[0].ref)["payload"]["value"]
    bundle = verify_subagent_materialized_bundle(
        stored,
        expected_binding=envelope.binding,
    )
    assert bundle.bundle_schema == SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V3
    assert bundle.identity == invocation.attempt_identity
    assert bundle.receipt.schema_version == SUBAGENT_RECEIPT_SCHEMA_V3
    assert "workflow_id" not in stable_json_dumps(stored)

    mixed_schema = dict(stored)
    mixed_schema["bundle_schema"] = "newsroom.subagent-materialized-bundle@2"
    mixed_schema["bundle_checksum"] = checksum_for(
        {
            key: value
            for key, value in mixed_schema.items()
            if key != "bundle_checksum"
        }
    )
    with pytest.raises(HarnessValidationError) as mixed_error:
        verify_subagent_materialized_bundle(mixed_schema)
    assert mixed_error.value.code == "subagent_result_schema_unsupported"

    assert artifact.write_count == 1
    assert attempts.put_count == 1
