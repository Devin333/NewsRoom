from __future__ import annotations

from dataclasses import replace
from inspect import signature

import pytest

from business.research.graphs import (
    RESEARCH_DYNAMIC_STAGE_ID,
    build_dynamic_paper_analysis_graph_definition,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import (
    HarnessExecutableNode,
    HarnessGraphCompiler,
    HarnessWorkerType,
)
from framework.harness.task_plan import (
    DEFAULT_TASK_PLAN_SCHEMA_REGISTRY,
    GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA,
    GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA,
    TASK_PLAN_STAGE_BINDING_SCHEMA,
    VALIDATED_TASK_PLAN_SCHEMA,
    TaskPlanContractKind,
    TaskPlanStageBinding,
    TaskPlanValidationContext,
)
from tests.fixtures.task_plan import build_task_plan_stage_binding


def _binding(**overrides) -> TaskPlanStageBinding:
    values = {
        "workflow_id": "binding-workflow",
        "stage_id": "dynamic-stage",
        "policy_ref": "binding-policy@1",
        "required_output_roles": ("analysis.result",),
        "input_keys": ("document",),
    }
    values.update(overrides)
    return build_task_plan_stage_binding(**values)


def _graph_only_binding() -> TaskPlanStageBinding:
    graph = HarnessGraphCompiler().compile(
        build_dynamic_paper_analysis_graph_definition()
    ).graph
    return TaskPlanStageBinding(graph, RESEARCH_DYNAMIC_STAGE_ID)


def test_stage_binding_derives_all_authority_from_the_frozen_graph() -> None:
    binding = _binding()

    assert binding.schema_version == TASK_PLAN_STAGE_BINDING_SCHEMA
    assert binding.workflow_id == binding.graph.workflow_id
    assert binding.graph_checksum == binding.graph.checksum
    assert binding.stage_id == "dynamic-stage"
    assert binding.policy_ref == "binding-policy@1"
    assert binding.required_output_roles == ("analysis.result",)
    assert binding.worker_ref.endswith("@1")
    assert binding.activity_ref.endswith("@v1")
    assert binding.to_dict()["binding_checksum"] == binding.binding_checksum
    assert binding.binding_checksum == (
        "sha256:ef6e4bc73aba05b91dc49e0075d784af664368788aa3075c4a4028a10a8a6a81"
    )

    rebuilt = TaskPlanStageBinding(binding.graph, binding.stage_id)
    assert rebuilt.binding_checksum == binding.binding_checksum
    assert TaskPlanStageBinding.from_dict(
        binding.to_dict(),
        graph=binding.graph,
    ) == binding


def test_graph_only_stage_binding_uses_only_exact_graph_identity() -> None:
    binding = _graph_only_binding()
    payload = binding.to_dict()

    assert binding.schema_version == GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA
    assert binding.task_plan_schema == GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA
    assert binding.graph.graph_ref is not None
    assert payload["graph_ref"] == binding.graph.graph_ref.exact_ref
    assert payload["graph_version"] == binding.graph.identity_version
    assert payload["graph_checksum"] == binding.graph.checksum
    assert payload["condition_policy_version"] == (
        binding.graph.condition_policy_version
    )
    assert not {"workflow_id", "workflow_ref"}.intersection(payload)
    assert TaskPlanStageBinding.from_dict(
        payload,
        graph=binding.graph,
    ) == binding

    with pytest.raises(HarnessValidationError) as error:
        _ = binding.workflow_id

    assert error.value.code == "legacy_task_plan_identity_forbidden"


def test_stage_binding_registry_keeps_v1_writer_and_admits_v2_contract() -> None:
    registration = next(
        item
        for item in DEFAULT_TASK_PLAN_SCHEMA_REGISTRY.registrations
        if item.contract_kind is TaskPlanContractKind.STAGE_BINDING
    )

    assert registration.writer_schema == TASK_PLAN_STAGE_BINDING_SCHEMA
    assert set(registration.readable_schemas) == {
        TASK_PLAN_STAGE_BINDING_SCHEMA,
        GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA,
    }
    assert set(registration.executable_schemas) == {
        TASK_PLAN_STAGE_BINDING_SCHEMA,
        GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA,
    }


def test_stage_binding_rejects_schema_identity_mixing() -> None:
    legacy = _binding()
    graph_only = _graph_only_binding()

    with pytest.raises(HarnessValidationError) as legacy_error:
        TaskPlanStageBinding(
            legacy.graph,
            legacy.stage_id,
            schema_version=GRAPH_ONLY_TASK_PLAN_STAGE_BINDING_SCHEMA,
        )
    assert legacy_error.value.code == "task_plan_stage_binding_schema_mismatch"

    with pytest.raises(HarnessValidationError) as graph_error:
        TaskPlanStageBinding(
            graph_only.graph,
            graph_only.stage_id,
            schema_version=TASK_PLAN_STAGE_BINDING_SCHEMA,
        )
    assert graph_error.value.code == "task_plan_stage_binding_schema_mismatch"


def test_graph_only_stage_binding_rejects_legacy_plan_schema() -> None:
    definition = build_dynamic_paper_analysis_graph_definition()
    stage_binding = definition.task_plan_stage_bindings[0]
    legacy_definition = replace(
        definition,
        task_plan_stage_bindings=(
            replace(
                stage_binding,
                task_plan_schema=VALIDATED_TASK_PLAN_SCHEMA,
            ),
        ),
        definition_checksum=None,
    )
    graph = HarnessGraphCompiler().compile(legacy_definition).graph

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageBinding(graph, RESEARCH_DYNAMIC_STAGE_ID)

    assert error.value.code == "dynamic_task_plan_schema_identity_mismatch"


def test_graph_only_stage_binding_rejects_legacy_event_schema() -> None:
    definition = build_dynamic_paper_analysis_graph_definition()
    stage_binding = definition.task_plan_stage_bindings[0]
    legacy_definition = replace(
        definition,
        task_plan_stage_bindings=(
            replace(
                stage_binding,
                support_refs={
                    **dict(stage_binding.support_refs),
                    "event_schema": "newsroom.harness-task-plan-event/v1",
                },
            ),
        ),
        definition_checksum=None,
    )
    graph = HarnessGraphCompiler().compile(legacy_definition).graph

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageBinding(graph, RESEARCH_DYNAMIC_STAGE_ID)

    assert error.value.code == "dynamic_task_plan_event_schema_identity_mismatch"


def test_graph_only_stage_binding_reader_rejects_aliases_and_tampering() -> None:
    binding = _graph_only_binding()
    payload = binding.to_dict()

    with pytest.raises(HarnessValidationError) as alias_error:
        TaskPlanStageBinding.from_dict(
            {**payload, "workflow_id": binding.graph_id},
            graph=binding.graph,
        )
    assert alias_error.value.code == "task_plan_stage_binding_projection_invalid"

    with pytest.raises(HarnessValidationError) as checksum_error:
        TaskPlanStageBinding.from_dict(
            {**payload, "binding_checksum": "sha256:" + "0" * 64},
            graph=binding.graph,
        )
    assert checksum_error.value.code == "task_plan_stage_binding_checksum_invalid"


def test_graph_only_stage_binding_rejects_non_definition_authority() -> None:
    binding = _graph_only_binding()
    node = next(
        item
        for item in binding.graph.nodes
        if isinstance(item, HarnessExecutableNode)
        and item.step_id == RESEARCH_DYNAMIC_STAGE_ID
    )
    tampered_node = replace(
        node,
        metadata={**dict(node.metadata), "binding_source": "legacy_compiler"},
    )
    tampered_graph = replace(
        binding.graph,
        nodes=tuple(
            tampered_node if item.node_id == node.node_id else item
            for item in binding.graph.nodes
        ),
        checksum=None,
    )

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageBinding(tampered_graph, RESEARCH_DYNAMIC_STAGE_ID)

    assert error.value.code == "graph_task_plan_binding_source_invalid"


def test_graph_only_binding_checksum_changes_with_the_frozen_graph() -> None:
    definition = build_dynamic_paper_analysis_graph_definition()
    revised_definition = replace(
        definition,
        graph_version="2",
        definition_checksum=None,
    )
    first_graph = HarnessGraphCompiler().compile(definition).graph
    second_graph = HarnessGraphCompiler().compile(revised_definition).graph
    first = TaskPlanStageBinding(first_graph, RESEARCH_DYNAMIC_STAGE_ID)
    second = TaskPlanStageBinding(second_graph, RESEARCH_DYNAMIC_STAGE_ID)

    assert first.graph_checksum != second.graph_checksum
    assert first.binding_checksum != second.binding_checksum
    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageBinding.from_dict(first.to_dict(), graph=second_graph)

    assert error.value.code == "task_plan_stage_binding_checksum_invalid"


def test_validation_context_has_no_caller_dynamic_stage_attestation() -> None:
    binding = _binding()

    assert "dynamic_stage_declared" not in signature(
        TaskPlanValidationContext
    ).parameters
    with pytest.raises(TypeError):
        TaskPlanValidationContext(
            run_id="run",
            stage_binding=binding,
            available_input_refs=("document",),
            dynamic_stage_declared=True,
        )


@pytest.mark.parametrize(
    ("overrides", "code"),
    (
        (
            {"metadata_overrides": {"dynamic_stage": False}},
            "dynamic_task_plan_stage_marker_missing",
        ),
        (
            {"worker_type": HarnessWorkerType.LLM},
            "dynamic_task_plan_worker_type_mismatch",
        ),
        (
            {"metadata_overrides": {"task_plan_support": {}}},
            "dynamic_task_plan_support_incomplete",
        ),
        (
            {"metadata_overrides": {"task_plan_schema": "task-plan@latest"}},
            "dynamic_task_plan_schema_missing_or_inexact",
        ),
    ),
)
def test_stage_binding_rejects_unregistered_or_inexact_stage_declarations(
    overrides,
    code,
) -> None:
    with pytest.raises(HarnessValidationError) as error:
        _binding(**overrides)

    assert error.value.code == code


def test_stage_binding_rejects_a_stage_not_present_in_the_graph() -> None:
    binding = _binding()

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageBinding(binding.graph, "unregistered-stage")

    assert error.value.code == "task_plan_stage_binding_missing"


def test_binding_checksum_changes_with_the_frozen_graph() -> None:
    first = _binding()
    second = _binding(metadata_overrides={"test_graph_revision": "2"})

    assert first.graph_checksum != second.graph_checksum
    assert first.binding_checksum != second.binding_checksum
    assert replace(first, graph=second.graph).binding_checksum == second.binding_checksum
