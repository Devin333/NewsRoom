from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from business.research.application.graph_result_committer import (
    ResearchTaskPlanResultMaterializer,
)
from business.research.graphs import RESEARCH_DYNAMIC_STAGE_ID
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
    SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V1,
    SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V2,
    SUBAGENT_NODE_RESULT_SCHEMA_V2,
    verify_subagent_materialized_bundle,
)
from framework.harness.graph import HarnessWorkerType
from framework.harness.subagents.transcript import SUBAGENT_RECEIPT_SCHEMA_V2
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
    _graph_only_plan_for_fixture,
    _fixture as _task_plan_fixture,
    _worker_result_from_child,
)


def test_dynamic_child_materialization_is_independent_and_worker_free_on_recovery(
    tmp_path: Path,
) -> None:
    task_plan = _task_plan_fixture(tmp_path)
    plan = task_plan["plan"]
    policy = task_plan["policy"]
    resolved = task_plan["resolved"]
    instance = task_plan["instance"]
    binding = task_plan["registry"].resolve(
        resolved.task.worker_capability,
        policy,
    )
    worker_result = task_plan["invoke"]()
    assert task_plan["worker"].calls == 1

    context_pack = ContextEnvelope(
        envelope_id="lineage-context",
        run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        step_id=plan.stage_id,
        phase="EXECUTE",
        worker_id="lineage-task-plan",
        worker_type=HarnessWorkerType.TASK_PLAN.value,
        dynamic_tail={"input_refs": ["document"]},
    )
    budget = HarnessBudgetSnapshot.from_budget(HarnessBudget.safe_default())
    invocation_builder = ResolvedSubAgentTaskAdapter(
        SubAgentRuntime(
            workers={},
            transcript_store=task_plan["transcript_store"],
        )
    )
    invocation = invocation_builder.build_invocation(
        plan=plan,
        resolved_task=resolved,
        binding=binding,
        instance=instance,
        context_pack=context_pack,
        budget_snapshot=budget,
    )

    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    catalog = RecordingCatalog()
    config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.ENFORCE
    )
    event_port = InMemoryHarnessEventPort()
    common_adapter = HarnessSubAgentResultAdapter(
        materializer=_materializer(
            artifact=artifact,
            attempts=attempts,
            cache=RecordingCache(),
            catalog=catalog,
            quota=RecordingQuota(),
            config=config,
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(event_port)
        ),
        transcript_store=task_plan["transcript_store"],
    )
    tenant_id = "tenant-research-dynamic"
    verifier = ResearchTaskPlanResultMaterializer(
        verifier=task_plan["verifier"],
        adapter=common_adapter,
        config=config,
        tenant_id=tenant_id,
        tenant_scope_ref=checksum_for(tenant_id),
        invocation_factory=lambda active_plan, task, active: invocation,
        legacy_graph_id="research.paper_analysis.dynamic.graph",
        legacy_graph_version="research.paper_analysis.dynamic.graph@1",
    )

    first = verifier.verify(
        worker_result,
        task=resolved,
        request=TaskPlanResultVerificationRequest(
            plan=plan,
            task=resolved,
            instance=instance,
            worker_result=worker_result,
        ),
    )
    assert first.status is TaskLifecycle.SUCCEEDED
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    envelope = next(iter(attempts.envelopes.values()))
    assert envelope.binding.node_id == plan.stage_id
    assert envelope.binding.attempt_id.startswith("subagent_")
    assert envelope.binding.attempt_id != instance.task_instance_id
    assert envelope.materialized_refs[0].ref in first.output_refs

    recovered_result = task_plan["recover"](binding, instance)
    assert recovered_result is not None
    second = verifier.verify(
        recovered_result,
        task=resolved,
        request=TaskPlanResultVerificationRequest(
            plan=plan,
            task=resolved,
            instance=instance,
            worker_result=recovered_result,
        ),
    )

    assert second.status is TaskLifecycle.SUCCEEDED
    assert task_plan["worker"].calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    assert next(iter(attempts.envelopes.values())) == envelope

    read_only_config = GraphArtifactPersistenceConfig(
        mode=GraphArtifactRolloutMode.READ_ONLY
    )
    read_only_adapter = HarnessSubAgentResultAdapter(
        materializer=_materializer(
            artifact=artifact,
            attempts=attempts,
            cache=RecordingCache(),
            catalog=catalog,
            quota=RecordingQuota(),
            config=read_only_config,
        ),
        graph_result_runtime=HarnessGraphResultRuntime(
            HarnessGraphControlPlaneRuntime(event_port)
        ),
        transcript_store=task_plan["transcript_store"],
    )
    read_only_verifier = ResearchTaskPlanResultMaterializer(
        verifier=task_plan["verifier"],
        adapter=read_only_adapter,
        config=read_only_config,
        tenant_id=tenant_id,
        tenant_scope_ref=checksum_for(tenant_id),
        invocation_factory=lambda active_plan, task, active: invocation,
        legacy_graph_id="research.paper_analysis.dynamic.graph",
        legacy_graph_version="research.paper_analysis.dynamic.graph@1",
    )

    read_only_result = read_only_verifier.verify(
        recovered_result,
        task=resolved,
        request=TaskPlanResultVerificationRequest(
            plan=plan,
            task=resolved,
            instance=instance,
            worker_result=recovered_result,
        ),
    )

    assert read_only_result.status is TaskLifecycle.SUCCEEDED
    assert task_plan["worker"].calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1


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
    context_pack = replace(
        task_plan["context_pack"],
        workflow_id=None,
        step_id=plan.stage_id,
    )
    invocation = task_plan["adapter"].build_invocation(
        plan=plan,
        resolved_task=resolved,
        binding=binding,
        instance=instance,
        context_pack=context_pack,
        budget_snapshot=task_plan["budget"],
    )
    child = task_plan["adapter"].invoke(
        plan=plan,
        resolved_task=resolved,
        binding=binding,
        instance=instance,
        context_pack=context_pack,
        budget_snapshot=task_plan["budget"],
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
        invocation_factory=lambda active_plan, task, active: invocation,
    )

    record = materializer.verify(
        worker_result,
        task=resolved,
        request=TaskPlanResultVerificationRequest(
            plan=plan,
            task=resolved,
            instance=instance,
            worker_result=worker_result,
        ),
    )

    assert record.is_graph_only is True
    assert "workflow_id" not in record.to_dict()
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    envelope = next(iter(attempts.envelopes.values()))
    assert envelope.binding.graph_id == plan.graph_id
    assert envelope.binding.graph_version == plan.graph_ref
    assert envelope.output_schema_ref == SUBAGENT_NODE_RESULT_SCHEMA_V2
    assert envelope.output_schema_digest == (
        "sha256:4ceda242a6b595d794baba8433db600701b296f579d1f69721357769e8a890b3"
    )
    assert envelope.provenance.producer_revision == "harness-subagent-result-adapter@2"
    assert envelope.materialized_refs[0].ref in record.output_refs

    stored = artifact.read_artifact(envelope.materialized_refs[0].ref)["payload"]["value"]
    bundle = verify_subagent_materialized_bundle(
        stored,
        expected_binding=envelope.binding,
    )
    assert bundle.bundle_schema == SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V2
    assert bundle.identity == invocation.attempt_identity
    assert bundle.receipt.schema_version == SUBAGENT_RECEIPT_SCHEMA_V2
    assert "workflow_id" not in stable_json_dumps(stored)

    mixed_schema = dict(stored)
    mixed_schema["bundle_schema"] = SUBAGENT_MATERIALIZED_BUNDLE_SCHEMA_V1
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

    legacy_identity_materializer = ResearchTaskPlanResultMaterializer(
        verifier=task_plan["verifier"],
        adapter=common_adapter,
        config=config,
        tenant_id=tenant_id,
        tenant_scope_ref=checksum_for(tenant_id),
        invocation_factory=lambda active_plan, task, active: invocation,
        legacy_graph_id="legacy.graph",
        legacy_graph_version="legacy.graph@1",
    )
    with pytest.raises(HarnessValidationError) as legacy_error:
        legacy_identity_materializer.verify(
            worker_result,
            task=resolved,
            request=TaskPlanResultVerificationRequest(
                plan=plan,
                task=resolved,
                instance=instance,
                worker_result=worker_result,
            ),
        )
    assert legacy_error.value.code == "legacy_graph_identity_forbidden"
    assert artifact.write_count == 1
    assert attempts.put_count == 1
