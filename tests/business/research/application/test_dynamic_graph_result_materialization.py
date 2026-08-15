from __future__ import annotations

from pathlib import Path

from business.research.application.graph_result_committer import (
    ResearchTaskPlanResultMaterializer,
)
from framework.events.canonical import checksum_for
from framework.harness import (
    ContextEnvelope,
    HarnessBudget,
    HarnessBudgetSnapshot,
    ResolvedSubAgentTaskAdapter,
    SubAgentRuntime,
    TaskLifecycle,
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
)
from framework.harness.graph import HarnessWorkerType
from tests.framework.harness.runtime.test_materializer import (
    RecordingArtifactPort,
    RecordingAttempts,
    RecordingCache,
    RecordingCatalog,
    RecordingQuota,
    _materializer,
)
from tests.framework.harness.task_plan.test_subagent_result_lineage import (
    _fixture as _task_plan_fixture,
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
        resolved_task=resolved,
        binding=binding,
        task_instance_id=instance.task_instance_id,
        parent_run_id=plan.run_id,
        workflow_id=plan.workflow_id,
        stage_id=plan.stage_id,
        context_pack=context_pack,
        budget_snapshot=budget,
        attempt=instance.attempt,
        observed_at=plan.accepted_at,
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
        graph_id="research.paper_analysis.dynamic.graph",
        graph_version="research.paper_analysis.dynamic.graph@1",
        invocation_factory=lambda task, active: invocation,
    )

    first = verifier.verify(
        worker_result,
        task=resolved,
        request=instance,
        workflow_id=plan.workflow_id,
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
        request=instance,
        workflow_id=plan.workflow_id,
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
        graph_id="research.paper_analysis.dynamic.graph",
        graph_version="research.paper_analysis.dynamic.graph@1",
        invocation_factory=lambda task, active: invocation,
    )

    read_only_result = read_only_verifier.verify(
        recovered_result,
        task=resolved,
        request=instance,
        workflow_id=plan.workflow_id,
    )

    assert read_only_result.status is TaskLifecycle.SUCCEEDED
    assert task_plan["worker"].calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1
