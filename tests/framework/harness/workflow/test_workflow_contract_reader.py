from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.conditions import ConditionPredicate
from framework.harness.workflow.dsl import Choice, ChoiceBranch, HarnessGraphSpec, StepRef
from framework.harness.workflow.reader import HarnessWorkflowContractReader
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.workflow.step import HarnessRetryPolicy, HarnessStepSpec
from framework.harness.workflow.versioning import HARNESS_GRAPH_DSL_SCHEMA, LEGACY_WORKFLOW_SCHEMA


def test_legacy_serialization_shape_remains_byte_compatible_and_reads_explicitly() -> None:
    workflow = _legacy_workflow()
    payload = workflow.to_dict()

    assert set(payload) == {
        "workflow_id",
        "steps",
        "entry_step_id",
        "terminal_policies",
        "routing_rules",
        "metadata",
    }
    assert workflow.schema_version == LEGACY_WORKFLOW_SCHEMA
    assert workflow.declaration_mode == "legacy"

    restored = HarnessWorkflowContractReader().read(
        payload,
        source_schema=LEGACY_WORKFLOW_SCHEMA,
    )
    assert restored.to_dict() == payload
    assert restored.graph is None


def test_explicit_graph_is_the_only_active_route_declaration_and_executes_by_exact_schema() -> None:
    graph = HarnessGraphSpec(
        graph_id="research-graph",
        root=Choice(
            choice_id="route",
            branches=(
                ChoiceBranch(
                    branch_id="accepted",
                    child=StepRef("report"),
                    priority=0,
                    condition=ConditionPredicate(
                        path="quality_verdict.passed",
                        operator="equals",
                        expected=True,
                    ),
                ),
                ChoiceBranch(
                    branch_id="repair",
                    child=StepRef("collect"),
                    priority=1,
                    is_default=True,
                ),
            ),
        ),
    )
    workflow = HarnessWorkflowSpec(
        workflow_id="research",
        workflow_version="2.3",
        steps=_steps(),
        entry_step_id="collect",
        graph=graph,
    )
    payload = workflow.to_dict()

    assert payload["schema_version"] == HARNESS_GRAPH_DSL_SCHEMA
    assert payload["workflow_version"] == "2.3"
    assert payload["routing_rules"] == []
    assert workflow.declaration_mode == "graph"

    restored = HarnessWorkflowContractReader().read_for_execution(
        payload,
        source_schema=HARNESS_GRAPH_DSL_SCHEMA,
    )
    assert restored == workflow


def test_explicit_graph_and_legacy_routes_are_rejected_as_ambiguous() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessWorkflowSpec(
            workflow_id="ambiguous",
            steps=_steps(),
            entry_step_id="collect",
            routing_rules=(HarnessRoutingRule("collect", "report"),),
            graph=HarnessGraphSpec(graph_id="graph", root=StepRef("collect")),
        )

    assert captured.value.code == "ambiguous_workflow_declaration"


def test_legacy_reader_is_read_only_and_unknown_versions_fail_closed() -> None:
    reader = HarnessWorkflowContractReader()
    payload = _legacy_workflow().to_dict()

    with pytest.raises(HarnessValidationError) as captured:
        reader.read_for_execution(payload, source_schema=LEGACY_WORKFLOW_SCHEMA)
    assert captured.value.code == "graph_schema_not_executable"

    with pytest.raises(HarnessValidationError) as captured:
        reader.read(payload, source_schema="newsroom.harness-workflow-spec/v999")
    assert captured.value.code == "unsupported_graph_schema"


def _legacy_workflow() -> HarnessWorkflowSpec:
    return HarnessWorkflowSpec(
        workflow_id="research",
        steps=_steps(),
        entry_step_id="collect",
        routing_rules=(HarnessRoutingRule("collect", "report"),),
        metadata={"version": "1.4"},
    )


def _steps() -> tuple[HarnessStepSpec, ...]:
    return (
        HarnessStepSpec(
            step_id="collect",
            worker_type="retrieval",
            output_key="evidence",
            retry_policy=HarnessRetryPolicy(max_retries=1),
        ),
        HarnessStepSpec(
            step_id="report",
            worker_type="llm",
            input_keys=("evidence",),
            output_key="report",
        ),
    )
