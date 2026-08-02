from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import (
    canonical_payload_checksum,
    checksum,
    frozen_mapping,
    identifier,
    non_negative_int,
    reference,
    stable_text_tuple,
    thaw_mapping,
)
from framework.harness.task_plan.models import (
    TaskInstance,
    TaskLifecycle,
    TaskPlanProjection,
    TaskResultReference,
    ValidatedTaskPlan,
)
from framework.harness.task_plan.scheduler import (
    TaskPlanReadyDecision,
    TaskPlanScheduler,
    task_instance_for_attempt,
)
from framework.harness.task_plan.store import (
    TaskPlanEvent,
    TaskResultRecord,
    _projection_for_plan,
    _settle_result_budget,
)
from framework.harness.task_plan.models import PlanPatch


TASK_PLAN_REPLAY_REDUCER_VERSION = "newsroom.harness-task-plan-replay/v1"
_ACTIVE_TASK_STATES = frozenset(
    {TaskLifecycle.READY, TaskLifecycle.DISPATCHED, TaskLifecycle.RUNNING}
)
_TASK_RESULT_EVENTS = frozenset(
    {"TASK_RESULT_ACCEPTED", "TASK_RESULT_REJECTED"}
)
_TASK_TERMINAL_EVENTS = frozenset({"TASK_COMPLETED", "TASK_FAILED"})


