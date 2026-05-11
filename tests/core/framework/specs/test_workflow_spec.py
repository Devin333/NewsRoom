import pytest

from core.framework.specs import (
    EdgeSpec,
    RetryPolicySpec,
    StepSpec,
    StepType,
    WorkflowSpec,
    WorkflowSpecError,
)


def test_valid_workflow_spec_passes_validation() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[
            StepSpec(step_id="start", implementation="sample.start", step_type=StepType.FUNCTION),
            StepSpec(step_id="finish", implementation="sample.finish"),
        ],
        edges=[EdgeSpec(edge_id="start-to-finish", source_step_id="start", target_step_id="finish")],
    )

    spec.validate()

    assert spec.step_by_id("finish").implementation == "sample.finish"
    assert spec.to_dict()["steps"][0]["step_type"] == "function"


def test_step_spec_serializes_retry_policy() -> None:
    step = StepSpec(
        step_id="flaky",
        implementation="sample.flaky",
        retry_policy=RetryPolicySpec(
            max_retries=2,
            retry_delay_seconds=[1, 5],
            retry_on_error_types=["RuntimeError"],
            no_retry_on_error_types=["ValueError"],
        ),
    )

    payload = step.to_dict()

    assert payload["retry_policy"] == {
        "max_retries": 2,
        "retry_delay_seconds": [1, 5],
        "backoff_strategy": "fixed",
        "retry_on_error_types": ["RuntimeError"],
        "no_retry_on_error_types": ["ValueError"],
    }


def test_retry_policy_rejects_negative_values() -> None:
    with pytest.raises(WorkflowSpecError, match="max_retries must be non-negative"):
        RetryPolicySpec(max_retries=-1)

    with pytest.raises(WorkflowSpecError, match="retry_delay_seconds"):
        RetryPolicySpec(retry_delay_seconds=[-1])


def test_workflow_spec_rejects_missing_start_step() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="missing",
        steps=[StepSpec(step_id="start", implementation="sample.start")],
    )

    with pytest.raises(WorkflowSpecError, match="start step does not exist"):
        spec.validate()


def test_workflow_spec_rejects_duplicate_step_ids() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="same",
        steps=[
            StepSpec(step_id="same", implementation="sample.one"),
            StepSpec(step_id="same", implementation="sample.two"),
        ],
    )

    with pytest.raises(WorkflowSpecError, match="duplicate step ids"):
        spec.validate()


def test_workflow_spec_rejects_missing_edge_endpoint() -> None:
    spec = WorkflowSpec(
        workflow_id="sample",
        name="Sample",
        version="1.0",
        start_step_id="start",
        steps=[StepSpec(step_id="start", implementation="sample.start")],
        edges=[EdgeSpec(edge_id="bad-edge", source_step_id="start", target_step_id="missing")],
    )

    with pytest.raises(WorkflowSpecError, match="missing target step"):
        spec.validate()
