from __future__ import annotations

import pytest

from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import RoutingEngine, WorkflowCompiler
from core.framework.workflow.scheduler import (
    JoinPolicy,
    StepOutcome,
    StepOutcomeStatus,
    WorkflowScheduleError,
    WorkflowScheduler,
)


def test_all_success_join_blocks_when_upstream_fails() -> None:
    scheduler = _initialized_after_branch_source(_join_spec(["B", "C"]))

    scheduler.mark_step_finished("B", _success("B"))
    scheduler.mark_step_finished("C", _failure("C"))

    assert "J" in scheduler.state.blocked
    assert not any(step.step_id == "J" for step in scheduler.state.ready_queue)


def test_best_effort_join_runs_when_some_upstream_succeeds() -> None:
    scheduler = _initialized_after_branch_source(
        _join_spec(["B", "C"], join_policy=JoinPolicy.BEST_EFFORT)
    )

    scheduler.mark_step_finished("B", _success("B"))
    scheduler.mark_step_finished("C", _failure("C"))

    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["J"]
    assert ready[0].reason == "join_best_effort"


def test_quorum_join_runs_when_success_threshold_is_met() -> None:
    scheduler = _initialized_after_branch_source(
        _join_spec(
            ["B", "C", "D"],
            join_policy=JoinPolicy.QUORUM,
            join_quorum=2,
        )
    )

    scheduler.mark_step_finished("B", _success("B"))
    scheduler.mark_step_finished("C", _failure("C"))
    assert not any(step.step_id == "J" for step in scheduler.state.ready_queue)

    scheduler.mark_step_finished("D", _success("D"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert [step.step_id for step in ready] == ["J"]
    assert ready[0].reason == "join_quorum"


def test_cycle_is_protected_by_max_step_visits() -> None:
    scheduler = _make_scheduler(_cycle_spec(max_step_visits=1))
    scheduler.initialize({})

    ready = scheduler.next_ready_steps(max_count=1)
    assert [step.step_id for step in ready] == ["A"]

    scheduler.mark_step_finished("A", _success("A"))
    ready = scheduler.next_ready_steps(max_count=1)
    assert [step.step_id for step in ready] == ["B"]

    scheduler.mark_step_finished("B", _success("B"))
    with pytest.raises(WorkflowScheduleError, match="exceeded max_step_visits"):
        scheduler.next_ready_steps(max_count=1)

    assert "A" in scheduler.state.blocked


def _initialized_after_branch_source(spec: WorkflowSpec) -> WorkflowScheduler:
    scheduler = _make_scheduler(spec)
    scheduler.initialize({})
    ready = scheduler.next_ready_steps(max_count=1)
    assert [step.step_id for step in ready] == ["A"]
    scheduler.mark_step_finished("A", _success("A"))
    ready = scheduler.next_ready_steps(max_count=10)
    assert {step.step_id for step in ready} == {
        step.step_id
        for step in spec.steps
        if step.step_id not in {"A", "J"}
    }
    return scheduler


def _make_scheduler(spec: WorkflowSpec) -> WorkflowScheduler:
    result = WorkflowCompiler().compile(spec)
    assert result.passed
    assert result.graph is not None
    return WorkflowScheduler(
        workflow=spec,
        graph=result.graph,
        routing_engine=RoutingEngine(),
    )


def _join_spec(
    branch_step_ids: list[str],
    *,
    join_policy: JoinPolicy = JoinPolicy.ALL_SUCCESS,
    join_quorum: int | None = None,
) -> WorkflowSpec:
    branch_steps = [
        StepSpec(step_id, f"test.{step_id}", read_keys=["a"], write_keys=[step_id.lower()])
        for step_id in branch_step_ids
    ]
    join_metadata: dict[str, object] = {"join_policy": join_policy.value}
    if join_quorum is not None:
        join_metadata["join_quorum"] = join_quorum

    return WorkflowSpec(
        workflow_id="scheduler-partial-join",
        name="Scheduler Partial Join",
        version="1.0",
        start_step_id="A",
        terminal_step_ids=["J"],
        steps=[
            StepSpec("A", "test.A", write_keys=["a"]),
            *branch_steps,
            StepSpec(
                "J",
                "test.J",
                read_keys=[step_id.lower() for step_id in branch_step_ids],
                write_keys=["joined"],
                metadata=join_metadata,
            ),
        ],
        edges=[
            *[EdgeSpec(f"A-{step_id}", "A", step_id) for step_id in branch_step_ids],
            *[EdgeSpec(f"{step_id}-J", step_id, "J") for step_id in branch_step_ids],
        ],
    )


def _cycle_spec(*, max_step_visits: int) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="scheduler-cycle",
        name="Scheduler Cycle",
        version="1.0",
        start_step_id="A",
        terminal_step_ids=["C"],
        max_step_visits=max_step_visits,
        steps=[
            StepSpec("A", "test.A", write_keys=["a"]),
            StepSpec("B", "test.B", read_keys=["a"], write_keys=["b"]),
            StepSpec("C", "test.C", read_keys=["b"], write_keys=["c"]),
        ],
        edges=[
            EdgeSpec("A-B", "A", "B"),
            EdgeSpec("B-A", "B", "A"),
            EdgeSpec("B-C", "B", "C"),
        ],
    )


def _success(step_id: str) -> StepOutcome:
    return StepOutcome(step_id=step_id, status=StepOutcomeStatus.SUCCESS)


def _failure(step_id: str) -> StepOutcome:
    return StepOutcome(step_id=step_id, status=StepOutcomeStatus.FAILURE)
