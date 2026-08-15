from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from framework.events.canonical import (
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventContractError, EventIntegrityError
from framework.events.projection import GraphEventContext
from framework.shared.time import format_datetime


GRAPH_PHASE_TRANSITION_SCHEMA = "newsroom.harness-graph-phase-transition/v1"

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GRAPH_PHASE_TRANSITION_FIELDS = frozenset(
    {
        "schema",
        "context",
        "phase",
        "boundary",
        "attempt",
        "event_sequence",
        "gate_evidence_refs",
        "occurred_at",
        "record_checksum",
    }
)


class GraphExecutionPhase(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPLAN = "replan"
    HALT = "halt"


class GraphPhaseBoundary(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class GraphPhaseTransitionRecord:
    context: GraphEventContext | Mapping[str, Any]
    phase: GraphExecutionPhase | str
    boundary: GraphPhaseBoundary | str
    attempt: int
    event_sequence: int
    occurred_at: datetime
    gate_evidence_refs: tuple[str, ...] = ()
    schema: str = GRAPH_PHASE_TRANSITION_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        context = self.context
        if isinstance(context, Mapping):
            context = GraphEventContext.from_dict(context)
        if not isinstance(context, GraphEventContext):
            raise TypeError("context must be GraphEventContext")
        if context.node_id is None or context.node_instance_id is None:
            raise EventContractError(
                "graph phase transition requires node identity"
            )
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "phase", _phase(self.phase))
        object.__setattr__(self, "boundary", _boundary(self.boundary))
        object.__setattr__(self, "attempt", _nonnegative_int(self.attempt, "attempt"))
        object.__setattr__(
            self,
            "event_sequence",
            _positive_int(self.event_sequence, "event_sequence"),
        )
        object.__setattr__(
            self,
            "gate_evidence_refs",
            _canonical_evidence_refs(self.gate_evidence_refs),
        )
        object.__setattr__(self, "occurred_at", _required_utc(self.occurred_at))
        if self.schema != GRAPH_PHASE_TRANSITION_SCHEMA:
            raise EventContractError(
                "graph phase transition schema is unsupported"
            )
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        context = self.context
        if not isinstance(context, GraphEventContext):  # pragma: no cover
            raise TypeError("context must be GraphEventContext")
        return {
            "schema": self.schema,
            "context": context.to_dict(),
            "phase": self.phase.value,
            "boundary": self.boundary.value,
            "attempt": self.attempt,
            "event_sequence": self.event_sequence,
            "gate_evidence_refs": list(self.gate_evidence_refs),
            "occurred_at": format_datetime(self.occurred_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "record_checksum": self.record_checksum,
        }

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.record_checksum:
            raise EventIntegrityError(
                "graph phase transition checksum does not match"
            )

    def assert_envelope_sequence(self, stream_sequence: int) -> None:
        normalized = _positive_int(stream_sequence, "stream_sequence")
        if normalized != self.event_sequence:
            raise EventContractError(
                "graph phase transition sequence differs from durable envelope"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphPhaseTransitionRecord:
        normalized = normalize_canonical_json(
            value,
            path="$.graph_phase_transition",
        )
        raw = thaw_canonical_json(normalized)
        payload = _exact_mapping(
            raw,
            _GRAPH_PHASE_TRANSITION_FIELDS,
            "graph phase transition",
        )
        context = _mapping(payload["context"], "context")
        supplied_refs = _evidence_refs(payload["gate_evidence_refs"])
        if supplied_refs != tuple(sorted(supplied_refs)):
            raise EventContractError(
                "gate_evidence_refs must use canonical order"
            )
        record = cls(
            context=GraphEventContext.from_dict(context),
            phase=payload["phase"],
            boundary=payload["boundary"],
            attempt=payload["attempt"],
            event_sequence=payload["event_sequence"],
            gate_evidence_refs=supplied_refs,
            occurred_at=_parse_utc(payload["occurred_at"]),
            schema=payload["schema"],
        )
        supplied_checksum = _sha256_ref(
            payload["record_checksum"],
            "record_checksum",
        )
        if supplied_checksum != record.record_checksum:
            raise EventIntegrityError(
                "graph phase transition checksum does not match"
            )
        return record


def _phase(value: Any) -> GraphExecutionPhase:
    try:
        return GraphExecutionPhase(value)
    except (TypeError, ValueError) as exc:
        raise EventContractError(
            "graph phase transition phase is unsupported"
        ) from exc


def _boundary(value: Any) -> GraphPhaseBoundary:
    try:
        return GraphPhaseBoundary(value)
    except (TypeError, ValueError) as exc:
        raise EventContractError(
            "graph phase transition boundary is unsupported"
        ) from exc


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventContractError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EventContractError(f"{field_name} must be a positive integer")
    return value


def _canonical_evidence_refs(value: Any) -> tuple[str, ...]:
    return tuple(sorted(_evidence_refs(value)))


def _evidence_refs(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise EventContractError("gate_evidence_refs must be an array")
    refs = tuple(
        _sha256_ref(item, "gate_evidence_refs item")
        for item in value
    )
    if len(set(refs)) != len(refs):
        raise EventContractError("gate_evidence_refs must be unique")
    return refs


def _required_utc(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise EventContractError("occurred_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventContractError("occurred_at must be timezone-aware")
    return value.astimezone(UTC)


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EventContractError("occurred_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventContractError(
            "occurred_at must be an RFC 3339 timestamp"
        ) from exc
    return _required_utc(parsed)


def _sha256_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
        raise EventContractError(f"{field_name} must be SHA-256")
    return value


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventContractError(f"{field_name} must be an object")
    return value


def _exact_mapping(
    value: Any,
    expected_fields: frozenset[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EventContractError(f"{model} must be an object")
    payload = dict(value)
    if set(payload) != expected_fields:
        raise EventContractError(f"{model} fields are invalid")
    return payload


__all__ = [
    "GRAPH_PHASE_TRANSITION_SCHEMA",
    "GraphExecutionPhase",
    "GraphPhaseBoundary",
    "GraphPhaseTransitionRecord",
]
