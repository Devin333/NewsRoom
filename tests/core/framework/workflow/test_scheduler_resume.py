from __future__ import annotations

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import RoutingEngine, WorkflowCompiler
from core.framework.workflow.scheduler import (
    StepOutcome,
    StepOutcomeStatus,
    WorkflowScheduler,
    scheduler_state_from_dict,
    scheduler_state_to_dict,
)


def test_scheduler_can_resume_from_checkpoint() -> None:
    spec = _fanout_join_spec()
    scheduler = _make_scheduler(spec)
    scheduler.initialize({})

    ready = scheduler.next_ready_steps(max_count=1)
    assert [step.step_id for step in ready] == ["A"]
    scheduler.mark_step_finished("A", _success("A"))

    checkpoint = scheduler_state_to_dict(scheduler.state)
    restored_state = scheduler_state_from_dict(checkpoint)
    restored = _make_scheduler(spec, state=restored_state)

    ready = restored.next_ready_steps(max_count=10)
    assert {step.step_id for step in ready} == {"B", "C"}


def test_scheduler_from_checkpoint_restores_state() -> None:
    spec = _fanout_join_spec()
    scheduler = _make_scheduler(spec)
    scheduler.initialize({})
    scheduler.next_ready_steps(max_count=1)
    scheduler.mark_step_finished("A", _success("A"))

    checkpoint = scheduler.to_checkpoint()
    compile_result = WorkflowCompiler().compile(spec)
    assert compile_result.graph is not None
    restored = WorkflowScheduler.from_checkpoint(
        workflow=spec,
        graph=compile_result.graph,
        routing_engine=RoutingEngine(),
        checkpoint=checkpoint,
    )

    ready = restored.next_ready_steps(max_count=10)
    assert {step.step_id for step in ready} == {"B", "C"}


def _make_scheduler(
    spec: WorkflowSpec,
    *,
    state=None,
) -> WorkflowScheduler:
    result = WorkflowCompiler().compile(spec)
    assert result.passed
    assert result.graph is not None
    return WorkflowScheduler(
        workflow=spec,
        graph=result.graph,
        routing_engine=RoutingEngine(),
        state=state,
    )


def _fanout_join_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="scheduler-resume",
        name="Scheduler Resume",
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