@dataclass(frozen=True, slots=True)
class TaskPlanReplayReport:
    projection: TaskPlanProjection
    active_task_instances: tuple[TaskInstance, ...]
    ready_order: tuple[str, ...]
    accepted_output_refs: tuple[str, ...]
    pending_terminal_results: tuple[TaskResultRecord, ...]
    retry_counts: Mapping[str, int]
    replan_count: int
    event_history_checksum: str
    aggregate_ref: str | None = None
    aggregate_checksum: str | None = None
    verified: bool = True
    reducer_version: str = TASK_PLAN_REPLAY_REDUCER_VERSION
    replay_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.projection, TaskPlanProjection):
            raise TypeError("projection must be TaskPlanProjection")
        instances = tuple(self.active_task_instances)
        if any(not isinstance(item, TaskInstance) for item in instances):
            raise TypeError("active_task_instances must contain TaskInstance values")
        instance_ids = [item.task_instance_id for item in instances]
        if len(instance_ids) != len(set(instance_ids)):
            raise HarnessValidationError(
                "TaskPlan replay contains duplicate active task instances",
                code="task_plan_replay_duplicate_instance",
            )
        ready_order = tuple(identifier(item, "ready_order") for item in self.ready_order)
        if len(ready_order) != len(set(ready_order)):
            raise HarnessValidationError(
                "TaskPlan replay ready order contains duplicates",
                code="task_plan_replay_duplicate_ready_task",
            )
        active_task_ids = {item.task_id for item in instances}
        if set(ready_order) != active_task_ids:
            raise HarnessValidationError(
                "TaskPlan replay ready order does not match active task instances",
                code="task_plan_replay_ready_order_mismatch",
            )
        output_refs = tuple(sorted(reference(item, "accepted_output_refs") for item in self.accepted_output_refs))
        if len(output_refs) != len(set(output_refs)):
            raise HarnessValidationError(
                "TaskPlan replay accepted output refs contain duplicates",
                code="task_plan_replay_duplicate_output_ref",
            )
        pending_results = tuple(self.pending_terminal_results)
        if any(not isinstance(item, TaskResultRecord) for item in pending_results):
            raise TypeError("pending_terminal_results must contain TaskResultRecord values")
        pending_identities = [
            (item.task_instance_id, item.attempt, item.plan_version)
            for item in pending_results
        ]
        if len(pending_identities) != len(set(pending_identities)):
            raise HarnessValidationError(
                "TaskPlan replay contains duplicate pending terminal results",
                code="task_plan_replay_result_conflict",
            )
        retry_counts = {
            identifier(task_id, "retry_counts.task_id"): non_negative_int(count, "retry_counts.count")
            for task_id, count in self.retry_counts.items()
        }
        if self.reducer_version != TASK_PLAN_REPLAY_REDUCER_VERSION:
            raise HarnessValidationError(
                "unsupported TaskPlan replay reducer",
                code="unsupported_task_plan_replay_reducer",
                details={"reducer_version": str(self.reducer_version)},
            )
        object.__setattr__(self, "active_task_instances", instances)
        object.__setattr__(self, "ready_order", ready_order)
        object.__setattr__(self, "accepted_output_refs", output_refs)
        object.__setattr__(
            self,
            "pending_terminal_results",
            tuple(
                sorted(
                    pending_results,
                    key=lambda item: (
                        item.task_id,
                        item.attempt,
                        item.result_checksum,
                    ),
                )
            ),
        )
        object.__setattr__(self, "retry_counts", frozen_mapping(dict(sorted(retry_counts.items())), "retry_counts"))
        object.__setattr__(self, "replan_count", non_negative_int(self.replan_count, "replan_count"))
        object.__setattr__(self, "event_history_checksum", checksum(self.event_history_checksum, "event_history_checksum"))
        object.__setattr__(self, "aggregate_ref", reference(self.aggregate_ref, "aggregate_ref") if self.aggregate_ref else None)
        object.__setattr__(self, "aggregate_checksum", checksum(self.aggregate_checksum, "aggregate_checksum") if self.aggregate_checksum else None)
        if (self.aggregate_ref is None) != (self.aggregate_checksum is None):
            raise HarnessValidationError(
                "TaskPlan replay aggregate ref and checksum must be present together",
                code="task_plan_replay_aggregate_mismatch",
            )
        if not isinstance(self.verified, bool):
            raise TypeError("verified must be bool")
        object.__setattr__(self, "replay_checksum", canonical_payload_checksum(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "reducer_version": self.reducer_version,
            "projection": self.projection.to_dict(),
            "active_task_instances": [item.to_dict() for item in self.active_task_instances],
            "ready_order": list(self.ready_order),
            "accepted_output_refs": list(self.accepted_output_refs),
            "pending_terminal_results": [
                item.to_dict() for item in self.pending_terminal_results
            ],
            "retry_counts": thaw_mapping(self.retry_counts),
            "replan_count": self.replan_count,
            "event_history_checksum": self.event_history_checksum,
            "aggregate_ref": self.aggregate_ref,
            "aggregate_checksum": self.aggregate_checksum,
            "verified": self.verified,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "replay_checksum": self.replay_checksum}


class TaskPlanReplayReducer:
    """Pure reducer over recorded plans, events, and result references only."""

    def reduce(
        self,
        plan: ValidatedTaskPlan | Iterable[ValidatedTaskPlan],
        events: Iterable[TaskPlanEvent],
        *,
        results: Iterable[TaskResultRecord] = (),
        patches: Iterable[PlanPatch] = (),
        require_terminal_events: bool = False,
    ) -> TaskPlanProjection:
        plan_history = (plan,) if isinstance(plan, ValidatedTaskPlan) else tuple(plan)
        return self.replay(
            plan_history,
            events,
            results=results,
            patches=patches,
            require_terminal_events=require_terminal_events,
            apply_unterminated_results=not require_terminal_events,
        ).projection

    def replay(
        self,
        plans: Iterable[ValidatedTaskPlan],
        events: Iterable[TaskPlanEvent],
        *,
        results: Iterable[TaskResultRecord] = (),
        patches: Iterable[PlanPatch] = (),
        through_sequence: int | None = None,
        require_terminal_events: bool = True,
        apply_unterminated_results: bool = False,
        require_latest_plan: bool = True,
    ) -> TaskPlanReplayReport:
        plan_history = _validated_plan_history(plans)
        plans_by_version = {item.version: item for item in plan_history}
        ordered_events = _validated_event_prefix(
            tuple(events),
            plan_history[0],
            through_sequence=through_sequence,
        )
        results_by_attempt = _validated_results(results, plan_history)
        patches_by_checksum = _validated_patches(patches, plan_history)

        projection: TaskPlanProjection | None = None
        current_plan: ValidatedTaskPlan | None = None
        instances: dict[str, TaskInstance] = {}
        ready_sequences: dict[str, int] = {}
        pending_results: dict[tuple[str, int, int], TaskResultRecord] = {}
        retry_counts: dict[str, int] = {}
        aggregate_ref: str | None = None
        aggregate_checksum: str | None = None
        aggregate_output_refs: tuple[str, ...] = ()
        accepted_patch: tuple[TaskPlanEvent, PlanPatch] | None = None

        for event in ordered_events:
            if accepted_patch is not None and event.event_type != "PLAN_ACCEPTED":
                raise HarnessValidationError(
                    "accepted TaskPlan patch is not followed by its new plan",
                    code="task_plan_replay_patch_mismatch",
                    details={"patch_ref": accepted_patch[1].patch_checksum},
                )
            if event.event_type == "PLAN_ACCEPTED":
                accepted = _accepted_plan_for_event(event, plans_by_version)
                if current_plan is not None and accepted.version != current_plan.version + 1:
                    raise HarnessValidationError(
                        "TaskPlan replay plan versions are not monotonic",
                        code="task_plan_replay_plan_version_gap",
                        details={"previous": current_plan.version, "actual": accepted.version},
                    )
                if accepted_patch is not None:
                    patch_event, patch = accepted_patch
                    if (
                        event.sequence != patch_event.sequence + 1
                        or accepted.parent_plan_id != patch.base_plan_id
                        or accepted.source_candidate_ref != patch.patch_checksum
                        or accepted.version != patch.base_plan_version + 1
                    ):
                        raise HarnessValidationError(
                            "PLAN_ACCEPTED does not materialize the recorded patch",
                            code="task_plan_replay_patch_mismatch",
                            details={
                                "patch_ref": patch.patch_checksum,
                                "plan_version": accepted.version,
                            },
                        )
                    accepted_patch = None
                projection = _projection_for_plan(
                    accepted,
                    sequence=event.sequence,
                    previous=projection,
                )
                current_plan = accepted
                continue

            if event.event_type in {
                "PLAN_CANDIDATE_BUILT",
                "PLAN_CANDIDATE_REJECTED",
                "PLAN_VALIDATION_FAILED",
            }:
                _validate_candidate_event(event)
            elif event.event_type in {
                "PLAN_PATCH_PROPOSED",
                "PLAN_PATCH_REJECTED",
                "PLAN_PATCH_ACCEPTED",
            }:
                _validate_patch_event(event)
                patch_ref = thaw_mapping(event.payload).get("patch_ref")
                patch = patches_by_checksum.get(patch_ref)
                if patch is None:
                    raise HarnessValidationError(
                        "TaskPlan replay is missing patch evidence",
                        code="task_plan_replay_patch_missing",
                        details={"patch_ref": patch_ref},
                    )
                if (
                    event.plan_id != patch.base_plan_id
                    or event.plan_version != patch.base_plan_version
                    or event.run_id != patch.run_id
                    or event.stage_id != patch.stage_id
                ):
                    raise HarnessValidationError(
                        "TaskPlan patch event identity does not match recorded patch",
                        code="task_plan_replay_patch_mismatch",
                        details={"patch_ref": patch.patch_checksum},
                    )
                base_plan = plans_by_version.get(patch.base_plan_version)
                if base_plan is None or base_plan.plan_id != patch.base_plan_id:
                    raise HarnessValidationError(
                        "TaskPlan patch base plan evidence is unavailable",
                        code="task_plan_replay_patch_mismatch",
                        details={"patch_ref": patch.patch_checksum},
                    )
                if current_plan is None or current_plan.version != patch.base_plan_version:
                    raise HarnessValidationError(
                        "TaskPlan patch event does not target the current plan",
                        code="task_plan_replay_patch_mismatch",
                        details={"patch_ref": patch.patch_checksum},
                    )
                if event.event_type == "PLAN_PATCH_ACCEPTED":
                    if accepted_patch is not None:
                        raise HarnessValidationError(
                            "TaskPlan replay contains an unmaterialized accepted patch",
                            code="task_plan_replay_patch_mismatch",
                        )
                    if current_plan is None or current_plan.version != patch.base_plan_version:
                        raise HarnessValidationError(
                            "TaskPlan accepted patch does not target the current plan",
                            code="task_plan_replay_patch_mismatch",
                        )
                    accepted_patch = (event, patch)
            elif event.event_type in {
                "TASK_READY",
                "TASK_DISPATCHED",
                "TASK_STARTED",
            }:
                projection = _require_projection(projection, event)
                task_plan = _task_plan_for_event(event, plans_by_version)
                instance = _instance_for_event(event, task_plan)
                _require_projection_task_definition(projection, instance)
                if event.event_type == "TASK_READY":
                    projection = TaskPlanScheduler().reserve_ready_tasks(
                        projection,
                        TaskPlanReadyDecision((instance,)),
                    )
                    ready_sequences[instance.task_instance_id] = event.sequence
                    instances[instance.task_instance_id] = instance
                elif event.event_type == "TASK_DISPATCHED":
                    _require_recorded_instance(instances, instance, event)
                    projection = TaskPlanScheduler.mark_dispatched(projection, instance)
                else:
                    _require_recorded_instance(instances, instance, event)
                    projection = TaskPlanScheduler.mark_started(projection, instance)
            elif event.event_type in _TASK_RESULT_EVENTS:
                projection = _require_projection(projection, event)
                task_plan = _task_plan_for_event(event, plans_by_version)
                instance = _instance_for_event(event, task_plan)
                _require_recorded_instance(instances, instance, event)
                result = _result_for_event(event, results_by_attempt, task_plan)
                pending_results[(instance.task_instance_id, instance.attempt, task_plan.version)] = result
            elif event.event_type in _TASK_TERMINAL_EVENTS:
                projection = _require_projection(projection, event)
                task_plan = _task_plan_for_event(event, plans_by_version)
                instance = _instance_for_event(event, task_plan)
                _require_recorded_instance(instances, instance, event)
                result = pending_results.pop(
                    (instance.task_instance_id, instance.attempt, task_plan.version),
                    None,
                )
                if result is None:
                    raise HarnessValidationError(
                        "TaskPlan terminal event is missing committed result evidence",
                        code="task_plan_replay_result_missing",
                        details={"task_id": instance.task_id, "event_type": event.event_type},
                    )
                projection = _apply_terminal_result(
                    projection,
                    event,
                    result,
                    plan=task_plan,
                )
                ready_sequences.pop(instance.task_instance_id, None)
            elif event.event_type == "TASK_RETRY_SCHEDULED":
                projection = _require_projection(projection, event)
                task_plan = _task_plan_for_event(event, plans_by_version)
                instance = _instance_for_event(event, task_plan)
                projection = _schedule_retry(projection, event, instance)
                ready_sequences.pop(instance.task_instance_id, None)
                retry_counts[instance.task_id] = retry_counts.get(instance.task_id, 0) + 1
            elif event.event_type in {"TASK_BLOCKED", "TASK_SKIPPED"}:
                projection = _require_projection(projection, event)
                projection = _apply_non_result_terminal(projection, event)
            elif event.event_type == "STAGE_OUTPUT_AGGREGATED":
                projection = _require_projection(projection, event)
                if (
                    event.plan_id != projection.plan_id
                    or event.plan_version != projection.plan_version
                ):
                    raise HarnessValidationError(
                        "TaskPlan aggregation event references a stale plan",
                        code="task_plan_replay_aggregate_mismatch",
                    )
                (
                    aggregate_ref,
                    aggregate_checksum,
                    aggregate_output_refs,
                    _aggregate_result_refs,
                    _aggregate_branch_refs,
                ) = _aggregate_for_event(event)
            elif event.event_type == "TASK_PLAN_VERIFIED":
                projection = _require_projection(projection, event)
                if (
                    event.plan_id != projection.plan_id
                    or event.plan_version != projection.plan_version
                    or aggregate_checksum is None
                    or event.input_checksum != aggregate_checksum
                ):
                    raise HarnessValidationError(
                        "TaskPlan verification is missing matching aggregate evidence",
                        code="task_plan_replay_aggregate_mismatch",
                    )
                if tuple(event.output_refs) != aggregate_output_refs:
                    raise HarnessValidationError(
                        "TaskPlan verification output refs do not match aggregation",
                        code="task_plan_replay_aggregate_mismatch",
                    )
            elif event.event_type != "TASK_PLAN_HALTED":
                raise HarnessValidationError(
                    "TaskPlan replay encountered an unsupported event",
                    code="task_plan_replay_unknown_event",
                    details={"event_type": event.event_type},
                )

            if projection is not None:
                projection = replace(projection, last_sequence=event.sequence)

        if projection is None or current_plan is None:
            raise HarnessValidationError(
                "TaskPlan replay history has no accepted plan",
                code="task_plan_replay_plan_missing",
            )
        if require_latest_plan and current_plan.version != plan_history[-1].version:
            raise HarnessValidationError(
                "TaskPlan replay history is missing the latest accepted plan",
                code="task_plan_replay_plan_missing",
                details={"expected_version": plan_history[-1].version, "actual_version": current_plan.version},
            )
        if accepted_patch is not None:
            raise HarnessValidationError(
                "TaskPlan replay ends before the accepted patch plan",
                code="task_plan_replay_patch_mismatch",
            )
        pending_report: tuple[TaskResultRecord, ...] = ()
        if pending_results:
            if require_terminal_events:
                raise HarnessValidationError(
                    "TaskPlan replay history ends before a result terminal event",
                    code="task_plan_replay_terminal_event_missing",
                    details={"task_instance_ids": sorted({key[0] for key in pending_results})},
                )
            if apply_unterminated_results:
                projection = _apply_legacy_pending_results(
                    projection,
                    pending_results.values(),
                    plan=current_plan,
                )
                for result in pending_results.values():
                    ready_sequences.pop(result.task_instance_id, None)
            else:
                pending_report = tuple(pending_results.values())

        active_states = {
            item.active_instance_id: item
            for item in projection.tasks
            if item.status in _ACTIVE_TASK_STATES and item.active_instance_id is not None
        }
        missing_instances = sorted(set(active_states) - set(instances))
        if missing_instances:
            raise HarnessValidationError(
                "TaskPlan replay projection is missing active attempt evidence",
                code="task_plan_replay_attempt_missing",
                details={"task_instance_ids": missing_instances},
            )
        active_instances = tuple(
            instances[instance_id]
            for instance_id in sorted(
                active_states,
                key=lambda instance_id: (
                    ready_sequences.get(instance_id, 2**63 - 1),
                    active_states[instance_id].task_id,
                    instance_id,
                ),
            )
        )
        ready_order = tuple(item.task_id for item in active_instances)
        accepted_output_refs = tuple(
            sorted(
                item.result.result_ref
                for item in projection.tasks
                if item.status is TaskLifecycle.SUCCEEDED and item.result is not None
            )
        )
        history_checksum = canonical_payload_checksum(
            {"event_checksums": [event.event_checksum for event in ordered_events]}
        )
        return TaskPlanReplayReport(
            projection=projection,
            active_task_instances=active_instances,
            ready_order=ready_order,
            accepted_output_refs=accepted_output_refs,
            pending_terminal_results=pending_report,
            retry_counts=retry_counts,
            replan_count=max(current_plan.version - 1, 0),
            event_history_checksum=history_checksum,
            aggregate_ref=aggregate_ref,
            aggregate_checksum=aggregate_checksum,
        )

    def decision_checksum(self, projection: TaskPlanProjection) -> str:
        return canonical_payload_checksum(projection.checksum_projection())


def _validated_plan_history(plans: Iterable[ValidatedTaskPlan]) -> tuple[ValidatedTaskPlan, ...]:
    history = tuple(plans)
    if not history or any(not isinstance(item, ValidatedTaskPlan) for item in history):
        raise HarnessValidationError(
            "TaskPlan replay requires accepted plan history",
            code="task_plan_replay_plan_missing",
        )
    ordered = tuple(sorted(history, key=lambda item: item.version))
    versions = [item.version for item in ordered]
    if versions != list(range(1, len(ordered) + 1)):
        raise HarnessValidationError(
            "TaskPlan replay plan history is not contiguous",
            code="task_plan_replay_plan_version_gap",
            details={"versions": versions},
        )
    first = ordered[0]
    for index, plan in enumerate(ordered):
        if (
            plan.run_id != first.run_id
            or plan.workflow_id != first.workflow_id
            or plan.stage_id != first.stage_id
            or plan.graph_checksum != first.graph_checksum
            or plan.policy_ref != first.policy_ref
            or plan.policy_checksum != first.policy_checksum
        ):
            raise HarnessValidationError(
                "TaskPlan replay plan history has incompatible pinned identity",
                code="task_plan_replay_identity_mismatch",
            )
        expected_parent = None if index == 0 else ordered[index - 1].plan_id
        if plan.parent_plan_id != expected_parent:
            raise HarnessValidationError(
                "TaskPlan replay plan parent history is invalid",
                code="task_plan_replay_plan_parent_mismatch",
                details={"plan_version": plan.version},
            )
    return ordered


def _validated_event_prefix(
    events: tuple[TaskPlanEvent, ...],
    identity: ValidatedTaskPlan,
    *,
    through_sequence: int | None,
) -> tuple[TaskPlanEvent, ...]:
    if through_sequence is not None:
        through_sequence = non_negative_int(through_sequence, "through_sequence")
        if through_sequence == 0:
            raise HarnessValidationError(
                "TaskPlan replay sequence must include an accepted plan",
                code="task_plan_replay_plan_missing",
            )
    ordered = tuple(event for event in events if through_sequence is None or event.sequence <= through_sequence)
    if through_sequence is not None and (not ordered or ordered[-1].sequence != through_sequence):
        raise HarnessValidationError(
            "TaskPlan replay history does not reach the requested sequence",
            code="task_plan_replay_sequence_gap",
            details={"through_sequence": through_sequence},
        )
    for expected_sequence, event in enumerate(ordered, start=1):
        if not isinstance(event, TaskPlanEvent):
            raise TypeError("events must contain TaskPlanEvent values")
        if event.sequence != expected_sequence:
            raise HarnessValidationError(
                "TaskPlan event sequence is not contiguous",
                code="task_plan_replay_sequence_gap",
                details={"expected": expected_sequence, "actual": event.sequence},
            )
        expected_checksum = canonical_payload_checksum(event.to_dict(include_checksum=False))
        if event.event_checksum != expected_checksum:
            raise HarnessValidationError(
                "TaskPlan event checksum does not match recorded content",
                code="task_plan_replay_event_checksum_mismatch",
                details={"sequence": event.sequence},
            )
        if (
            event.run_id != identity.run_id
            or event.workflow_id != identity.workflow_id
            or event.stage_id != identity.stage_id
            or event.graph_checksum != identity.graph_checksum
        ):
            raise HarnessValidationError(
                "TaskPlan event identity does not match accepted plan",
                code="task_plan_replay_identity_mismatch",
                details={"sequence": event.sequence},
            )
    return ordered


def _validated_results(
    results: Iterable[TaskResultRecord],
    plans: tuple[ValidatedTaskPlan, ...],
) -> dict[tuple[str, int, int], TaskResultRecord]:
    first = plans[0]
    result_map: dict[tuple[str, int, int], TaskResultRecord] = {}
    for result in results:
        if not isinstance(result, TaskResultRecord):
            raise TypeError("results must contain TaskResultRecord values")
        expected_checksum = canonical_payload_checksum(result.checksum_projection())
        if result.result_checksum != expected_checksum:
            raise HarnessValidationError(
                "TaskPlan result checksum does not match recorded content",
                code="task_plan_replay_result_checksum_mismatch",
                details={"task_id": result.task_id},
            )
        if (
            result.run_id != first.run_id
            or result.workflow_id != first.workflow_id
            or result.stage_id != first.stage_id
        ):
            raise HarnessValidationError(
                "TaskPlan result identity does not match plan history",
                code="task_plan_replay_result_mismatch",
            )
        key = (result.task_instance_id, result.attempt, result.plan_version)
        existing = result_map.get(key)
        if existing is not None and existing.result_checksum != result.result_checksum:
            raise HarnessValidationError(
                "TaskPlan replay contains conflicting duplicate results",
                code="task_plan_replay_result_conflict",
                details={"task_instance_id": result.task_instance_id},
            )
        result_map[key] = result
    return result_map


def _validated_patches(
    patches: Iterable[PlanPatch],
    plans: tuple[ValidatedTaskPlan, ...],
) -> dict[str, PlanPatch]:
    first = plans[0]
    values: dict[str, PlanPatch] = {}
    for patch in patches:
        if not isinstance(patch, PlanPatch):
            raise TypeError("patches must contain PlanPatch values")
        expected_checksum = canonical_payload_checksum(patch.checksum_projection())
        if patch.patch_checksum != expected_checksum:
            raise HarnessValidationError(
                "TaskPlan patch checksum does not match recorded content",
                code="task_plan_replay_patch_checksum_mismatch",
                details={"patch_id": patch.patch_id},
            )
        if (
            patch.run_id != first.run_id
            or patch.stage_id != first.stage_id
            or patch.base_plan_version < 1
        ):
            raise HarnessValidationError(
                "TaskPlan patch identity does not match plan history",
                code="task_plan_replay_patch_mismatch",
            )
        existing = values.get(patch.patch_checksum)
        if existing is not None and existing != patch:
            raise HarnessValidationError(
                "TaskPlan replay contains conflicting patch evidence",
                code="task_plan_replay_patch_mismatch",
            )
        values[patch.patch_checksum] = patch
    return values


def _accepted_plan_for_event(
    event: TaskPlanEvent,
    plans_by_version: Mapping[int, ValidatedTaskPlan],
) -> ValidatedTaskPlan:
    if event.plan_version is None:
        raise HarnessValidationError(
            "PLAN_ACCEPTED is missing plan version",
            code="task_plan_replay_plan_missing",
        )
    plan = plans_by_version.get(event.plan_version)
    if plan is None:
        raise HarnessValidationError(
            "PLAN_ACCEPTED references unavailable plan evidence",
            code="task_plan_replay_plan_missing",
            details={"plan_version": event.plan_version},
        )
    payload = thaw_mapping(event.payload)
    if (
        event.plan_id != plan.plan_id
        or event.input_checksum != plan.plan_checksum
        or payload.get("plan_ref") != plan.plan_checksum
        or payload.get("policy_ref") != plan.policy_ref
        or (
            payload.get("policy_checksum") is not None
            and payload.get("policy_checksum") != plan.policy_checksum
        )
    ):
        raise HarnessValidationError(
            "PLAN_ACCEPTED evidence does not match recorded plan",
            code="task_plan_replay_plan_checksum_mismatch",
            details={"plan_version": plan.version},
        )
    return plan


def _validate_candidate_event(event: TaskPlanEvent) -> None:
    payload = thaw_mapping(event.payload)
    candidate_ref = payload.get("candidate_ref")
    if candidate_ref is not None and candidate_ref != event.input_checksum:
        raise HarnessValidationError(
            "TaskPlan candidate event reference does not match checksum",
            code="task_plan_replay_candidate_mismatch",
            details={"sequence": event.sequence},
        )


def _validate_patch_event(event: TaskPlanEvent) -> None:
    payload = thaw_mapping(event.payload)
    patch_ref = payload.get("patch_ref")
    if not isinstance(patch_ref, str) or patch_ref != event.input_checksum:
        raise HarnessValidationError(
            "TaskPlan patch event is missing matching patch evidence",
            code="task_plan_replay_patch_mismatch",
            details={"sequence": event.sequence},
        )


def _require_projection(
    projection: TaskPlanProjection | None,
    event: TaskPlanEvent,
) -> TaskPlanProjection:
    if projection is None:
        raise HarnessValidationError(
            "TaskPlan lifecycle event precedes plan acceptance",
            code="task_plan_replay_plan_missing",
            details={"event_type": event.event_type, "sequence": event.sequence},
        )
    return projection


def _task_plan_for_event(
    event: TaskPlanEvent,
    plans_by_version: Mapping[int, ValidatedTaskPlan],
) -> ValidatedTaskPlan:
    if event.plan_version is None:
        raise HarnessValidationError(
            "TaskPlan task event is missing plan version",
            code="task_plan_replay_identity_mismatch",
            details={"event_type": event.event_type},
        )
    plan = plans_by_version.get(event.plan_version)
    if plan is None or event.plan_id != plan.plan_id:
        raise HarnessValidationError(
            "TaskPlan task event references unavailable plan evidence",
            code="task_plan_replay_plan_missing",
            details={"plan_version": event.plan_version},
        )
    return plan


def _instance_for_event(event: TaskPlanEvent, plan: ValidatedTaskPlan) -> TaskInstance:
    if event.task_id is None or event.task_instance_id is None or event.attempt is None:
        raise HarnessValidationError(
            "TaskPlan lifecycle event is missing attempt identity",
            code="task_plan_replay_identity_mismatch",
            details={"event_type": event.event_type},
        )
    definition = next((item for item in plan.tasks if item.task_id == event.task_id), None)
    if definition is None:
        raise HarnessValidationError(
            "TaskPlan lifecycle event references unknown task",
            code="task_plan_replay_unknown_task",
            details={"task_id": event.task_id, "plan_version": plan.version},
        )
    if event.event_type in {"TASK_READY", "TASK_DISPATCHED", "TASK_STARTED"} and event.input_checksum != definition.task_definition_checksum:
        raise HarnessValidationError(
            "TaskPlan lifecycle event task checksum does not match accepted definition",
            code="task_plan_replay_task_checksum_mismatch",
            details={"task_id": event.task_id},
        )
    return task_instance_for_attempt(
        plan,
        event.task_id,
        event.attempt,
        task_instance_id=event.task_instance_id,
    )


def _require_projection_task_definition(
    projection: TaskPlanProjection,
    instance: TaskInstance,
) -> None:
    state = next((item for item in projection.tasks if item.task_id == instance.task_id), None)
    if state is None or state.task_definition_checksum != instance.task_definition_checksum:
        raise HarnessValidationError(
            "TaskPlan event task definition does not match current projection",
            code="task_plan_replay_task_checksum_mismatch",
            details={"task_id": instance.task_id},
        )


def _require_recorded_instance(
    instances: Mapping[str, TaskInstance],
    instance: TaskInstance,
    event: TaskPlanEvent,
) -> None:
    recorded = instances.get(instance.task_instance_id)
    if recorded is None or recorded.instance_checksum != instance.instance_checksum:
        raise HarnessValidationError(
            "TaskPlan lifecycle event has no matching TASK_READY evidence",
            code="task_plan_replay_attempt_missing",
            details={"task_id": instance.task_id, "event_type": event.event_type},
        )


def _result_for_event(
    event: TaskPlanEvent,
    results: Mapping[tuple[str, int, int], TaskResultRecord],
    plan: ValidatedTaskPlan,
) -> TaskResultRecord:
    assert event.task_instance_id is not None
    assert event.attempt is not None
    result = results.get((event.task_instance_id, event.attempt, plan.version))
    if result is None:
        raise HarnessValidationError(
            "TaskPlan replay is missing a recorded result",
            code="task_plan_replay_result_missing",
            details={"task_id": event.task_id},
        )
    definition = next(item for item in plan.tasks if item.task_id == result.task_id)
    payload = thaw_mapping(event.payload)
    expected_event = "TASK_RESULT_ACCEPTED" if result.status is TaskLifecycle.SUCCEEDED else "TASK_RESULT_REJECTED"
    if (
        event.event_type != expected_event
        or event.task_id != result.task_id
        or event.plan_id != result.plan_id
        or event.plan_version != result.plan_version
        or event.input_checksum != result.task_checksum
        or result.task_checksum != definition.task_definition_checksum
        or result.worker_ref != definition.worker_ref
        or result.binding_checksum != definition.binding_checksum
        or tuple(event.output_refs) != result.output_refs
        or payload.get("result_ref") != result.result_ref
        or payload.get("result_checksum") != result.result_checksum
        or tuple(payload.get("gate_refs", ())) != result.verified_gate_refs
        or tuple(payload.get("gate_evidence_refs", ())) != result.gate_evidence_refs
    ):
        raise HarnessValidationError(
            "TaskPlan result event does not match recorded result evidence",
            code="task_plan_replay_result_mismatch",
            details={"task_id": result.task_id},
        )
    return result


def _apply_terminal_result(
    projection: TaskPlanProjection,
    event: TaskPlanEvent,
    result: TaskResultRecord,
    *,
    plan: ValidatedTaskPlan,
) -> TaskPlanProjection:
    state = next((item for item in projection.tasks if item.task_id == result.task_id), None)
    if (
        state is None
        or state.active_instance_id != result.task_instance_id
        or state.attempts != result.attempt
        or state.status not in {TaskLifecycle.READY, TaskLifecycle.DISPATCHED, TaskLifecycle.RUNNING}
    ):
        raise HarnessValidationError(
            "TaskPlan terminal result does not match active projection",
            code="task_plan_replay_result_mismatch",
            details={"task_id": result.task_id},
        )
    payload = thaw_mapping(event.payload)
    if event.input_checksum not in {result.task_checksum, result.result_checksum}:
        raise HarnessValidationError(
            "TaskPlan terminal event checksum does not match result evidence",
            code="task_plan_replay_result_checksum_mismatch",
            details={"task_id": result.task_id},
        )
    payload_checksum = payload.get("result_checksum")
    if payload_checksum is not None and payload_checksum != result.result_checksum:
        raise HarnessValidationError(
            "TaskPlan terminal event result checksum is inconsistent",
            code="task_plan_replay_result_checksum_mismatch",
            details={"task_id": result.task_id},
        )
    if tuple(event.output_refs) != result.output_refs:
        raise HarnessValidationError(
            "TaskPlan terminal event output refs do not match result evidence",
            code="task_plan_replay_result_mismatch",
            details={"task_id": result.task_id},
        )
    if tuple(payload.get("gate_refs", ())) != result.verified_gate_refs or tuple(
        payload.get("gate_evidence_refs", ())
    ) != result.gate_evidence_refs:
        raise HarnessValidationError(
            "TaskPlan terminal event gate evidence does not match result evidence",
            code="task_plan_replay_result_mismatch",
            details={"task_id": result.task_id},
        )
    if event.event_type == "TASK_COMPLETED":
        if result.status is not TaskLifecycle.SUCCEEDED or not result.output_roles:
            raise HarnessValidationError(
                "TASK_COMPLETED requires successful result evidence",
                code="task_plan_replay_result_mismatch",
            )
        reference_value = TaskResultReference(
            result_ref=result.result_ref or "task-result:" + result.result_checksum,
            result_checksum=result.result_checksum,
            output_role=result.output_roles[0],
            output_schema_ref=result.output_schema_ref,
        )
        updated = replace(
            state,
            status=TaskLifecycle.SUCCEEDED,
            active_instance_id=None,
            result=reference_value,
            failure_reason_code=None,
        )
    else:
        if result.status is not TaskLifecycle.FAILED:
            raise HarnessValidationError(
                "TASK_FAILED requires failed result evidence",
                code="task_plan_replay_result_mismatch",
            )
        updated = replace(
            state,
            status=TaskLifecycle.FAILED,
            active_instance_id=result.task_instance_id,
            failure_reason_code=result.error_code or event.reason_code or "task_failed",
        )
    definition = next(
        (item for item in plan.tasks if item.task_id == result.task_id),
        None,
    )
    if definition is None:
        raise HarnessValidationError(
            "TaskPlan terminal result definition is unavailable",
            code="task_plan_replay_unknown_task",
            details={"task_id": result.task_id},
        )
    settled_budget = _settle_result_budget(
        projection.consumed_budget,
        definition,
        result,
    )
    return replace(
        projection,
        tasks=tuple(updated if item.task_id == result.task_id else item for item in projection.tasks),
        consumed_budget=settled_budget,
    )


def _schedule_retry(
    projection: TaskPlanProjection,
    event: TaskPlanEvent,
    instance: TaskInstance,
) -> TaskPlanProjection:
    state = next((item for item in projection.tasks if item.task_id == instance.task_id), None)
    if (
        state is None
        or state.status is not TaskLifecycle.FAILED
        or state.active_instance_id != instance.task_instance_id
        or state.attempts != instance.attempt
    ):
        raise HarnessValidationError(
            "TaskPlan retry event does not match failed attempt",
            code="task_plan_replay_retry_mismatch",
            details={"task_id": instance.task_id},
        )
    updated = replace(
        state,
        status=TaskLifecycle.PENDING,
        active_instance_id=None,
        failure_reason_code=None,
    )
    return replace(
        projection,
        tasks=tuple(updated if item.task_id == instance.task_id else item for item in projection.tasks),
    )


def _apply_non_result_terminal(
    projection: TaskPlanProjection,
    event: TaskPlanEvent,
) -> TaskPlanProjection:
    if event.plan_id != projection.plan_id or event.plan_version != projection.plan_version:
        raise HarnessValidationError(
            "TaskPlan terminal event references a stale plan",
            code="task_plan_replay_plan_mismatch",
        )
    if event.task_id is None:
        raise HarnessValidationError(
            "TaskPlan terminal event is missing task id",
            code="task_plan_replay_identity_mismatch",
        )
    state = next((item for item in projection.tasks if item.task_id == event.task_id), None)
    if state is None:
        raise HarnessValidationError(
            "TaskPlan terminal event references unknown task",
            code="task_plan_replay_unknown_task",
            details={"task_id": event.task_id},
        )
    target = TaskLifecycle.BLOCKED if event.event_type == "TASK_BLOCKED" else TaskLifecycle.SKIPPED
    updated = replace(
        state,
        status=target,
        active_instance_id=None,
        failure_reason_code=event.reason_code,
    )
    return replace(
        projection,
        tasks=tuple(updated if item.task_id == event.task_id else item for item in projection.tasks),
    )


def _aggregate_for_event(
    event: TaskPlanEvent,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Mapping[str, Any], ...]]:
    payload = thaw_mapping(event.payload)
    aggregate_ref = payload.get("aggregate_ref")
    aggregate_checksum = payload.get("aggregate_checksum") or event.input_checksum
    if not isinstance(aggregate_ref, str) or not isinstance(aggregate_checksum, str):
        raise HarnessValidationError(
            "TaskPlan aggregation event is missing reference evidence",
            code="task_plan_replay_aggregate_mismatch",
        )
    output_refs_by_role = payload.get("output_refs_by_role", {})
    if not isinstance(output_refs_by_role, Mapping):
        raise HarnessValidationError(
            "TaskPlan aggregation output refs must be an object",
            code="task_plan_replay_aggregate_mismatch",
        )
    projected_refs = tuple(
        sorted(output_refs_by_role[key] for key in sorted(output_refs_by_role))
    )
    if projected_refs != tuple(event.output_refs):
        raise HarnessValidationError(
            "TaskPlan aggregation event output refs are inconsistent",
            code="task_plan_replay_aggregate_mismatch",
        )
    result_refs_raw = payload.get("result_refs")
    branch_refs_raw = payload.get("branch_refs")
    if not isinstance(result_refs_raw, (list, tuple)) or not isinstance(branch_refs_raw, (list, tuple)):
        raise HarnessValidationError(
            "TaskPlan aggregation event is missing result and branch evidence",
            code="task_plan_replay_aggregate_mismatch",
        )
    try:
        result_refs = stable_text_tuple(
            result_refs_raw,
            "result_refs",
            allow_empty=False,
            item_kind="reference",
        )
        branch_refs = tuple(
            frozen_mapping(item, "branch_refs.item") for item in branch_refs_raw
        )
    except (TypeError, HarnessValidationError) as exc:
        raise HarnessValidationError(
            "TaskPlan aggregation branch evidence is invalid",
            code="task_plan_replay_aggregate_mismatch",
        ) from exc
    branch_payload = [thaw_mapping(item) for item in branch_refs]
    expected_checksum = canonical_payload_checksum(
        {
            "roles": dict(output_refs_by_role),
            "result_refs": list(result_refs),
            "branch_refs": branch_payload,
        }
    )
    if event.input_checksum != expected_checksum:
        raise HarnessValidationError(
            "TaskPlan aggregation event input checksum does not match branch evidence",
            code="task_plan_replay_aggregate_mismatch",
        )
    if checksum(aggregate_checksum, "aggregate_checksum") != expected_checksum:
        raise HarnessValidationError(
            "TaskPlan aggregation checksum does not match recorded branch evidence",
            code="task_plan_replay_aggregate_mismatch",
        )
    expected_ref = f"task-plan-aggregate:{expected_checksum}"
    if reference(aggregate_ref, "aggregate_ref") != expected_ref:
        raise HarnessValidationError(
            "TaskPlan aggregation ref is not bound to recorded branch evidence",
            code="task_plan_replay_aggregate_mismatch",
        )
    return (
        expected_ref,
        expected_checksum,
        projected_refs,
        result_refs,
        tuple(branch_refs),
    )


def _apply_legacy_pending_results(
    projection: TaskPlanProjection,
    results: Iterable[TaskResultRecord],
    *,
    plan: ValidatedTaskPlan,
) -> TaskPlanProjection:
    current = projection
    for result in sorted(results, key=lambda item: (item.task_id, item.attempt, item.result_checksum)):
        event_type = "TASK_COMPLETED" if result.status is TaskLifecycle.SUCCEEDED else "TASK_FAILED"
        event = _LegacyTerminalEvent(event_type, result)
        current = _apply_terminal_result(current, event, result, plan=plan)
    return current


class _LegacyTerminalEvent:
    def __init__(self, event_type: str, result: TaskResultRecord) -> None:
        self.event_type = event_type
        self.input_checksum = result.result_checksum
        self.reason_code = result.error_code
        self.payload = frozen_mapping(
            {"result_checksum": result.result_checksum},
            "legacy_terminal_event.payload",
        )


__all__ = [
    "TASK_PLAN_REPLAY_REDUCER_VERSION",
    "TaskPlanReplayReducer",
    "TaskPlanReplayReport",
]
