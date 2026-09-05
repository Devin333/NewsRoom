from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import checksum, thaw_mapping
from framework.harness.workers.result import HarnessWorkerResult, HarnessWorkerStatus

if TYPE_CHECKING:
    from framework.harness.task_plan.store import TaskPlanEvent


def submission_result_from_event(event: TaskPlanEvent) -> HarnessWorkerResult:
    """Read an immutable stage outcome; never reconstruct it by running workers."""
    payload = event.payload
    try:
        checksum(payload.get("submission_key"), "submission_key")
        raw = payload.get("terminal_result")
        if not isinstance(raw, Mapping):
            raise ValueError("terminal result must be an object")
        raw = thaw_mapping(raw)
        result = HarnessWorkerResult.from_dict(raw)
        if (
            result.effect_intent is not None or result.to_dict() != raw
            or result.artifacts or result.metrics
        ):
            raise ValueError("terminal result must be a canonical stage outcome")
        if result.candidate_result_ref != payload.get("terminal_result_checksum"):
            raise ValueError("terminal result checksum mismatch")
        if event.event_type == "TASK_PLAN_VERIFIED":
            if (
                result.status is not HarnessWorkerStatus.SUCCEEDED
                or result.output.get("aggregate_checksum") != event.input_checksum
                or result.error is not None
            ):
                raise ValueError("terminal result does not match stage verification")
        elif event.event_type == "TASK_PLAN_HALTED":
            if (
                result.status not in {HarnessWorkerStatus.FAILED, HarnessWorkerStatus.BLOCKED}
                or result.diagnostics != {"reason_code": event.reason_code}
                or result.output or result.error != event.reason_code
            ):
                raise ValueError("terminal result does not match stage halt")
        else:
            raise ValueError("terminal result is not attached to a terminal event")
        return result
    except (HarnessValidationError, TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "recorded candidate submission outcome is invalid",
            code="task_plan_submission_result_invalid",
        ) from exc
