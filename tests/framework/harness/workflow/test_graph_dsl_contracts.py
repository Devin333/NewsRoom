from __future__ import annotations

from types import MappingProxyType

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.conditions import (
    ConditionAll,
    ConditionAny,
    ConditionOperator,
    ConditionPredicate,
    condition_from_dict,
    condition_from_legacy_dict,
    evaluate_condition,
)
from framework.harness.workflow.dsl import (
    BoundedLoop,
    Choice,
    ChoiceBranch,
    CompensationBinding,
    HarnessGraphSpec,
    ParallelAll,
    ParallelAny,
    ParallelBranch,
    Sequence,
    StepRef,
    Wait,
    WaitTimeoutPolicy,
)
from framework.harness.workflow.versioning import HARNESS_GRAPH_DSL_SCHEMA


def test_every_graph_dsl_construct_round_trips_canonically() -> None:
    passed = ConditionPredicate(
        path="quality_verdict.passed",
        operator=ConditionOperator.EQUALS,
        expected=True,
    )
    score = ConditionPredicate(
        path="quality_verdict.score",
        operator=ConditionOperator.GTE,
        expected=0.8,
    )
    graph = HarnessGraphSpec(
        graph_id="research-analysis",
        root=Sequence(
            sequence_id="root-sequence",
            children=(
                StepRef("collect"),
                Choice(
                    choice_id="evidence-choice",
                    branches=(
                        ChoiceBranch(
                            branch_id="verified",
                            child=ParallelAll(
                                fork_id="analysis-fork",
                                join_id="analysis-join",
                                branches=(
                                    ParallelBranch(
                                        branch_id="structure",
                                        child=StepRef("analyze_structure"),
                                        output_namespace="analysis.structure",
                                    ),
                                    ParallelBranch(
                                        branch_id="experiment",
                                        child=StepRef("analyze_experiment"),
                                        output_namespace="analysis.experiment",
                                    ),
                                ),
                                merge_ref="research_analysis_merge@1",
                            ),
                            priority=10,
                            condition=ConditionAll((passed, score)),
                        ),
                        ChoiceBranch(
                            branch_id="fallback",
                            child=ParallelAny(
                                fork_id="retrieval-fork",
                                join_id="retrieval-winner",
                                branches=(
                                    ParallelBranch(
                                        branch_id="primary",
                                        child=StepRef("retrieve_primary"),
                                        output_namespace="retrieval.primary",
                                    ),
                                    ParallelBranch(
                                        branch_id="secondary",
                                        child=StepRef("retrieve_secondary"),
                                        output_namespace="retrieval.secondary",
                                    ),
                                ),
                            ),
                            priority=20,
                            is_default=True,
                        ),
                    ),
                ),
                BoundedLoop(
                    loop_id="evidence-loop",
                    body=StepRef("collect_more"),
                    condition=ConditionAny((passed, score)),
                    max_iterations=3,
                    exit=StepRef("write_report"),
                    exhaustion=StepRef("manual_review"),
                ),
                Wait(
                    wait_id="approval-wait",
                    kind="approval",
                    correlation={"paper_id_path": "graph.inputs.paper_id"},
                    signal_type="research.report.approval",
                    signal_version="1",
                    tenant_scope_path="graph.inputs.tenant_id",
                    identity_scope_path="graph.inputs.actor_id",
                    timeout_policy=WaitTimeoutPolicy(
                        action="route", target_node_id="manual_review"
                    ),
                ),
            ),
        ),
        compensations=(
            CompensationBinding(
                binding_id="retract-publication",
                for_node_id="publish",
                compensation_step_id="retract",
                handler_ref="research.retract@1",
                activity_contract_ref="research.retract.activity@1",
            ),
        ),
        terminal_output_keys=("report", "publication"),
        metadata={"owner": "research", "tags": ["graph", "v2"]},
    )

    payload = graph.to_dict()
    restored = HarnessGraphSpec.from_dict(payload)

    assert payload["schema_version"] == HARNESS_GRAPH_DSL_SCHEMA
    assert restored == graph
    assert restored.to_dict() == payload


def test_pre_input_contract_graph_spec_defaults_missing_input_keys() -> None:
    graph = HarnessGraphSpec(
        graph_id="pre-input-contract",
        root=StepRef("one"),
        terminal_output_keys=("result",),
    )
    payload = graph.to_dict()
    payload.pop("input_keys")

    restored = HarnessGraphSpec.from_dict(payload)

    assert restored.input_keys == ()
    assert restored.terminal_output_keys == ("result",)


def test_dsl_deep_freezes_nested_json_and_rejects_unsupported_values() -> None:
    correlation = {"keys": ["paper", {"field": "tenant"}]}
    wait = Wait(
        wait_id="signal",
        kind="signal",
        correlation=correlation,
        signal_type="paper.ready",
        signal_version="1",
        tenant_scope_path="graph.inputs.tenant_id",
        identity_scope_path="graph.inputs.actor_id",
    )

    correlation["keys"].append("mutated")

    assert isinstance(wait.correlation, MappingProxyType)
    assert wait.to_dict()["correlation"] == {
        "keys": ["paper", {"field": "tenant"}],
    }
    with pytest.raises(TypeError):
        wait.correlation["other"] = "value"  # type: ignore[index]
    with pytest.raises(HarnessValidationError, match="canonical JSON"):
        HarnessGraphSpec(
            graph_id="invalid",
            root=StepRef("one"),
            metadata={"unsupported": object()},
        )


def test_condition_contract_is_shared_by_legacy_and_graph_evaluation() -> None:
    legacy = {
        "all": [
            {"path": "quality_verdict.passed", "equals": True},
            {"field": "quality_verdict.score", "gte": 0.8, "lte": 1.0},
        ]
    }

    condition = condition_from_legacy_dict(legacy)
    payload = condition.to_dict()
    restored = condition_from_dict(payload)

    assert restored == condition
    assert evaluate_condition(
        condition,
        {"quality_verdict": {"passed": True, "score": 0.9}},
    )
    assert not evaluate_condition(
        condition,
        {"quality_verdict": {"passed": True, "score": 1.1}},
    )


@pytest.mark.parametrize(
    "condition,code",
    (
        ({"path": "worker_result.status"}, "missing_condition_operator"),
        (
            {"path": "worker_result.status", "equals": "ok", "unknown": True},
            "unsupported_condition_field",
        ),
        (
            {"path": "private.secret", "equals": "value"},
            "forbidden_condition_path",
        ),
    ),
)
def test_legacy_condition_fail_closed(condition: dict[str, object], code: str) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        condition_from_legacy_dict(condition)

    assert captured.value.code == code


def test_choice_and_compensation_reject_ambiguous_or_moving_contracts() -> None:
    with pytest.raises(HarnessValidationError) as captured:
        ChoiceBranch(
            branch_id="ambiguous",
            child=StepRef("step"),
            priority=0,
            condition=ConditionPredicate(
                path="worker_result.status",
                operator="equals",
                expected="succeeded",
            ),
            is_default=True,
        )
    assert captured.value.code == "default_choice_has_condition"

    with pytest.raises(HarnessValidationError) as captured:
        CompensationBinding(
            binding_id="moving",
            for_node_id="publish",
            compensation_step_id="retract",
            handler_ref="research.retract@latest",
            activity_contract_ref="research.retract.activity@1",
        )
    assert captured.value.code == "graph_inexact_version_reference"
