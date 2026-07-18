from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from framework.events.canonical import (
    PayloadReference,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventStoreCorruptionError
from framework.events.runtime.activities import (
    RecordedActivityResolver,
    RecordedActivityStorePort,
    ReplayActivityCorruptionError,
    ReplayActivityDescriptor,
    ReplayActivityHandlerVersion,
    ReplayActivityKind,
    ReplayActivityMissingError,
    ReplayActivityRegistry,
    ReplayActivityResolverPort,
    ResolvedReplayActivity,
)
from framework.events.runtime.history import (
    DeterministicCommand,
    DeterministicHistoryRecord,
    ExactVersionRegistration,
    ExactVersionRegistry,
    HistoryEventPolicy,
    HistoryVerifier,
)
from framework.harness.control_plane.activity import HARNESS_ACTIVITY_CONTRACT
from framework.harness.control_plane.event import HarnessEvent
from framework.harness.control_plane.decision import HarnessDecision
from framework.harness.control_plane.transition import (
    HARNESS_POLICY_VERSION,
    HARNESS_REDUCER_VERSION,
    HARNESS_TRANSITION_DATA_SCHEMA,
    HARNESS_TRANSITION_EVENT_TYPE,
    HarnessTransitionCommitted,
    workflow_checksum,
    workflow_version,
)
from framework.harness.quality.verdict import gate_result_evidence


HARNESS_HISTORY_HANDLER_ID = "harness-control-plane"
HARNESS_HISTORY_POLICY_ID = "harness-control-policy"
HARNESS_HISTORY_SCHEMA_ID = "newsroom.harness-event"
HARNESS_TRANSITION_HISTORY_SCHEMA_ID = "newsroom.harness-transition"
HARNESS_EVENT_HISTORY_WORKFLOW_ID = "harness-events"
HARNESS_EVENT_HISTORY_WORKFLOW_VERSION = "1"
HARNESS_ACTIVITY_HISTORY_WORKFLOW_ID = "harness-worker-activity"
HARNESS_DECISION_INPUT_SCHEMA = "newsroom.harness-decision-input/v1"
HARNESS_DECISION_WORKFLOW_ID = "harness-scheduler"

_ACTIVITY_KIND_BY_TYPE = {
    "artifact": ReplayActivityKind.PUBLICATION,
    "clock": ReplayActivityKind.CLOCK,
    "email": ReplayActivityKind.EMAIL,
    "external_database": ReplayActivityKind.EXTERNAL_DATABASE,
    "http": ReplayActivityKind.HTTP,
    "llm": ReplayActivityKind.LLM,
    "mcp": ReplayActivityKind.MCP,
    "memory": ReplayActivityKind.MEMORY_WRITE,
    "publication": ReplayActivityKind.PUBLICATION,
    "random": ReplayActivityKind.RANDOM,
    "retrieval": ReplayActivityKind.RETRIEVAL,
    "script": ReplayActivityKind.TOOL,
    "skill": ReplayActivityKind.TOOL,
    "skill_evolution": ReplayActivityKind.TOOL,
    "subagent": ReplayActivityKind.TOOL,
    "tool": ReplayActivityKind.TOOL,
    "quality_gate": ReplayActivityKind.TOOL,
}


def harness_decision_history(
    *,
    workflow_id: str,
    workflow_version: str,
    command_ordinal: int,
    decision_input: Mapping[str, Any],
    decision: HarnessDecision,
    causation_id: str,
    expected_activity: ReplayActivityDescriptor | None = None,
    recorded_activity_ref: PayloadReference | None = None,
) -> DeterministicHistoryRecord:
    normalized = _decision_input(decision_input)
    snapshot_activity = normalized["expected_activity"]
    policy_activity = (
        None if expected_activity is None else expected_activity.to_dict()
    )
    if snapshot_activity != policy_activity:
        raise ValueError(
            "Harness decision input activity conflicts with history policy"
        )
    if (expected_activity is None) != (recorded_activity_ref is None):
        raise ValueError(
            "Harness decision activity and recorded reference must be supplied together"
        )
    return DeterministicHistoryRecord(
        policy=HistoryEventPolicy(
            handler_id=HARNESS_HISTORY_HANDLER_ID,
            handler_version=HARNESS_REDUCER_VERSION,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            policy_id=HARNESS_HISTORY_POLICY_ID,
            policy_version=HARNESS_POLICY_VERSION,
            schema_id=HARNESS_HISTORY_SCHEMA_ID,
            schema_version="newsroom.harness-event/v1",
            expected_activity=expected_activity,
            recorded_activity_ref=recorded_activity_ref,
        ),
        handler_input=normalized,
        commands=(
            _decision_command(
                command_ordinal=command_ordinal,
                decision_input=normalized,
                decision_projection=_decision_projection(decision),
                workflow_version=workflow_version,
                causation_id=causation_id,
            ),
        ),
    )


def harness_decision_input_snapshot(
    *,
    state: Any,
    command_ordinal: int,
    causation_id: str,
    gate_results: Sequence[Any] = (),
    quality_verdict: Any | None = None,
    expected_activity: ReplayActivityDescriptor | None = None,
    approval_outcome: str | None = None,
) -> Mapping[str, Any]:
    workflow = state.run_spec.workflow
    current_step = next(
        (
            step
            for step in workflow.steps
            if step.step_id == state.current_step_id
        ),
        None,
    )
    current_policy: dict[str, Any] = {}
    if current_step is not None:
        current_policy = {
            "worker_type": current_step.worker_type.value,
            "approval_required": bool(
                current_step.metadata.get("approval_required")
            ),
            "repair_step_id": (
                current_step.retry_policy.repair_step_id
                or current_step.metadata.get("repair_step_id")
            ),
            **current_step.retry_policy.to_dict(),
        }
    routing_values: dict[str, Any] = {
        "quality_verdict.passed": (
            None if quality_verdict is None else quality_verdict.passed
        ),
        "quality_verdict.score": (
            None if quality_verdict is None else quality_verdict.score
        ),
    }
    routing_values.update(_routing_snapshot_values(state, workflow.routing_rules))
    snapshot = {
        "schema": HARNESS_DECISION_INPUT_SCHEMA,
        "command_ordinal": command_ordinal,
        "causation_id": causation_id,
        "run_id": state.run_spec.run_id,
        "workflow_id": workflow.workflow_id,
        "workflow_version": workflow_version(state.run_spec),
        "workflow_checksum": workflow_checksum(state.run_spec),
        "entry_step_id": workflow.entry_step_id,
        "step_order": workflow.step_ids,
        "current_step_policy": current_policy,
        "routing_rules": tuple(rule.to_dict() for rule in workflow.routing_rules),
        "before_state_checksum": checksum_for(state.to_dict()),
        "run_status": state.status.value,
        "current_step_id": state.current_step_id,
        "turn_count": state.turn_count,
        "replan_count": state.replan_count,
        "worker_call_count": state.worker_call_count,
        "step_states": tuple(
            {
                "step_id": step.step_id,
                "status": step.status.value,
                "attempts": step.attempts,
                "replans": step.replans,
                "approval_granted": bool(
                    step.metadata.get("approval_granted")
                ),
            }
            for step in state.step_states
        ),
        "budget": state.run_spec.budget.to_dict(),
        "gate_results": tuple(_gate_decision_evidence(result) for result in gate_results),
        "quality_verdict": (
            None if quality_verdict is None else quality_verdict.to_dict()
        ),
        "approval_outcome": approval_outcome,
        "routing_values": routing_values,
        "expected_activity": (
            None
            if expected_activity is None
            else expected_activity.to_dict()
        ),
    }
    return _decision_input(snapshot)


def _gate_decision_evidence(result: Any) -> Mapping[str, Any]:
    return gate_result_evidence(result)


def harness_event_history(event: HarnessEvent, *, data_schema: str) -> DeterministicHistoryRecord:
    if not isinstance(event, HarnessEvent):
        raise TypeError("event must be HarnessEvent")
    return DeterministicHistoryRecord(
        policy=HistoryEventPolicy(
            handler_id=HARNESS_HISTORY_HANDLER_ID,
            handler_version=HARNESS_REDUCER_VERSION,
            workflow_id=HARNESS_EVENT_HISTORY_WORKFLOW_ID,
            workflow_version=HARNESS_EVENT_HISTORY_WORKFLOW_VERSION,
            policy_id=HARNESS_HISTORY_POLICY_ID,
            policy_version=HARNESS_POLICY_VERSION,
            schema_id=HARNESS_HISTORY_SCHEMA_ID,
            schema_version=data_schema,
        ),
        commands=(),
    )


def harness_transition_history(
    transition: HarnessTransitionCommitted,
) -> DeterministicHistoryRecord:
    if not isinstance(transition, HarnessTransitionCommitted):
        raise TypeError("transition must be HarnessTransitionCommitted")
    return DeterministicHistoryRecord(
        policy=HistoryEventPolicy(
            handler_id=HARNESS_HISTORY_HANDLER_ID,
            handler_version=transition.reducer_version,
            workflow_id=transition.state.workflow_id,
            workflow_version=transition.state.workflow_version,
            policy_id=HARNESS_HISTORY_POLICY_ID,
            policy_version=transition.policy_version,
            schema_id=HARNESS_TRANSITION_HISTORY_SCHEMA_ID,
            schema_version=transition.schema_version,
        ),
        commands=(),
    )


def harness_activity_history(
    record: Any,
) -> DeterministicHistoryRecord:
    from framework.events.runtime.activities import RecordedActivityWrite

    if not isinstance(record, RecordedActivityWrite):
        raise TypeError("record must be RecordedActivityWrite")
    activity = record.record.activity
    return DeterministicHistoryRecord(
        policy=HistoryEventPolicy(
            handler_id=HARNESS_HISTORY_HANDLER_ID,
            handler_version=HARNESS_REDUCER_VERSION,
            workflow_id=HARNESS_ACTIVITY_HISTORY_WORKFLOW_ID,
            workflow_version=activity.contract_version,
            policy_id=HARNESS_HISTORY_POLICY_ID,
            policy_version=HARNESS_POLICY_VERSION,
            schema_id=HARNESS_HISTORY_SCHEMA_ID,
            schema_version="newsroom.harness-event/v1",
            expected_activity=activity,
            recorded_activity_ref=record.recorded_ref,
        ),
        commands=(),
    )


def harness_expected_commands(
    event: Any,
    handler_input: Mapping[str, Any],
    activity_result: ResolvedReplayActivity | None,
) -> tuple[DeterministicCommand, ...]:
    """Rebuild Harness decisions from accepted deterministic inputs."""

    if not handler_input:
        return ()
    decision_input = _decision_input(handler_input)
    semantic = harness_decision_kernel(decision_input, activity_result)
    return (
        _decision_command(
            command_ordinal=int(decision_input["command_ordinal"]),
            decision_input=decision_input,
            decision_projection=semantic,
            workflow_version=str(decision_input["workflow_version"]),
            causation_id=str(decision_input["causation_id"]),
        ),
    )


def harness_decision_kernel(
    decision_input: Mapping[str, Any],
    activity_result: ResolvedReplayActivity | None,
) -> Mapping[str, Any]:
    value = _decision_input(decision_input)
    status = str(value["run_status"])
    step_id = _optional_string(value.get("current_step_id"))
    run_id = str(value["run_id"])
    steps = tuple(value["step_states"])
    current = None
    for step in steps:
        if isinstance(step, Mapping) and step.get("step_id") == step_id:
            current = step
            break
    step_status = None if current is None else str(current["status"])
    budget = value["budget"]
    policy = value["current_step_policy"]
    gates = tuple(value["gate_results"])
    verdict = value.get("quality_verdict")
    worker = _resolved_worker_semantics(activity_result)
    approval_outcome = value["approval_outcome"]

    decision_type: str
    target: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = {}
    if status in {"succeeded", "failed", "halted", "cancelled"}:
        decision_type = "halt_run"
        reason = "run is already terminal: " + status
    elif status == "created":
        decision_type = "start_step"
        step_id = str(value["entry_step_id"])
        target = step_id
        reason = "start entry step"
    elif status == "waiting_approval" or step_status == "waiting_approval":
        if approval_outcome == "approved":
            decision_type = "resume_after_approval"
            reason = "Harness approval granted"
            payload = {"approval_outcome": "approved"}
        elif approval_outcome == "cancelled":
            decision_type = "cancel_run"
            reason = "Harness approval was cancelled"
            payload = {"approval_outcome": "cancelled"}
        else:
            decision_type = "wait_for_approval"
            reason = "run is waiting for Harness approval"
    elif step_status == "pending":
        decision_type = _turn_budget_decision(value) or "plan_step"
        if decision_type == "halt_run":
            reason = "turn budget is exhausted"
            payload = {"budget_exhausted": "turns"}
    elif step_status == "planning":
        failed = False
        for item in gates:
            if not bool(item["passed"]):
                failed = True
                break
        if not gates or not failed:
            decision_type = _execution_decision(value)
        elif _can_replan(value, current):
            decision_type = "replan_step"
            reason = "plan gate failed"
            payload = {"gate_results": [dict(item) for item in gates]}
        else:
            decision_type = "halt_run"
            reason = "plan gate failed and replan budget is exhausted"
            payload = {"budget_exhausted": "replans"}
    elif step_status in {"plan_verified", "retrying"}:
        decision_type = _execution_decision(value)
        if step_status == "retrying":
            reason = "retry current step"
    elif step_status == "running":
        if worker is None:
            decision_type = "execute_step"
        elif worker["status"] == "succeeded":
            if bool(policy.get("approval_required")) and not bool(
                current.get("approval_granted")
            ):
                decision_type = "wait_for_approval"
                reason = "step requires Harness approval"
            else:
                decision_type = (
                    _turn_budget_decision(value)
                    or "verify_step"
                )
        elif worker["status"] == "waiting_approval":
            decision_type = "wait_for_approval"
            reason = "worker is waiting for approval"
        elif worker["status"] == "blocked":
            decision_type = "block_run"
            reason = worker.get("error") or "worker blocked"
        elif _can_retry_worker(value, current, policy, worker):
            decision_type = "retry_step"
            reason = worker.get("error") or "worker failed with retryable status"
            payload = {"backoff_seconds": policy.get("backoff_seconds", 0.0)}
        elif policy.get("repair_step_id"):
            decision_type = "route_to_repair"
            target = str(policy["repair_step_id"])
            reason = worker.get("error") or "worker failed; route to configured repair step"
        else:
            decision_type = "fail_run"
            reason = worker.get("error") or "worker failed and retry budget is exhausted"
    elif step_status == "verifying":
        if not gates and verdict is None:
            decision_type = (
                _turn_budget_decision(value)
                or "verify_step"
            )
        elif gates and _all_gates_passed(gates) and not (
            isinstance(verdict, Mapping) and not bool(verdict["passed"])
        ):
            decision_type = "complete_step"
        elif policy.get("repair_step_id"):
            decision_type = "route_to_repair"
            target = str(policy["repair_step_id"])
            reason = "verification failed; route to repair step"
        elif _can_replan(value, current):
            decision_type = "replan_step"
            reason = "verification failed"
        else:
            decision_type = "halt_run"
            reason = "verification failed and replan budget is exhausted"
            payload = {"budget_exhausted": "replans"}
    elif step_status == "replanning":
        decision_type = (
            _turn_budget_decision(value) or "plan_step"
        )
        reason = "controlled replan"
    elif step_status == "succeeded":
        target = _selected_route(value, worker)
        if target is None:
            decision_type = "complete_run"
            reason = "workflow has no next step"
        else:
            decision_type = "route_to_step"
            reason = "explicit routing rule or workflow order selected next step"
    elif step_status == "halted":
        decision_type = "halt_run"
    elif step_status == "failed":
        decision_type = "fail_run"
    else:
        decision_type = "fail_run"
        reason = "unsupported step status: " + str(step_status)
    return {
        "decision_type": decision_type,
        "step_id": step_id,
        "target_step_id": target,
        "reason": reason,
        "payload": payload,
    }


def _decision_input(value: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = normalize_canonical_json(
        value,
        path="$.harness_decision_input",
    )
    if not isinstance(normalized, Mapping):
        raise TypeError("Harness decision input must be an object")
    required = {
        "schema",
        "command_ordinal",
        "causation_id",
        "run_id",
        "workflow_id",
        "workflow_version",
        "workflow_checksum",
        "entry_step_id",
        "step_order",
        "current_step_policy",
        "routing_rules",
        "before_state_checksum",
        "run_status",
        "current_step_id",
        "turn_count",
        "replan_count",
        "worker_call_count",
        "step_states",
        "budget",
        "gate_results",
        "quality_verdict",
        "approval_outcome",
        "routing_values",
        "expected_activity",
    }
    if set(normalized) != required:
        raise ValueError("Harness decision input fields are incomplete")
    if normalized["schema"] != HARNESS_DECISION_INPUT_SCHEMA:
        raise ValueError("unsupported Harness decision input schema")
    approval_outcome = normalized["approval_outcome"]
    if approval_outcome not in {None, "approved", "cancelled"}:
        raise ValueError("unsupported Harness approval outcome")
    if approval_outcome is not None:
        current_step_id = normalized["current_step_id"]
        current_step_status = None
        for step in normalized["step_states"]:
            if (
                isinstance(step, Mapping)
                and step.get("step_id") == current_step_id
            ):
                current_step_status = step.get("status")
                break
        if (
            normalized["run_status"] != "waiting_approval"
            and current_step_status != "waiting_approval"
        ):
            raise ValueError(
                "Harness approval outcome requires an approval-waiting state"
            )
    return normalized


def _decision_command(
    *,
    command_ordinal: int,
    decision_input: Mapping[str, Any],
    decision_projection: Mapping[str, Any],
    workflow_version: str,
    causation_id: str,
) -> DeterministicCommand:
    target = (
        decision_projection.get("target_step_id")
        or decision_projection.get("step_id")
        or "run"
    )
    return DeterministicCommand(
        ordinal=command_ordinal,
        kind=str(decision_projection["decision_type"]),
        target=target,
        handler_version=HARNESS_REDUCER_VERSION,
        workflow_version=workflow_version,
        policy_version=HARNESS_POLICY_VERSION,
        input_refs=(
            "urn:newsroom:harness-decision-input:"
            + str(command_ordinal),
        ),
        input_checksums=(checksum_for(decision_input),),
        budget_ref=checksum_for(decision_input["budget"]),
        gate_ref=checksum_for(decision_input["gate_results"]),
        decision_ref=checksum_for(
            _semantic_decision_projection(decision_projection)
        ),
        causation_id=causation_id,
    )


def _decision_projection(decision: HarnessDecision) -> dict[str, Any]:
    return _semantic_decision_projection(
        {
        "decision_type": decision.decision_type.value,
        "step_id": decision.step_id,
        "target_step_id": decision.target_step_id,
        "payload": decision.payload,
        }
    )


def _semantic_decision_projection(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    payload = value.get("payload", {})
    safe_payload: dict[str, Any] = {}
    if isinstance(payload, Mapping):
        for key in (
            "approval_outcome",
            "backoff_seconds",
            "budget_exhausted",
        ):
            if key in payload:
                safe_payload[key] = payload[key]
    return {
        "decision_type": str(value["decision_type"]),
        "step_id": value.get("step_id"),
        "target_step_id": value.get("target_step_id"),
        "payload": safe_payload,
    }


def _resolved_worker_semantics(
    activity_result: ResolvedReplayActivity | None,
) -> dict[str, Any] | None:
    if activity_result is None:
        return None
    context = thaw_canonical_json(activity_result.activity.context)
    if not isinstance(context, Mapping):
        raise ValueError("Harness replay activity context must be an object")
    outcome = activity_result.outcome
    error_class = outcome.error_class
    status = "succeeded"
    if outcome.status.value != "succeeded":
        prefix = "harness_worker_"
        status = (
            error_class.removeprefix(prefix)
            if isinstance(error_class, str) and error_class.startswith(prefix)
            else "failed"
        )
    return {
        "status": status,
        "error": None,
        "error_type": _optional_string(
            context.get("worker_error_type", error_class)
        ),
    }


def _turn_budget_decision(
    value: Mapping[str, Any],
) -> str | None:
    budget = value["budget"]
    if int(value["turn_count"]) >= int(budget["max_turns"]):
        return "halt_run"
    return None


def _all_gates_passed(gates: tuple[Any, ...]) -> bool:
    for item in gates:
        if not bool(item["passed"]):
            return False
    return True


def _execution_decision(value: Mapping[str, Any]) -> str:
    if _turn_budget_decision(value) is not None:
        return "halt_run"
    budget = value["budget"]
    if int(value["worker_call_count"]) >= int(budget["max_worker_calls"]):
        return "halt_run"
    return "execute_step"


def _can_replan(value: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    budget = value["budget"]
    return int(value["replan_count"]) < int(budget["max_replans"]) and int(
        current["replans"]
    ) < int(budget["max_replans"])


def _can_retry_worker(
    value: Mapping[str, Any],
    current: Mapping[str, Any],
    policy: Mapping[str, Any],
    worker: Mapping[str, Any],
) -> bool:
    if worker["status"] not in tuple(policy["retry_on_statuses"]):
        return False
    error_type = worker.get("error_type")
    if error_type is not None and error_type in tuple(
        policy["fail_fast_error_types"]
    ):
        return False
    allowed = min(
        int(policy["effective_max_attempts"]),
        int(value["budget"]["max_retries_per_step"]) + 1,
    )
    return int(current["attempts"]) < allowed


def _selected_route(
    value: Mapping[str, Any],
    worker: Mapping[str, Any] | None,
) -> str | None:
    current_step = _optional_string(value.get("current_step_id"))
    routing_values = dict(value["routing_values"])
    routing_values["worker_result.status"] = (
        None if worker is None else worker.get("status")
    )
    for rule in value["routing_rules"]:
        if rule.get("from_step") != current_step:
            continue
        if _routing_rule_matches(rule, routing_values):
            return str(rule["to_step"])
    order_items: list[str] = []
    for item in value["step_order"]:
        order_items.append(str(item))
    order = tuple(order_items)
    if current_step not in order:
        return None
    index = order.index(current_step) + 1
    return None if index >= len(order) else order[index]


def _routing_rule_matches(
    rule: Mapping[str, Any],
    values: Mapping[str, Any],
) -> bool:
    kind = str(rule.get("kind"))
    condition = rule.get("condition", {})
    if kind == "always" and not condition:
        return True
    if kind == "on_status":
        expected = condition.get("status", condition.get("equals"))
        return values.get("worker_result.status") == expected
    if kind == "on_verdict":
        if "passed" in condition and values.get(
            "quality_verdict.passed"
        ) != condition["passed"]:
            return False
        score = values.get("quality_verdict.score")
        if "min_score" in condition and (
            not isinstance(score, int | float)
            or score < condition["min_score"]
        ):
            return False
        if "max_score" in condition and (
            not isinstance(score, int | float)
            or score > condition["max_score"]
        ):
            return False
        return True
    path = condition.get("path", condition.get("field"))
    if not isinstance(path, str):
        return not condition
    actual = values.get(path)
    if "exists" in condition:
        return (actual is not None) is bool(condition["exists"])
    if "equals" in condition:
        return actual == condition["equals"]
    if "not_equals" in condition:
        return actual != condition["not_equals"]
    if "in" in condition:
        return actual in condition["in"]
    if "not_in" in condition:
        return actual not in condition["not_in"]
    if "gte" in condition and not _numeric_compare(actual, condition["gte"], "gte"):
        return False
    if "gt" in condition and not _numeric_compare(actual, condition["gt"], "gt"):
        return False
    if "lte" in condition and not _numeric_compare(actual, condition["lte"], "lte"):
        return False
    if "lt" in condition and not _numeric_compare(actual, condition["lt"], "lt"):
        return False
    return True


def _routing_snapshot_values(state: Any, rules: Sequence[Any]) -> dict[str, Any]:
    paths: set[str] = set()
    for rule in rules:
        _collect_routing_paths(rule.condition, paths)
    values: dict[str, Any] = {}
    for path in sorted(paths):
        if path.startswith("state.inputs."):
            values[path] = _nested_value(
                state.run_spec.inputs,
                path.removeprefix("state.inputs."),
            )
        elif path.startswith("state.outputs."):
            outputs = state.metadata.get("outputs", {})
            values[path] = _nested_value(
                outputs if isinstance(outputs, Mapping) else {},
                path.removeprefix("state.outputs."),
            )
        elif path.startswith("state.step_status."):
            step_id = path.removeprefix("state.step_status.")
            values[path] = next(
                (
                    step.status.value
                    for step in state.step_states
                    if step.step_id == step_id
                ),
                None,
            )
    return values


def _collect_routing_paths(value: Any, paths: set[str]) -> None:
    if not isinstance(value, Mapping):
        return
    path = value.get("path", value.get("field"))
    if isinstance(path, str):
        paths.add(path)
    for key in ("all", "any"):
        clauses = value.get(key, ())
        if isinstance(clauses, list | tuple):
            for clause in clauses:
                _collect_routing_paths(clause, paths)


def _nested_value(value: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for segment in dotted_path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _numeric_compare(actual: Any, expected: Any, operation: str) -> bool:
    if not isinstance(actual, int | float) or not isinstance(expected, int | float):
        return False
    if operation == "gte":
        return actual >= expected
    if operation == "gt":
        return actual > expected
    if operation == "lte":
        return actual <= expected
    return actual < expected


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


class HarnessReplayActivityResolver(ReplayActivityResolverPort):
    """Resolve Harness worker outcomes from the generic recorded-activity store."""

    def __init__(
        self,
        store: RecordedActivityStorePort,
        registry: ReplayActivityRegistry,
    ) -> None:
        if store is None:
            raise TypeError("store is required")
        if not isinstance(registry, ReplayActivityRegistry):
            raise TypeError("registry must be ReplayActivityRegistry")
        self._resolver = RecordedActivityResolver(store, registry)

    def resolve(
        self,
        expected_activity: ReplayActivityDescriptor,
        recorded_ref: PayloadReference,
    ) -> ResolvedReplayActivity:
        if not isinstance(expected_activity, ReplayActivityDescriptor):
            raise TypeError("expected_activity must be ReplayActivityDescriptor")
        if not isinstance(recorded_ref, PayloadReference):
            raise TypeError("recorded_ref must be PayloadReference")
        try:
            return self._resolver.resolve(expected_activity, recorded_ref)
        except ReplayActivityCorruptionError:
            raise
        except Exception as exc:
            if isinstance(exc, ReplayActivityMissingError):
                raise
            raise ReplayActivityCorruptionError(
                "Harness recorded activity cannot be resolved"
            ) from exc


def build_harness_history_verifier(
    *,
    workflow_id: str,
    workflow_version: str,
    activity_store: RecordedActivityStorePort | None = None,
    secure_activity_store: RecordedActivityStorePort | None = None,
    activity_versions: Sequence[ReplayActivityHandlerVersion] = (),
) -> HistoryVerifier:
    versions = ExactVersionRegistry()
    registrations = {
        ("workflow", str(workflow_id), str(workflow_version)),
        (
            "workflow",
            HARNESS_EVENT_HISTORY_WORKFLOW_ID,
            HARNESS_EVENT_HISTORY_WORKFLOW_VERSION,
        ),
        (
            "workflow",
            HARNESS_ACTIVITY_HISTORY_WORKFLOW_ID,
            HARNESS_ACTIVITY_CONTRACT,
        ),
        ("policy", HARNESS_HISTORY_POLICY_ID, HARNESS_POLICY_VERSION),
        (
            "schema",
            HARNESS_HISTORY_SCHEMA_ID,
            "newsroom.harness-event/v1",
        ),
        (
            "schema",
            HARNESS_TRANSITION_HISTORY_SCHEMA_ID,
            HARNESS_TRANSITION_DATA_SCHEMA,
        ),
    }
    for kind, component_id, version in sorted(registrations):
        versions.register(
            ExactVersionRegistration(kind, component_id, version, "pinned")
        )
    versions.register(
        ExactVersionRegistration(
            "reducer",
            HARNESS_HISTORY_HANDLER_ID,
            HARNESS_REDUCER_VERSION,
            harness_expected_commands,
        )
    )
    if (
        activity_store is not None
        and secure_activity_store is not None
        and activity_store is not secure_activity_store
    ):
        raise ValueError("activity_store and secure_activity_store must identify one store")
    recorded_store = activity_store or secure_activity_store
    resolver = None
    if recorded_store is not None:
        activity_versions_registry = ReplayActivityRegistry()
        for version in activity_versions:
            if not isinstance(version, ReplayActivityHandlerVersion):
                raise TypeError(
                    "activity_versions must contain ReplayActivityHandlerVersion values"
                )
            activity_versions_registry.register(version)
        resolver = HarnessReplayActivityResolver(
            recorded_store,
            activity_versions_registry,
        )
    return HistoryVerifier(versions=versions, activity_resolver=resolver)


def harness_activity_kind(activity_type: str) -> ReplayActivityKind:
    """Map a Harness worker type to its durable nondeterministic activity kind."""

    try:
        return _ACTIVITY_KIND_BY_TYPE[str(activity_type).strip()]
    except KeyError as exc:
        raise EventStoreCorruptionError(
            f"unsupported Harness replay activity type: {activity_type}"
        ) from exc


__all__ = [
    "HARNESS_ACTIVITY_HISTORY_WORKFLOW_ID",
    "HARNESS_EVENT_HISTORY_WORKFLOW_ID",
    "HARNESS_HISTORY_HANDLER_ID",
    "HARNESS_HISTORY_POLICY_ID",
    "HarnessReplayActivityResolver",
    "build_harness_history_verifier",
    "harness_decision_history",
    "harness_decision_input_snapshot",
    "harness_decision_kernel",
    "harness_activity_history",
    "harness_activity_kind",
    "harness_event_history",
    "harness_expected_commands",
    "harness_transition_history",
]
