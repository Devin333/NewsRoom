from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.specs import EdgeSpec, StepSpec, StepStatus, WorkflowSpec, WorkflowStatus
from framework.workflow.compiler import CompiledWorkflowGraph
from framework.workflow.runtime.result import StepOutcome as RuntimeStepOutcome
from framework.workflow.routing import RoutingEngine
from framework.workflow.runtime.state_machine import (
    StepRuntimeEvent,
    StepRuntimeEventType,
    StepStateMachine,
    WorkflowStateMachine,
)


class WorkflowScheduleError(RuntimeError):
    """Raised when workflow scheduling cannot proceed safely."""


@dataclass(frozen=True)
class ScheduledStep:
    step_id: str
    reason: str
    upstream_step_ids: list[str]
    attempt: int = 1


class StepOutcomeStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    PAUSED = "paused"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StepOutcome:
    step_id: str
    status: StepOutcomeStatus
    output_keys: set[str] = field(default_factory=set)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", StepOutcomeStatus(self.status))
        object.__setattr__(self, "output_keys", {str(key) for key in self.output_keys})


class JoinPolicy(StrEnum):
    ALL_SUCCESS = "all_success"
    ANY_SUCCESS = "any_success"
    BEST_EFFORT = "best_effort"
    QUORUM = "quorum"


@dataclass
class BranchGroupState:
    group_id: str
    source_step_id: str
    branch_step_ids: set[str]
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)


@dataclass
class SchedulerState:
    ready_queue: list[ScheduledStep] = field(default_factory=list)
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    blocked: set[str] = field(default_factory=set)
    paused: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    running: set[str] = field(default_factory=set)
    visit_counts: dict[str, int] = field(default_factory=dict)
    branch_groups: dict[str, BranchGroupState] = field(default_factory=dict)
    step_statuses: dict[str, StepStatus] = field(default_factory=dict)


