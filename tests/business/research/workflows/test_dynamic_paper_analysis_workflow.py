from __future__ import annotations

from dataclasses import replace

from business.research.graphs import (
    build_research_analysis_task_plan_policy,
)
from business.research.workflows.paper_analysis_workflow import (
    build_dynamic_paper_analysis_workflow_spec,
    build_paper_analysis_workflow_spec,
)
from framework.harness.graph import HarnessWorkerType
from framework.harness.workflow.compiler import HarnessWorkflowGraphCompiler
from framework.harness.graph.validation import HarnessGraphPreflight


def test_dynamic_variant_replaces_only_analysis_fanout():
    static = build_paper_analysis_workflow_spec()
    dynamic = build_dynamic_paper_analysis_workflow_spec()
    assert static.workflow_id == "research.paper_analysis"
    assert dynamic.workflow_id == "research.paper_analysis.dynamic"
    assert dynamic.graph.graph_id == "research.paper_analysis.dynamic.graph"
    assert "dynamic_analysis_stage" in dynamic.step_ids
    assert all(step_id not in dynamic.step_ids for step_id in ("analyze_structure", "analyze_contribution", "analyze_experiments"))
    stage = next(step for step in dynamic.steps if step.step_id == "dynamic_analysis_stage")
    assert stage.worker_type is HarnessWorkerType.TASK_PLAN
    assert stage.output_key == "analysis_branch_refs"
    assert next(step for step in dynamic.steps if step.step_id == "verify_claims").input_keys[-1] == "analysis_branch_refs"


def test_dynamic_policy_pins_required_roles_and_budgets():
    policy = build_research_analysis_task_plan_policy()
    assert policy.exact_ref == "research.analysis@1"
    assert policy.stage_id == "dynamic_analysis_stage"
    assert policy.required_output_roles == (
        "analysis.contribution",
        "analysis.experiments",
        "analysis.structure",
    )
    assert policy.max_parallelism == 3


def test_compiled_dynamic_stage_support_declaration_passes_preflight() -> None:
    workflow = build_dynamic_paper_analysis_workflow_spec()
    graph = HarnessWorkflowGraphCompiler().compile(workflow).graph

    diagnostics = HarnessGraphPreflight().validate_static(graph).diagnostics

    assert not [
        item for item in diagnostics if item.code.startswith("dynamic_task_plan")
    ]


def test_compiled_dynamic_stage_preflight_rejects_inexact_or_missing_support() -> None:
    workflow = build_dynamic_paper_analysis_workflow_spec()
    stage = next(
        step for step in workflow.steps if step.step_id == "dynamic_analysis_stage"
    )
    support = dict(stage.metadata["task_plan_support"])
    support["candidate_builder_ref"] = "research.task-plan-builder@latest"
    support.pop("result_store_ref")
    invalid_stage = replace(
        stage,
        metadata={
            **stage.metadata,
            "task_plan_policy_ref": "research.analysis@current",
            "task_plan_support": support,
        },
    )
    invalid = replace(
        workflow,
        steps=tuple(
            invalid_stage if step.step_id == invalid_stage.step_id else step
            for step in workflow.steps
        ),
    )
    graph = HarnessWorkflowGraphCompiler().compile(invalid).graph

    codes = {
        item.code for item in HarnessGraphPreflight().validate_static(graph).diagnostics
    }

    assert "dynamic_task_plan_policy_missing_or_inexact" in codes
    assert "dynamic_task_plan_support_incomplete" in codes
    assert "dynamic_task_plan_support_inexact" in codes
