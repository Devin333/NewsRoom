from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.events.canonical import normalize_canonical_json
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


class HarnessEventType(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STATE_CHANGED = "run_state_changed"
    STEP_STATE_CHANGED = "step_state_changed"
    PHASE_RECORDED = "phase_recorded"
    GRAPH_PHASE_TRANSITION_RECORDED = "graph_phase_transition_recorded"
    DECISION_RECORDED = "decision_recorded"
    GRAPH_WORKER_CALLED = "graph_worker_called"
    GRAPH_WORKER_RESULT_RECORDED = "graph_worker_result_recorded"
    BUDGET_FACT_RECORDED = "budget_fact_recorded"
    GATE_EVALUATED = "gate_evaluated"
    CHECKPOINT_CREATED = "checkpoint_created"
    CONTEXT_COMPACTION_PLANNED = "context_compaction_planned"
    CONTEXT_COMPACTION_ACTION_APPLIED = "context_compaction_action_applied"
    CONTEXT_SUMMARY_CANDIDATE_CREATED = "context_summary_candidate_created"
    CONTEXT_COMPACTION_VERIFIED = "context_compaction_verified"
    CONTEXT_COMPACTION_REJECTED = "context_compaction_rejected"


HARNESS_EVENT_SOURCE = "io.newsroom.harness.control-plane"


@dataclass(frozen=True)
class HarnessEvent:
    event_type: HarnessEventType | str
    run_id: str
    event_id: str | None = None
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: Any = field(default_factory=utc_now)
    trace_id: str | None = None
    deterministic_history: Mapping[str, Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

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
        payload = dict(payload)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "metadata", metadata)
        history = self.deterministic_history
        if history is not None:
            history = normalize_canonical_json(
                history,
                path="$.harness.deterministic_history",
            )
            if not isinstance(history, Mapping):
                raise HarnessValidationError(
                    "deterministic_history must be an object"
                )
        object.__setattr__(self, "deterministic_history", history)
        event_id = self.event_id or _stable_event_id(
            run_id=self.run_id,
            event_type=self.event_type.value,
            node_id=self.node_id,
            payload=self.payload,
            metadata=self.metadata,
            occurred_at=self.occurred_at,
        )
        if not str(event_id).strip():
            raise HarnessValidationError("event_id is required")
        object.__setattr__(self, "event_id", str(event_id))

    def to_dict(
        self,
        *,
        include_deterministic_history: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "payload": to_jsonable(self.payload),
            "metadata": to_jsonable(self.metadata),
            "occurred_at": format_datetime(self.occurred_at),
            "trace_id": self.trace_id,
        }
        if include_deterministic_history:
            payload["deterministic_history"] = to_jsonable(
                self.deterministic_history
            )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessEvent":
        if not isinstance(value, Mapping):
            raise HarnessValidationError("Harness event payload must be an object")
        payload = dict(value)
        occurred_at = parse_datetime(payload.pop("occurred_at", None))
        if occurred_at is None:
            raise HarnessValidationError("Harness event occurred_at is required")
        try:
            event_type = payload.pop("event_type")
            run_id = payload.pop("run_id")
        except KeyError as exc:
            raise HarnessValidationError(
                f"Harness event field is required: {exc.args[0]}"
            ) from exc
        event_id = payload.pop("event_id", None)
        node_id = payload.pop("node_id", None)
        event_payload = payload.pop("payload", {})
        metadata = payload.pop("metadata", {})
        trace_id = payload.pop("trace_id", None)
        deterministic_history = payload.pop("deterministic_history", None)
        if payload:
            raise HarnessValidationError(
                "Harness event payload contains unsupported fields: "
                + ", ".join(sorted(payload))
            )
        return cls(
            event_type=event_type,
            run_id=run_id,
            event_id=event_id,
            node_id=node_id,
            payload=event_payload,
            metadata=metadata,
            occurred_at=occurred_at,
            trace_id=trace_id,
            deterministic_history=deterministic_history,
        )


def _stable_event_id(
    *,
    run_id: str,
    event_type: str,
    node_id: str | None,
    payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    occurred_at: Any,
) -> str:
    projection = {
        "run_id": run_id,
        "event_type": event_type,
        "node_id": node_id,
        "payload": to_jsonable(payload),
        "metadata": to_jsonable(metadata),
        "occurred_at": format_datetime(occurred_at),
    }
    digest = hashlib.sha256(stable_json_dumps(projection).encode("utf-8")).hexdigest()
    return f"graph-event:{digest}"


__all__ = ["HarnessEvent", "HarnessEventType"]
