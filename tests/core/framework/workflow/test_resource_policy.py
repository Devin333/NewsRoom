from __future__ import annotations

import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import ResourcePolicySpec, StepSpec, WorkflowSpec, WorkflowSpecError, WorkflowStatus
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    FunctionStepRunner,
    StepResourceEstimator,
    StepResourceGuard,
    WorkflowExecutor,
)


def test_resource_policy_rejects_negative_fields() -> None:
    with pytest.raises(WorkflowSpecError, match="max_artifact_bytes"):
        ResourcePolicySpec(max_artifact_bytes=-1)


def test_resource_policy_allows_none_and_serializes_all_fields() -> None:
    policy = ResourcePolicySpec()

    assert policy.to_dict() == {
        "max_input_tokens": None,
        "max_output_tokens": None,
        "max_cost_usd": None,
        "max_items": None,
        "max_parallelism": None,
        "max_artifact_bytes": None,
    }


def test_resource_policy_coerces_from_dict() -> None:
    step = StepSpec(
        step_id="limited",
        implementation="sample.limited",
        resource_policy={"max_items": 3, "max_artifact_bytes": 1024},
    )

    assert step.resource_policy.max_items == 3
    assert step.resource_policy.max_artifact_bytes == 1024


def test_step_resource_estimator_counts_list_string_dict_and_missing_keys() -> None:
    step = StepSpec(
        step_id="estimate",
        implementation="sample.estimate",
        read_keys=["items", "text", "mapping", "missing"],
    )
    buffer = DataBuffer(
        {
            "items": ["a", "b", "c"],
            "text": "12345678",
            "mapping": {"a": 1, "b": 2},
        }
    )

    estimate = StepResourceEstimator().estimate_inputs(step, buffer)

    assert estimate.input_items == 5
    assert estimate.input_tokens == 5
    assert estimate.input_bytes > 0
    assert estimate.input_keys == ["items", "text", "mapping"]


def test_step_resource_guard_reports_max_input_tokens_violation() -> None:
    step = StepSpec(
        step_id="guard",
        implementation="sample.guard",
        resource_policy=ResourcePolicySpec(max_input_tokens=1),
    )

    violations = StepResourceGuard().check(
        step,
        StepResourceEstimator().estimate_inputs(
            StepSpec(
                step_id="guard",
                implementation="sample.guard",
                read_keys=["text"],
            ),
            DataBuffer({"text": "12345678"}),
        ),
    )

    assert violations[0].code == "resource.max_input_tokens"


def test_executor_blocks_step_over_max_items_and_records_violation(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.count", lambda buffer: {"count": len(buffer.read("request")["items"])})
    spec = WorkflowSpec(
        workflow_id="resource-block",
        name="Resource Block",
        version="1.0",
        start_step_id="count",
        steps=[
            StepSpec(
                step_id="count",
                implementation="sample.count",
                read_keys=["request"],
                write_keys=["count"],
                resource_policy=ResourcePolicySpec(max_items=1),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        spec,
        {"items": ["a", "b"]},
        profile="test",
        run_id="run-resource-block",
    )
    manifest = json.loads(
        (tmp_path / "run-resource-block" / "manifest.json").read_text(encoding="utf-8")
    )
    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-resource-block" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.error_type == "WorkflowResourcePolicyViolation"
    assert result.error.details["policy"] == "resource.max_items"
    assert manifest["policy_violations"][0]["policy"] == "resource.max_items"
    assert "policy_violation" in event_types


def test_executor_blocks_step_over_max_input_tokens(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.echo", lambda buffer: {"text": buffer.read("request")["text"]})
    spec = WorkflowSpec(
        workflow_id="token-block",
        name="Token Block",
        version="1.0",
        start_step_id="echo",
        steps=[
            StepSpec(
                step_id="echo",
                implementation="sample.echo",
                read_keys=["request"],
                write_keys=["text"],
                resource_policy=ResourcePolicySpec(max_input_tokens=1),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        spec,
        {"text": "12345678"},
        profile="test",
        run_id="run-token-block",
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.error.details["policy"] == "resource.max_input_tokens"
