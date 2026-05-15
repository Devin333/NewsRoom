from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import RoutingEngine, WorkflowCompiler
from core.framework.workflow.scheduler import (
    StepOutcome,
    StepOutcomeStatus,
    WorkflowScheduler,
)


def test_fanout_schedules_multiple_ready_steps_and_join_waits_for_all_upstream() -> None:
    scheduler = _make_scheduler(_fanout_join_spec())

    scheduler.initialize({})
    ready = scheduler.next_ready_steps(max_count=1)
    assert [step.step_id for step in ready] == ["A"]

    scheduler.mark_step_finished("A", _success("A"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert {step.step_id for step in ready} == {"B", "C"}

    scheduler.mark_step_finished("B", _success("B"))
    assert not any(step.step_id == "J" for step in scheduler.state.ready_queue)
    assert scheduler.next_ready_steps(max_count=10) == []

    scheduler.mark_step_finished("C", _success("C"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["J"]
    assert ready[0].reason == "join_all_success"

    scheduler.mark_step_finished("J", _success("J"))
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


def _fanout_join_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="scheduler-fanout-join",
        name="Scheduler Fanout Join",
        version="1.0",
        start_step_id="A",
        terminal_step_ids=["J"],
        steps=[
            StepSpec("A", "test.A", write_keys=["a"]),
            StepSpec("B", "test.B", read_keys=["a"], write_keys=["b"]),
            StepSpec("C", "test.C", read_keys=["a"], write_keys=["c"]),
            StepSpec("J", "test.J", read_keys=["b", "c"], write_keys=["joined"]),
        ],
        edges=[
            EdgeSpec("A-B", "A", "B"),
            EdgeSpec("A-C", "A", "C"),
            EdgeSpec("B-J", "B", "J"),
            EdgeSpec("C-J", "C", "J"),
        ],
    )


def _success(step_id: str) -> StepOutcome:
    return StepOutcome(step_id=step_id, status=StepOutcomeStatus.SUCCESS)
