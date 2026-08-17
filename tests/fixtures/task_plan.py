from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.graph import (
    HarnessGraphSpec,
    HarnessStepSpec,
    HarnessWorkerType,
    StepRef,
)
from framework.harness.task_plan import TaskPlanStageBinding
from framework.harness.task_plan.schema import VALIDATED_TASK_PLAN_SCHEMA
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.workflow.spec import HarnessWorkflowSpec


_DEFAULT_SUPPORT_REFS = {
    "candidate_builder_ref": "test.task-plan-builder@1",
    "capability_registry_ref": "test.task-capability-registry@1",
    "gate_registry_ref": "test.task-gate-registry@1",
    "aggregator_ref": "test.task-plan-aggregator@1",
    "event_schema": "newsroom.harness-task-plan-event/v1",
    "checkpoint_ref": "test.task-plan-checkpoint@1",
    "result_store_ref": "test.task-plan-result-store@1",
}


def build_task_plan_stage_binding(
    *,
    workflow_id: str,
    stage_id: str,
    policy_ref: str,
    required_output_roles: Sequence[str],
    input_keys: Sequence[str] = ("document", "evidence_pack"),
    metadata_overrides: Mapping[str, Any] | None = None,
    worker_type: HarnessWorkerType | str = HarnessWorkerType.TASK_PLAN,
) -> TaskPlanStageBinding:
    metadata: dict[str, Any] = {
        "dynamic_stage": True,
        "task_plan_policy_ref": policy_ref,
        "required_output_roles": list(required_output_roles),
        "task_plan_schema": VALIDATED_TASK_PLAN_SCHEMA,
        "task_plan_support": dict(_DEFAULT_SUPPORT_REFS),
    }
    metadata.update(metadata_overrides or {})
    step = HarnessStepSpec(
        step_id=stage_id,
        worker_type=worker_type,
        input_keys=tuple(input_keys),
        output_key="task_plan_output",
        metadata=metadata,
    )
    workflow = HarnessWorkflowSpec(
        workflow_id=workflow_id,
        workflow_version="1",
        steps=(step,),
        entry_step_id=stage_id,
        graph=HarnessGraphSpec(
            graph_id=f"{workflow_id}.graph",
            root=StepRef(stage_id),
            input_keys=tuple(input_keys),
            terminal_output_keys=("task_plan_output",),
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph
    return TaskPlanStageBinding(graph, stage_id)


__all__ = ["build_task_plan_stage_binding"]