class WorkflowScheduler:
    def __init__(
        self,
        *,
        workflow: WorkflowSpec,
        graph: CompiledWorkflowGraph,
        routing_engine: RoutingEngine,
        workflow_state_machine: WorkflowStateMachine | None = None,
        step_state_machine: StepStateMachine | None = None,
        state: SchedulerState | None = None,
    ) -> None:
        self.workflow = workflow
        self.graph = graph
        self.routing_engine = routing_engine
        self.workflow_state_machine = workflow_state_machine or WorkflowStateMachine()
        self.step_state_machine = step_state_machine or StepStateMachine()
        self.state = state or SchedulerState()
        self._step_by_id = {step.step_id: step for step in workflow.steps}
        self._edge_by_id = {edge.edge_id: edge for edge in workflow.edges}

    def initialize(self, request: Mapping[str, Any]) -> SchedulerState:
        del request
        start_step_id = self.workflow.start_step_id
        self.state.visit_counts.setdefault(start_step_id, 0)
        self._enqueue_once(
            ScheduledStep(
                step_id=start_step_id,
                reason="start_step",
                upstream_step_ids=[],
                attempt=1,
            )
        )
        return self.state

    def next_ready_steps(
        self,
        max_count: int = 1,
        *,
        workflow_status: WorkflowStatus = WorkflowStatus.RUNNING,
    ) -> list[ScheduledStep]:
        self.workflow_state_machine.assert_can_schedule(workflow_status)
        selected: list[ScheduledStep] = []
        limit = max(1, int(max_count))

        while self.state.ready_queue and len(selected) < limit:
            scheduled = self.state.ready_queue.pop(0)
            if scheduled.step_id in self.state.failed:
                continue
            if scheduled.step_id in self.state.blocked:
                continue
            if scheduled.step_id in self.state.paused:
                continue
            if scheduled.step_id in self.state.running:
                continue

            self._guard_max_step_visits(scheduled.step_id)
            self._transition_step_status(
                scheduled.step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.START,
                    reason="scheduler_selected_step",
                    attempt=scheduled.attempt,
                ),
                default=StepStatus.READY,
            )
            self.state.running.add(scheduled.step_id)
            selected.append(scheduled)

        return selected

    def mark_step_finished(self, step_id: str, outcome: StepOutcome) -> SchedulerState:
        if outcome.step_id != step_id:
            raise WorkflowScheduleError(
                f"outcome step_id does not match finished step: {outcome.step_id} != {step_id}"
            )

        self.state.running.discard(step_id)
        self._clear_terminal_sets(step_id)

        if outcome.status == StepOutcomeStatus.SUCCESS:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.SUCCEED,
                    reason=_outcome_reason(outcome),
                ),
            )
            self.state.completed.add(step_id)
            self._schedule_downstream_steps(step_id, outcome, reason="upstream_success")
        elif outcome.status == StepOutcomeStatus.FAILURE:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.FAIL,
                    reason=_outcome_reason(outcome),
                    error=outcome.error,
                ),
            )
            self.state.failed.add(step_id)
            self._handle_failed_or_blocked_step(step_id, outcome)
        elif outcome.status == StepOutcomeStatus.SKIPPED:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.SKIP,
                    reason=_outcome_reason(outcome),
                ),
            )
            self.state.skipped.add(step_id)
            self._schedule_downstream_steps(step_id, outcome, reason="upstream_skipped")
        elif outcome.status == StepOutcomeStatus.PAUSED:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.PAUSE,
                    reason=_outcome_reason(outcome),
                    checkpoint_id=_outcome_checkpoint_id(outcome),
                ),
            )
            self.state.paused.add(step_id)
        elif outcome.status == StepOutcomeStatus.BLOCKED:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.BLOCK,
                    reason=_outcome_reason(outcome),
                    error=outcome.error,
                ),
            )
            self.state.blocked.add(step_id)
            self._handle_failed_or_blocked_step(step_id, outcome)

        return self.state

    def should_join_run(self, join_step_id: str) -> bool:
        upstream_step_ids = set(self.graph.reverse_adjacency.get(join_step_id, []))
        if not upstream_step_ids:
            return True

        policy = self._get_join_policy(join_step_id)
        completed = upstream_step_ids & self.state.completed
        failed = upstream_step_ids & self.state.failed
        skipped = upstream_step_ids & self.state.skipped
        blocked = upstream_step_ids & self.state.blocked
        finished = completed | failed | skipped | blocked

        if policy == JoinPolicy.ALL_SUCCESS:
            return self._should_join_all_success(
                join_step_id,
                upstream_step_ids,
                completed,
                failed,
                blocked,
            )
        if policy == JoinPolicy.ANY_SUCCESS:
            return self._should_join_any_success(
                join_step_id,
                upstream_step_ids,
                completed,
                finished,
            )
        if policy == JoinPolicy.BEST_EFFORT:
            return self._should_join_best_effort(
                join_step_id,
                upstream_step_ids,
                completed,
                finished,
            )
        if policy == JoinPolicy.QUORUM:
            return self._should_join_quorum(
                join_step_id,
                upstream_step_ids,
                completed,
                finished,
            )

        return False

    def is_terminal(self) -> bool:
        if self.state.ready_queue:
            return False
        if self.state.running:
            return False

        terminal_step_ids = set(self.workflow.terminal_step_ids)
        if terminal_step_ids & self.state.completed:
            return True

        finished = (
            self.state.completed
            | self.state.failed
            | self.state.blocked
            | self.state.skipped
        )
        return set(self.graph.reachable_step_ids) <= finished

    def to_checkpoint(self) -> dict[str, Any]:
        return scheduler_state_to_dict(self.state)

    @classmethod
    def from_checkpoint(
        cls,
        *,
        workflow: WorkflowSpec,
        graph: CompiledWorkflowGraph,
        routing_engine: RoutingEngine,
        checkpoint: Mapping[str, Any],
    ) -> WorkflowScheduler:
        return cls(
            workflow=workflow,
            graph=graph,
            routing_engine=routing_engine,
            state=scheduler_state_from_dict(checkpoint),
        )

    def _step(self, step_id: str) -> StepSpec:
        try:
            return self._step_by_id[step_id]
        except KeyError as exc:
            raise WorkflowScheduleError(f"unknown step_id: {step_id}") from exc

    def _outgoing_edges(self, step_id: str) -> list[EdgeSpec]:
        return sorted(
            [edge for edge in self.workflow.edges if edge.source_step_id == step_id],
            key=lambda edge: (edge.priority, edge.edge_id),
        )

    def _incoming_edges(self, step_id: str) -> list[EdgeSpec]:
        return sorted(
            [edge for edge in self.workflow.edges if edge.target_step_id == step_id],
            key=lambda edge: (edge.priority, edge.edge_id),
        )

    def _get_upstream_step_ids(self, step_id: str) -> list[str]:
        return list(self.graph.reverse_adjacency.get(step_id, []))

    def _get_downstream_step_ids(self, step_id: str) -> list[str]:
        return list(self.graph.adjacency.get(step_id, []))

    def _is_join_step(self, step_id: str) -> bool:
        return len(self.graph.reverse_adjacency.get(step_id, [])) > 1

    def _get_join_policy(self, step_id: str) -> JoinPolicy:
        step = self._step(step_id)
        raw = getattr(step, "join_policy", None)
        if raw is None:
            raw = step.metadata.get("join_policy", JoinPolicy.ALL_SUCCESS.value)
        try:
            return JoinPolicy(str(raw))
        except ValueError as exc:
            raise WorkflowScheduleError(
                f"unsupported join_policy for step {step_id}: {raw}"
            ) from exc

    def _enqueue_once(self, scheduled: ScheduledStep) -> None:
        step_id = scheduled.step_id
        if step_id in self.state.failed:
            return
        if step_id in self.state.blocked:
            return
        if step_id in self.state.paused:
            return
        if step_id in self.state.running:
            return
        if any(item.step_id == step_id for item in self.state.ready_queue):
            return
        current = self.state.step_statuses.get(step_id, StepStatus.PENDING)
        if current != StepStatus.READY:
            self._transition_step_status(
                step_id,
                StepRuntimeEvent(
                    event_type=StepRuntimeEventType.SCHEDULE,
                    reason=scheduled.reason,
                    attempt=scheduled.attempt,
                ),
                default=StepStatus.PENDING,
            )
        self.state.ready_queue.append(scheduled)

    def _resolve_outgoing_edges(self, step_id: str, outcome: StepOutcome) -> list[EdgeSpec]:
        current_step = self._step(step_id)
        runtime_outcome = _to_runtime_outcome(outcome)
        target_step_ids = self.routing_engine.next_steps(
            self.workflow,
            current_step,
            runtime_outcome,
        )
        target_set = set(target_step_ids)
        return [
            edge
            for edge in self._outgoing_edges(step_id)
            if edge.target_step_id in target_set
        ]

    def _guard_max_step_visits(self, step_id: str) -> None:
        max_visits = getattr(self.workflow, "max_step_visits", None)
        if max_visits is None:
            return

        current = self.state.visit_counts.get(step_id, 0)
        if current >= max_visits:
            self._mark_blocked(step_id, force=True)
            raise WorkflowScheduleError(
                f"Step exceeded max_step_visits: {step_id}, max={max_visits}"
            )
        self.state.visit_counts[step_id] = current + 1

    def _schedule_downstream_steps(
        self,
        step_id: str,
        outcome: StepOutcome,
        *,
        reason: str,
    ) -> None:
        edges = self._resolve_outgoing_edges(step_id, outcome)
        for edge in edges:
            target_step_id = edge.target_step_id
            if self._is_join_step(target_step_id):
                if self.should_join_run(target_step_id):
                    self._enqueue_once(
                        ScheduledStep(
                            step_id=target_step_id,
                            reason=self._join_ready_reason(target_step_id),
                            upstream_step_ids=self._get_upstream_step_ids(target_step_id),
                        )
                    )
                continue

            self._enqueue_once(
                ScheduledStep(
                    step_id=target_step_id,
                    reason=reason,
                    upstream_step_ids=[step_id],
                )
            )

    def _handle_failed_or_blocked_step(self, step_id: str, outcome: StepOutcome) -> None:
        routed_targets = set()
        for edge in self._resolve_outgoing_edges(step_id, outcome):
            routed_targets.add(edge.target_step_id)
            if self._is_join_step(edge.target_step_id):
                if self.should_join_run(edge.target_step_id):
                    self._enqueue_once(
                        ScheduledStep(
                            step_id=edge.target_step_id,
                            reason=self._join_ready_reason(edge.target_step_id),
                            upstream_step_ids=self._get_upstream_step_ids(edge.target_step_id),
                        )
                    )
                continue
            self._enqueue_once(
                ScheduledStep(
                    step_id=edge.target_step_id,
                    reason="upstream_failure",
                    upstream_step_ids=[step_id],
                )
            )

        for downstream_step_id in self._get_downstream_step_ids(step_id):
            if downstream_step_id in routed_targets:
                continue
            if self._is_join_step(downstream_step_id):
                if self.should_join_run(downstream_step_id):
                    self._enqueue_once(
                        ScheduledStep(
                            step_id=downstream_step_id,
                            reason=self._join_ready_reason(downstream_step_id),
                            upstream_step_ids=self._get_upstream_step_ids(downstream_step_id),
                        )
                    )
                continue
            self._block_descendants_if_needed(downstream_step_id)

    def _block_descendants_if_needed(self, step_id: str) -> None:
        if step_id in self.state.completed:
            return
        if step_id in self.state.blocked:
            return
        if step_id in self.state.failed:
            return

        self._mark_blocked(step_id)

        for downstream_step_id in self._get_downstream_step_ids(step_id):
            if self._is_join_step(downstream_step_id):
                if self.should_join_run(downstream_step_id):
                    self._enqueue_once(
                        ScheduledStep(
                            step_id=downstream_step_id,
                            reason=self._join_ready_reason(downstream_step_id),
                            upstream_step_ids=self._get_upstream_step_ids(downstream_step_id),
                        )
                    )
                continue
            self._block_descendants_if_needed(downstream_step_id)

    def _join_ready_reason(self, step_id: str) -> str:
        policy = self._get_join_policy(step_id)
        if policy == JoinPolicy.ALL_SUCCESS:
            return "join_all_success"
        if policy == JoinPolicy.BEST_EFFORT:
            return "join_best_effort"
        if policy == JoinPolicy.QUORUM:
            return "join_quorum"
        return "join_any_success"

    def _should_join_all_success(
        self,
        join_step_id: str,
        upstream_step_ids: set[str],
        completed: set[str],
        failed: set[str],
        blocked: set[str],
    ) -> bool:
        if failed or blocked:
            self._mark_blocked(join_step_id)
            self._remove_ready_step(join_step_id)
            return False
        return upstream_step_ids <= completed

    def _should_join_any_success(
        self,
        join_step_id: str,
        upstream_step_ids: set[str],
        completed: set[str],
        finished: set[str],
    ) -> bool:
        if completed:
            return True
        if upstream_step_ids <= finished:
            self._mark_blocked(join_step_id)
            self._remove_ready_step(join_step_id)
        return False

    def _should_join_best_effort(
        self,
        join_step_id: str,
        upstream_step_ids: set[str],
        completed: set[str],
        finished: set[str],
    ) -> bool:
        if not upstream_step_ids <= finished:
            return False
        if completed:
            return True
        self._mark_blocked(join_step_id)
        self._remove_ready_step(join_step_id)
        return False

    def _should_join_quorum(
        self,
        join_step_id: str,
        upstream_step_ids: set[str],
        completed: set[str],
        finished: set[str],
    ) -> bool:
        step = self._step(join_step_id)
        quorum = getattr(step, "join_quorum", None)
        if quorum is None:
            quorum = step.metadata.get("join_quorum")
        if quorum is None:
            raise WorkflowScheduleError(
                f"join_policy=quorum requires join_quorum: {join_step_id}"
            )
        if len(completed) >= int(quorum):
            return True
        if upstream_step_ids <= finished:
            self._mark_blocked(join_step_id)
            self._remove_ready_step(join_step_id)
        return False

    def _remove_ready_step(self, step_id: str) -> None:
        self.state.ready_queue = [
            scheduled
            for scheduled in self.state.ready_queue
            if scheduled.step_id != step_id
        ]

    def _clear_terminal_sets(self, step_id: str) -> None:
        self.state.completed.discard(step_id)
        self.state.failed.discard(step_id)
        self.state.blocked.discard(step_id)
        self.state.paused.discard(step_id)
        self.state.skipped.discard(step_id)

    def _mark_blocked(self, step_id: str, *, force: bool = False) -> None:
        if step_id in self.state.completed and not force:
            return
        if force:
            self.state.completed.discard(step_id)
            self.state.failed.discard(step_id)
            self.state.paused.discard(step_id)
            self.state.skipped.discard(step_id)
        self.state.blocked.add(step_id)
        self.state.step_statuses[step_id] = StepStatus.BLOCKED
        self._remove_ready_step(step_id)

    def _transition_step_status(
        self,
        step_id: str,
        event: StepRuntimeEvent,
        *,
        default: StepStatus = StepStatus.RUNNING,
    ) -> StepStatus:
        current = self.state.step_statuses.get(step_id, default)
        next_status = self.step_state_machine.transition(
            current,
            event,
            step_id=step_id,
        )
        self.state.step_statuses[step_id] = next_status
        return next_status


