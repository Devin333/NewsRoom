from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    identifier,
    non_negative_int,
)
from framework.harness.task_plan.checkpoint import TaskPlanCheckpoint
from framework.harness.task_plan.models import TaskInstance, TaskLifecycle, ValidatedTaskPlan
from framework.harness.task_plan.replay import TaskPlanReplayReducer, TaskPlanReplayReport
from framework.harness.task_plan.scheduler import materialize_queue_task
from framework.harness.task_plan.store import TaskPlanEvent, TaskResultRecord


@dataclass(frozen=True, slots=True)
class TaskPlanRecovery:
    """Pure recovery output; callers decide when to commit or dispatch it."""

    report: TaskPlanReplayReport
    checkpoint_verified: bool
    recovered_from_sequence: int
    missing_queue_projections: tuple[Any, ...] = ()
    awaiting_reclaim: tuple[TaskInstance, ...] = ()
    recovery_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.report, TaskPlanReplayReport):
            raise TypeError("report must be TaskPlanReplayReport")
        if not isinstance(self.checkpoint_verified, bool):
            raise TypeError("checkpoint_verified must be bool")
        object.__setattr__(
            self,
            "recovered_from_sequence",
            non_negative_int(self.recovered_from_sequence, "recovered_from_sequence"),
        )
        queue_items = tuple(self.missing_queue_projections)
        for item in queue_items:
            if getattr(item, "payload", None) != {}:
                raise HarnessValidationError(
                    "TaskPlan recovery queue projection must remain identity-only",
                    code="task_plan_recovery_queue_payload_rejected",
                )
        object.__setattr__(self, "missing_queue_projections", queue_items)
        awaiting = tuple(self.awaiting_reclaim)
        if any(not isinstance(item, TaskInstance) for item in awaiting):
            raise TypeError("awaiting_reclaim must contain TaskInstance values")
        object.__setattr__(
            self,
            "awaiting_reclaim",
            tuple(sorted(awaiting, key=lambda item: (item.task_id, item.attempt))),
        )
        object.__setattr__(
            self,
            "recovery_checksum",
            canonical_payload_checksum(self.checksum_projection()),
        )

    @property
    def pending_terminal_results(self) -> tuple[TaskResultRecord, ...]:
        return self.report.pending_terminal_results

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "replay_checksum": self.report.replay_checksum,
            "checkpoint_verified": self.checkpoint_verified,
            "recovered_from_sequence": self.recovered_from_sequence,
            "missing_queue_task_ids": [
                str(getattr(item, "task_id")) for item in self.missing_queue_projections
            ],
            "awaiting_reclaim": [item.instance_checksum for item in self.awaiting_reclaim],
            "pending_terminal_result_checksums": [
                item.result_checksum for item in self.pending_terminal_results
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "recovery_checksum": self.recovery_checksum}


class TaskPlanRecoveryService:
    """Rebuild TaskPlan state and queue projections from recorded evidence only."""

    def __init__(self, reducer: TaskPlanReplayReducer | None = None) -> None:
        self._reducer = reducer or TaskPlanReplayReducer()

    def recover(
        self,
        plans: Iterable[ValidatedTaskPlan],
        events: Iterable[TaskPlanEvent],
        *,
        results: Iterable[TaskResultRecord] = (),
        patches: Iterable[Any] = (),
        checkpoint: TaskPlanCheckpoint | None = None,
        queued_instance_ids: Iterable[str] = (),
    ) -> TaskPlanRecovery:
        plan_history = tuple(plans)
        recorded_events = tuple(events)
        recorded_results = tuple(results)
        if not plan_history:
            raise HarnessValidationError(
                "TaskPlan recovery requires accepted plan history",
                code="task_plan_recovery_plan_missing",
            )
        first_plan = plan_history[0]
        if not isinstance(first_plan, ValidatedTaskPlan):
            raise TypeError("plans must contain ValidatedTaskPlan values")
        if first_plan.is_graph_only:
            raise HarnessValidationError(
                "Graph-only TaskPlan recovery requires the queue and reclaim contract",
                code="graph_task_plan_recovery_contract_unavailable",
            )
        queued = {identifier(item, "queued_instance_ids") for item in queued_instance_ids}
        checkpoint_verified = False
        recovered_from_sequence = 0
        if checkpoint is not None:
            if not isinstance(checkpoint, TaskPlanCheckpoint):
                raise TypeError("checkpoint must be TaskPlanCheckpoint")
            checkpoint_report = self._reducer.replay(
                plan_history,
                recorded_events,
                results=recorded_results,
                patches=patches,
                through_sequence=checkpoint.last_sequence,
                require_terminal_events=False,
                apply_unterminated_results=False,
                require_latest_plan=False,
            )
            checkpoint.verify_replay(checkpoint_report)
            checkpoint_verified = True
            recovered_from_sequence = checkpoint.last_sequence

        report = self._reducer.replay(
            plan_history,
            recorded_events,
            results=recorded_results,
            patches=patches,
            require_terminal_events=False,
            apply_unterminated_results=False,
        )
        failure_sequences = tuple(
            event.sequence for event in recorded_events if event.event_type == "TASK_FAILED"
        )
        has_halt_after_failure = bool(failure_sequences) and any(
            event.event_type == "TASK_PLAN_HALTED"
            and event.sequence > max(failure_sequences)
            for event in recorded_events
        )
        has_terminal_failure = any(
            item.status is TaskLifecycle.FAILED for item in report.projection.tasks
        )
        has_actionable_task = any(
            item.status
            in {
                TaskLifecycle.PENDING,
                TaskLifecycle.READY,
                TaskLifecycle.DISPATCHED,
                TaskLifecycle.RUNNING,
            }
            for item in report.projection.tasks
        )
        if has_terminal_failure and not has_actionable_task and not has_halt_after_failure:
            raise HarnessValidationError(
                "TaskPlan terminal failure has no durable halt evidence",
                code="task_plan_recovery_halt_missing",
                details={
                    "stage_id": plan_history[-1].stage_id,
                    "plan_version": plan_history[-1].version,
                    "reason_codes": sorted(
                        {
                            item.failure_reason_code
                            for item in report.projection.tasks
                            if item.failure_reason_code is not None
                        }
                    ),
                },
            )
        states = {item.task_id: item for item in report.projection.tasks}
        pending_result_instances = {
            item.task_instance_id for item in report.pending_terminal_results
        }
        missing_queue = []
        awaiting_reclaim = []
        for instance in report.active_task_instances:
            state = states[instance.task_id]
            if instance.task_instance_id in pending_result_instances:
                continue
            if state.status is TaskLifecycle.READY:
                if instance.task_instance_id not in queued:
                    missing_queue.append(
                        materialize_queue_task(
                            instance,
                            workflow_id=plan_history[0].workflow_id,
                        )
                    )
            elif state.status in {TaskLifecycle.DISPATCHED, TaskLifecycle.RUNNING}:
                awaiting_reclaim.append(instance)
        return TaskPlanRecovery(
            report=report,
            checkpoint_verified=checkpoint_verified,
            recovered_from_sequence=recovered_from_sequence,
            missing_queue_projections=tuple(missing_queue),
            awaiting_reclaim=tuple(awaiting_reclaim),
        )


__all__ = ["TaskPlanRecovery", "TaskPlanRecoveryService"]
