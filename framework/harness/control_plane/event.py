from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.events.canonical import normalize_canonical_json
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, utc_now


class HarnessEventType(StrEnum):
    TRANSITION_COMMITTED = "harness_transition_committed"
    RUN_CREATED = "run_created"
    RUN_STATE_CHANGED = "run_state_changed"
    STEP_STATE_CHANGED = "step_state_changed"
    PHASE_RECORDED = "phase_recorded"
    DECISION_RECORDED = "decision_recorded"
    WORKER_CALLED = "worker_called"
    WORKER_RESULT_RECORDED = "worker_result_recorded"
    GATE_EVALUATED = "gate_evaluated"
    CHECKPOINT_CREATED = "checkpoint_created"


@dataclass(frozen=True)
class HarnessEvent:
    event_type: HarnessEventType | str
    run_id: str
    event_id: str | None = None
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: Any = field(default_factory=utc_now)
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", HarnessEventType(self.event_type))
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        object.__setattr__(self, "run_id", str(self.run_id))
        payload = normalize_canonical_json(to_jsonable(self.payload), path="$.harness.payload")
        metadata = normalize_canonical_json(to_jsonable(self.metadata), path="$.harness.metadata")
        if not isinstance(payload, Mapping):
            raise HarnessValidationError("payload must be an object")
        if not isinstance(metadata, Mapping):
            raise HarnessValidationError("metadata must be an object")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "metadata", metadata)
        event_id = self.event_id or _stable_event_id(
            run_id=self.run_id,
            event_type=self.event_type.value,
            step_id=self.step_id,
            payload=self.payload,
            metadata=self.metadata,
            occurred_at=self.occurred_at,
        )
        if not str(event_id).strip():
            raise HarnessValidationError("event_id is required")
        object.__setattr__(self, "event_id", str(event_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "payload": to_jsonable(self.payload),
            "metadata": to_jsonable(self.metadata),
            "occurred_at": format_datetime(self.occurred_at),
            "trace_id": self.trace_id,
        }


def _stable_event_id(
    *,
    run_id: str,
    event_type: str,
    step_id: str | None,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    occurred_at: Any,
) -> str:
    projection = {
        "run_id": run_id,
        "event_type": event_type,
        "step_id": step_id,
        "payload": to_jsonable(payload),
        "metadata": to_jsonable(metadata),
        "occurred_at": format_datetime(occurred_at),
    }
    digest = hashlib.sha256(stable_json_dumps(projection).encode("utf-8")).hexdigest()
    return f"harness-event:{digest}"


__all__ = ["HarnessEvent", "HarnessEventType"]