def scheduler_state_to_dict(state: SchedulerState) -> dict[str, Any]:
    return {
        "ready_queue": [
            {
                "step_id": item.step_id,
                "reason": item.reason,
                "upstream_step_ids": list(item.upstream_step_ids),
                "attempt": item.attempt,
            }
            for item in state.ready_queue
        ],
        "completed": sorted(state.completed),
        "failed": sorted(state.failed),
        "blocked": sorted(state.blocked),
        "paused": sorted(state.paused),
        "skipped": sorted(state.skipped),
        "running": sorted(state.running),
        "visit_counts": dict(state.visit_counts),
        "branch_groups": {
            group_id: {
                "group_id": group.group_id,
                "source_step_id": group.source_step_id,
                "branch_step_ids": sorted(group.branch_step_ids),
                "completed": sorted(group.completed),
                "failed": sorted(group.failed),
                "skipped": sorted(group.skipped),
                "blocked": sorted(group.blocked),
            }
            for group_id, group in state.branch_groups.items()
        },
        "step_statuses": {
            step_id: status.value
            for step_id, status in sorted(state.step_statuses.items())
        },
    }


def scheduler_state_from_dict(data: Mapping[str, Any]) -> SchedulerState:
    branch_groups: dict[str, BranchGroupState] = {}
    for group_id, raw_group in (data.get("branch_groups") or {}).items():
        group_data = dict(raw_group)
        branch_groups[str(group_id)] = BranchGroupState(
            group_id=str(group_data.get("group_id", group_id)),
            source_step_id=str(group_data["source_step_id"]),
            branch_step_ids={str(item) for item in group_data.get("branch_step_ids", [])},
            completed={str(item) for item in group_data.get("completed", [])},
            failed={str(item) for item in group_data.get("failed", [])},
            skipped={str(item) for item in group_data.get("skipped", [])},
            blocked={str(item) for item in group_data.get("blocked", [])},
        )

    return SchedulerState(
        ready_queue=[
            ScheduledStep(
                step_id=str(item["step_id"]),
                reason=str(item["reason"]),
                upstream_step_ids=[str(step_id) for step_id in item.get("upstream_step_ids", [])],
                attempt=int(item.get("attempt", 1)),
            )
            for item in data.get("ready_queue", [])
        ],
        completed={str(item) for item in data.get("completed", [])},
        failed={str(item) for item in data.get("failed", [])},
        blocked={str(item) for item in data.get("blocked", [])},
        paused={str(item) for item in data.get("paused", [])},
        skipped={str(item) for item in data.get("skipped", [])},
        running={str(item) for item in data.get("running", [])},
        visit_counts={
            str(step_id): int(count)
            for step_id, count in dict(data.get("visit_counts", {})).items()
        },
        branch_groups=branch_groups,
        step_statuses={
            str(step_id): StepStatus(str(status))
            for step_id, status in dict(data.get("step_statuses", {})).items()
        },
    )


