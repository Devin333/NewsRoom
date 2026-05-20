from __future__ import annotations

from datetime import UTC, datetime

from framework.workers import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    InMemoryApprovalStore,
    InMemoryTaskQueue,
    ScheduleSpec,
    ScheduleTriggerType,
    Scheduler,
    build_approval_resume_context,
)


def test_scheduler_tick_alias_enqueues_due_schedule() -> None:
    queue = InMemoryTaskQueue()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    scheduler = Scheduler(queue, now_fn=lambda: now)
    schedule = ScheduleSpec(
        schedule_id="sched-1",
        name="daily",
        trigger_type=ScheduleTriggerType.DATE,
        task_type="demo",
        run_at=now,
    )

    result = scheduler.tick([schedule], now=now)

    assert result.enqueued_count == 1
    assert result.enqueued[0].task.metadata["schedule_id"] == "sched-1"


def test_approval_store_prd_aliases_and_resume_context() -> None:
    store = InMemoryApprovalStore()
    request = store.create(
        ApprovalRequest(
            requested_action="ship",
            run_id="run-1",
            task_id="task-1",
        )
    )

    decided = store.decide(
        request.approval_id,
        ApprovalDecision(
            decision_type=ApprovalDecisionType.APPROVE,
            decided_by="operator",
        ),
    )
    resume = build_approval_resume_context(decided)

    assert store.get(request.approval_id).decision is not None
    assert resume.run_id == "run-1"
