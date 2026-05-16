from __future__ import annotations

from core.framework.specs import FailurePolicySpec, RetryPolicySpec, StepSpec, WorkflowStatus

from helpers import (
    make_function_registry,
    read_events,
    run_dir,
    run_workflow,
)
from helpers import make_linear_workflow as _make_linear_workflow


def test_retry_timeout_failure_contract_retries_matching_error_type(tmp_path) -> None:
    calls = {"count": 0}

    def flaky(buffer):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return {"report": "recovered"}

    workflow = type(_make_linear_workflow())(
        workflow_id="retry-contract",
        name="Retry Contract",
        version="1.0",
        start_step_id="flaky",
        terminal_step_ids=["flaky"],
        steps=[
            StepSpec(
                "flaky",
                "test.flaky",
                write_keys=["report"],
                required_output_keys=["report"],
                retry_policy=RetryPolicySpec(
                    max_retries=1,
                    retry_delay_seconds=[0],
                    retry_on_error_types=["RuntimeError"],
                ),
            )
        ],
    )

    result = run_workflow(
        tmp_path,
        workflow,
        make_function_registry({"test.flaky": flaky}),
        run_id="retry-contract-run",
    )
    event_types = [event["event_type"] for event in read_events(run_dir(tmp_path, result.run_id))]

    assert result.status == WorkflowStatus.SUCCEEDED
    assert calls["count"] == 2
    assert event_types == [
        "workflow_started",
        "step_started",
        "step_retry_scheduled",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_retry_timeout_failure_contract_routes_to_fallback_step(tmp_path) -> None:
    workflow = type(_make_linear_workflow())(
        workflow_id="fallback-contract",
        name="Fallback Contract",
        version="1.0",
        start_step_id="primary",
        terminal_step_ids=["recover"],
        steps=[
            StepSpec(
                "primary",
                "test.primary",
                failure_policy=FailurePolicySpec(fallback_step_id="recover"),
            ),
            StepSpec(
                "recover",
                "test.recover",
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
    )
    registry = make_function_registry(
        {
            "test.primary": lambda buffer: (_ for _ in ()).throw(RuntimeError("primary failed")),
            "test.recover": lambda buffer: {"report": "recovered"},
        }
    )

    result = run_workflow(tmp_path, workflow, registry, run_id="fallback-contract-run")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.path == ["primary", "recover"]
    assert result.output["report"] == "recovered"
