from __future__ import annotations

from dataclasses import replace
from inspect import signature

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import HarnessWorkerType
from framework.harness.task_plan import (
    TASK_PLAN_STAGE_BINDING_SCHEMA,
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

    rebuilt = TaskPlanStageBinding(binding.graph, binding.stage_id)
    assert rebuilt.binding_checksum == binding.binding_checksum


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
