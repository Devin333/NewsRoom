from __future__ import annotations

from dataclasses import replace

import pytest

from business.research.graphs import (
    RESEARCH_DYNAMIC_INPUT_REFS,
    RESEARCH_DYNAMIC_OUTPUT_ROLES,
    RESEARCH_DYNAMIC_POLICY_REF,
    RESEARCH_DYNAMIC_STAGE_ID,
    build_dynamic_paper_analysis_graph_definition,
    build_research_analysis_task_plan_policy,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph import HarnessGraphCompiler
from framework.harness.task_plan import (
    DEFAULT_TASK_PLAN_SCHEMA_REGISTRY,
    GRAPH_ONLY_PLAN_CANDIDATE_SCHEMA,
    GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA,
    PLAN_CANDIDATE_SCHEMA,
    TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    VALIDATED_TASK_PLAN_SCHEMA,
    PlanBuildRequest,
    TaskPlanContractKind,
    TaskPlanStageBinding,
    TaskPlanStageIdentity,
    TaskPlanStageRequest,
    TaskPlanValidationContext,
)
from tests.fixtures.task_plan import build_task_plan_stage_binding


def _legacy_binding() -> TaskPlanStageBinding:
    return build_task_plan_stage_binding(
        workflow_id="research.paper_analysis.dynamic",
        stage_id=RESEARCH_DYNAMIC_STAGE_ID,
        policy_ref=RESEARCH_DYNAMIC_POLICY_REF,
        required_output_roles=RESEARCH_DYNAMIC_OUTPUT_ROLES,
        input_keys=RESEARCH_DYNAMIC_INPUT_REFS,
    )


def _graph_only_binding(*, graph_version: str | None = None) -> TaskPlanStageBinding:
    definition = build_dynamic_paper_analysis_graph_definition()
    if graph_version is not None:
        definition = replace(
            definition,
            graph_version=graph_version,
            definition_checksum=None,
        )
    graph = HarnessGraphCompiler().compile(definition).graph
    return TaskPlanStageBinding(graph, RESEARCH_DYNAMIC_STAGE_ID)


def _request(binding: TaskPlanStageBinding) -> PlanBuildRequest:
    return PlanBuildRequest(
        run_id="research-run",
        stage_binding=binding,
        context_refs={name: name for name in RESEARCH_DYNAMIC_INPUT_REFS},
        policy=build_research_analysis_task_plan_policy(),
    )


def test_stage_identity_registry_keeps_v1_writer_and_admits_v2() -> None:
    registration = next(
        item
        for item in DEFAULT_TASK_PLAN_SCHEMA_REGISTRY.registrations
        if item.contract_kind is TaskPlanContractKind.STAGE_IDENTITY
    )

    assert registration.writer_schema == TASK_PLAN_STAGE_IDENTITY_SCHEMA
    assert set(registration.readable_schemas) == {
        TASK_PLAN_STAGE_IDENTITY_SCHEMA,
        GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    }
    assert set(registration.executable_schemas) == set(
        registration.readable_schemas
    )


def test_candidate_and_plan_registries_keep_v1_writers_and_admit_v2() -> None:
    registrations = {
        item.contract_kind: item
        for item in DEFAULT_TASK_PLAN_SCHEMA_REGISTRY.registrations
    }

    candidate = registrations[TaskPlanContractKind.PLAN_CANDIDATE]
    assert candidate.writer_schema == PLAN_CANDIDATE_SCHEMA
    assert set(candidate.readable_schemas) == {
        PLAN_CANDIDATE_SCHEMA,
        GRAPH_ONLY_PLAN_CANDIDATE_SCHEMA,
    }
    assert set(candidate.executable_schemas) == set(candidate.readable_schemas)

    plan = registrations[TaskPlanContractKind.VALIDATED_PLAN]
    assert plan.writer_schema == VALIDATED_TASK_PLAN_SCHEMA
    assert set(plan.readable_schemas) == {
        VALIDATED_TASK_PLAN_SCHEMA,
        GRAPH_ONLY_VALIDATED_TASK_PLAN_SCHEMA,
    }
    assert set(plan.executable_schemas) == set(plan.readable_schemas)


def test_legacy_stage_identity_round_trips_without_changing_request_wire() -> None:
    binding = _legacy_binding()
    identity = TaskPlanStageIdentity("research-run", binding)
    request = _request(binding)

    assert identity.schema_version == TASK_PLAN_STAGE_IDENTITY_SCHEMA
    assert identity.workflow_id == "research.paper_analysis.dynamic"
    assert identity.workflow_ref == "research.paper_analysis.dynamic@1"
    assert TaskPlanStageIdentity.from_dict(
        identity.to_dict(),
        stage_binding=binding,
    ) == identity
    assert request.to_dict() == {
        "run_id": "research-run",
        "workflow_id": "research.paper_analysis.dynamic",
        "stage_id": RESEARCH_DYNAMIC_STAGE_ID,
        "graph_checksum": binding.graph_checksum,
        "stage_binding_ref": binding.binding_checksum,
        "context_refs": {
            "document": "document",
            "evidence_pack": "evidence_pack",
        },
        "policy_ref": RESEARCH_DYNAMIC_POLICY_REF,
        "budget": {},
    }


def test_graph_only_stage_identity_and_plan_request_have_no_workflow_alias() -> None:
    binding = _graph_only_binding()
    identity = TaskPlanStageIdentity("research-run", binding)
    request = _request(binding)
    identity_payload = identity.to_dict()
    request_payload = request.to_dict()

    assert identity.schema_version == GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA
    assert identity_payload["graph_ref"] == binding.graph.graph_ref.exact_ref
    assert identity_payload["graph_id"] == binding.graph_id
    assert identity_payload["graph_version"] == binding.graph_version
    assert identity_payload["stage_binding_checksum"] == binding.binding_checksum
    assert not {"workflow_id", "workflow_ref"}.intersection(identity_payload)
    assert request_payload["graph_ref"] == identity.graph_ref
    assert request_payload["stage_identity_checksum"] == identity.identity_checksum
    assert request_payload["condition_policy_version"] == (
        binding.graph.condition_policy_version
    )
    assert not {"workflow_id", "workflow_ref"}.intersection(request_payload)
    assert TaskPlanStageIdentity.from_dict(
        identity_payload,
        stage_binding=binding,
    ) == identity

    with pytest.raises(HarnessValidationError) as error:
        _ = identity.workflow_id

    assert error.value.code == "legacy_task_plan_identity_forbidden"


def test_graph_only_contexts_share_the_frozen_stage_identity() -> None:
    binding = _graph_only_binding()
    policy = build_research_analysis_task_plan_policy()
    validation_context = TaskPlanValidationContext(
        run_id="research-run",
        stage_binding=binding,
        available_input_refs=RESEARCH_DYNAMIC_INPUT_REFS,
    )
    stage_request = TaskPlanStageRequest(
        run_id="research-run",
        stage_binding=binding,
        context_refs={name: name for name in RESEARCH_DYNAMIC_INPUT_REFS},
        policy=policy,
        accepted_at="2026-08-17T00:00:00Z",
    )

    assert validation_context.stage_identity == stage_request.stage_identity
    assert validation_context.graph_id == binding.graph_id
    assert validation_context.graph_version == binding.graph_version
    assert validation_context.graph_ref == binding.graph.graph_ref.exact_ref
    assert stage_request.graph_ref == validation_context.graph_ref

    for context in (validation_context, stage_request):
        with pytest.raises(HarnessValidationError) as error:
            _ = context.workflow_id
        assert error.value.code == "legacy_task_plan_identity_forbidden"


def test_graph_only_stage_identity_rejects_alias_tamper_and_cross_graph_restore() -> None:
    first_binding = _graph_only_binding()
    second_binding = _graph_only_binding(graph_version="2")
    identity = TaskPlanStageIdentity("research-run", first_binding)
    payload = identity.to_dict()

    with pytest.raises(HarnessValidationError) as alias_error:
        TaskPlanStageIdentity.from_dict(
            {**payload, "workflow_id": first_binding.graph_id},
            stage_binding=first_binding,
        )
    assert alias_error.value.code == "task_plan_stage_identity_projection_invalid"

    with pytest.raises(HarnessValidationError) as checksum_error:
        TaskPlanStageIdentity.from_dict(
            {**payload, "identity_checksum": "sha256:" + "0" * 64},
            stage_binding=first_binding,
        )
    assert checksum_error.value.code == "task_plan_stage_identity_checksum_invalid"

    with pytest.raises(HarnessValidationError) as graph_error:
        TaskPlanStageIdentity.from_dict(
            payload,
            stage_binding=second_binding,
        )
    assert graph_error.value.code == "task_plan_stage_identity_checksum_invalid"


def test_stage_identity_rejects_schema_binding_mixing() -> None:
    binding = _graph_only_binding()

    with pytest.raises(HarnessValidationError) as error:
        TaskPlanStageIdentity(
            "research-run",
            binding,
            schema_version=TASK_PLAN_STAGE_IDENTITY_SCHEMA,
        )

    assert error.value.code == "task_plan_stage_identity_schema_mismatch"

    with pytest.raises(HarnessValidationError) as empty_error:
        TaskPlanStageIdentity(
            "research-run",
            binding,
            schema_version="",
        )

    assert empty_error.value.code == "unsupported_task_plan_schema"
