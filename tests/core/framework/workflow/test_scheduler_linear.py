from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import RoutingEngine, WorkflowCompiler
from core.framework.workflow.scheduler import (
    StepOutcome,
    StepOutcomeStatus,
    WorkflowScheduler,
)


def test_linear_workflow_schedules_steps_in_order() -> None:
    scheduler = _make_scheduler(_linear_spec())

    scheduler.initialize({})

    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["A"]

    scheduler.mark_step_finished("A", _success("A"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["B"]

    scheduler.mark_step_finished("B", _success("B"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["C"]

    scheduler.mark_step_finished("C", _success("C"))
    assert scheduler.is_terminal() is True


def _make_scheduler(spec: WorkflowSpec) -> WorkflowScheduler:
    result = WorkflowCompiler().compile(spec)
    assert result.passed
    assert result.graph is not None
    return WorkflowScheduler(
        workflow=spec,
        graph=result.graph,
        routing_engine=RoutingEngine(),
    )


def _linear_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="scheduler-linear",
        name="Scheduler Linear",
        version="1.0",
        start_step_id="A",
        terminal_step_ids=["C"],
        steps=[
            StepSpec("A", "test.A", write_keys=["a"]),
            StepSpec("B", "test.B", read_keys=["a"], write_keys=["b"]),
            StepSpec("C", "test.C", read_keys=["b"], write_keys=["c"]),
        ],
        edges=[
            EdgeSpec("A-B", "A", "B"),
            EdgeSpec("B-C", "B", "C"),
        ],
    )


def _success(step_id: str) -> StepOutcome:
    return StepOutcome(step_id=step_id, status=StepOutcomeStatus.SUCCESS)
