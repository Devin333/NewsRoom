from __future__ import annotations

from core.framework.specs import RetryPolicySpec, StepSpec
from core.framework.workflow import OperationActor, WorkflowOperationType, append_operation_event
from core.framework.workflow.operations import operation_event

from helpers import make_function_registry, read_events, run_dir, run_workflow
from helpers import make_linear_workflow as _make_linear_workflow


def test_event_ordering_contract_for_successful_workflow(tmp_path) -> None:
    workflow = _make_linear_workflow(["plan", "write"])

    result = run_workflow(tmp_path, workflow, run_id="event-order-success")
    event_types = [event["event_type"] for event in read_events(run_dir(tmp_path, result.run_id))]

    assert event_types[0] == "workflow_started"
    assert event_types[-1] == "workflow_succeeded"
    assert event_types.index("step_started") < event_types.index("step_succeeded")
    assert "edge_evaluated" in event_types
    assert event_types.index("edge_evaluated") < event_types.index("edge_traversed")


def test_event_ordering_contract_for_retry_attempts(tmp_path) -> None:
    calls = {"count": 0}

    def flaky(buffer):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("try again")
        return {"report": "ok"}

    workflow = type(_make_linear_workflow())(
        workflow_id="event-order-retry",
        name="Event Order Retry",
        version="1.0",
        start_step_id="flaky",
        terminal_step_ids=["flaky"],
        steps=[
            StepSpec(
                "flaky",
                "test.flaky",
                write_keys=["report"],
                required_output_keys=["report"],
                retry_policy=RetryPolicySpec(max_retries=1, retry_delay_seconds=[0]),
            )
        ],
    )

    result = run_workflow(
        tmp_path,
        workflow,
        make_function_registry({"test.flaky": flaky}),
        run_id="event-order-retry-run",
    )
    event_types = [event["event_type"] for event in read_events(run_dir(tmp_path, result.run_id))]

    assert event_types == [
        "workflow_started",
        "step_started",
        "step_retry_scheduled",
        "step_started",
        "step_succeeded",
        "workflow_succeeded",
    ]


def test_event_ordering_contract_allows_operation_events_after_terminal(tmp_path) -> None:
    workflow = _make_linear_workflow(["plan"])
    result = run_workflow(tmp_path, workflow, run_id="event-order-operation")
    directory = run_dir(tmp_path, result.run_id)

    append_operation_event(
        directory,
        operation_event(
            "run_operation_requested",
            operation_id="op_contract",
            operation_type=WorkflowOperationType.CANCEL_RUN,
            run_id=result.run_id,
            actor=OperationActor("tester"),
            reason="audit",
            details={},
        ),
    )
    events = read_events(directory)

    assert events[-2]["event_type"] == "workflow_succeeded"
    assert events[-1]["event_type"] == "run_operation_requested"
    assert events[-1]["payload"]["operation_id"] == "op_contract"
