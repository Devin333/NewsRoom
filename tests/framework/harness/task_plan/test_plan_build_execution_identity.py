from __future__ import annotations

import pytest

from business.research.graphs import (
    RESEARCH_DYNAMIC_INPUT_REFS,
    RESEARCH_DYNAMIC_STAGE_ID,
    build_dynamic_paper_analysis_graph_definition,
    build_research_analysis_task_plan_policy,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import HarnessGraphCompiler
from framework.harness.task_plan import (
    FakePlanCandidateBuilder,
    InMemoryTaskPlanStore,
    PlanBuildRequest,
    TaskCapabilityRegistry,
    TaskPlanStageBinding,
    TaskPlanStageRequest,
    TaskPlanStageRunner,
)
from framework.shared.graph_identity import GraphExecutionIdentity


def _binding() -> TaskPlanStageBinding:
    graph = HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph
    return TaskPlanStageBinding(graph, RESEARCH_DYNAMIC_STAGE_ID)


def _identity(binding: TaskPlanStageBinding) -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id="research-run",
        graph_id=binding.graph_id,
        graph_version=binding.graph_version,
        graph_ref=binding.graph.graph_ref.exact_ref,
        graph_checksum=binding.graph_checksum,
        node_id=binding.node_id,
        node_instance_id="dynamic-analysis-stage:1",
        activity_id="activity-1",
        attempt=1,
    )


def test_stage_runner_forwards_identity_to_plan_builder() -> None:
    binding = _binding()
    policy = build_research_analysis_task_plan_policy()
    identity = _identity(binding)
    builder = FakePlanCandidateBuilder(
        HarnessValidationError("planner unavailable", code="planner_unavailable")
    )
    runner = TaskPlanStageRunner(
        candidate_builder=builder,
        capability_registry=TaskCapabilityRegistry(),
        store=InMemoryTaskPlanStore(),
    )

    result = runner.run(
        TaskPlanStageRequest(
            run_id="research-run",
            stage_binding=binding,
            context_refs={name: name for name in RESEARCH_DYNAMIC_INPUT_REFS},
            policy=policy,
            accepted_at="2026-08-17T00:00:00Z",
            execution_identity=identity,
        )
    )

    assert result.status.value == "blocked"
    assert builder.calls[0].execution_identity == identity


def test_plan_builder_rejects_identity_outside_frozen_stage() -> None:
    binding = _binding()
    policy = build_research_analysis_task_plan_policy()
    identity = _identity(binding)

    with pytest.raises(HarnessValidationError) as exc_info:
        PlanBuildRequest(
            run_id="research-run",
            stage_binding=binding,
            context_refs={name: name for name in RESEARCH_DYNAMIC_INPUT_REFS},
            policy=policy,
            execution_identity=GraphExecutionIdentity(
                **{
                    **identity.to_dict(),
                    "node_id": "other-node",
                }
            ),
        )

    assert exc_info.value.code == "task_plan_execution_identity_mismatch"