def _to_runtime_outcome(outcome: StepOutcome) -> RuntimeStepOutcome:
    outputs = {key: True for key in outcome.output_keys}
    metadata_outputs = outcome.metadata.get("outputs")
    if isinstance(metadata_outputs, dict):
        outputs.update(metadata_outputs)

    return RuntimeStepOutcome(
        status=_runtime_status(outcome.status),
        outputs=outputs,
        error_type=str(outcome.metadata.get("error_type", "StepFailed"))
        if outcome.status in {StepOutcomeStatus.FAILURE, StepOutcomeStatus.BLOCKED}
        else None,
        error_message=outcome.error,
        error_details=dict(outcome.metadata.get("error_details") or {}),
        metrics=dict(outcome.metadata.get("metrics") or {}),
        next_hint=(
            str(outcome.metadata["next_hint"])
            if outcome.metadata.get("next_hint") is not None
            else None
        ),
    )


def _runtime_status(status: StepOutcomeStatus) -> StepStatus:
    if status == StepOutcomeStatus.SUCCESS:
        return StepStatus.SUCCEEDED
    if status == StepOutcomeStatus.FAILURE:
        return StepStatus.FAILED
    if status == StepOutcomeStatus.SKIPPED:
        return StepStatus.SKIPPED
    if status == StepOutcomeStatus.PAUSED:
        return StepStatus.PAUSED
    if status == StepOutcomeStatus.BLOCKED:
        return StepStatus.FAILED
    raise WorkflowScheduleError(f"unsupported scheduler outcome status: {status}")


def _outcome_reason(outcome: StepOutcome) -> str | None:
    reason = outcome.metadata.get("reason")
    if reason is not None:
        return str(reason)
    return outcome.error


def _outcome_checkpoint_id(outcome: StepOutcome) -> str | None:
    checkpoint_id = outcome.metadata.get("checkpoint_id")
    if checkpoint_id is None:
        return None
    return str(checkpoint_id)



