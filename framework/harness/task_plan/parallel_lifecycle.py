"""Pure group and wave lifecycle contracts shared by execution and replay."""
from __future__ import annotations

from enum import StrEnum
from typing import Mapping


class DispatchGroupState(StrEnum):
    PLANNED = "PLANNED"
    ADMITTED = "ADMITTED"
    DISPATCHING = "DISPATCHING"
    RUNNING = "RUNNING"
    JOINING = "JOINING"
    REPLAN_PENDING = "REPLAN_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INDETERMINATE = "INDETERMINATE"
    HALTED = "HALTED"
    SUPERSEDED = "SUPERSEDED"


class DispatchWaveState(StrEnum):
    PLANNED = "PLANNED"
    ADMITTED = "ADMITTED"
    DISPATCHING = "DISPATCHING"
    RUNNING = "RUNNING"
    TERMINAL = "TERMINAL"


class DispatchWaveTerminalOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INDETERMINATE = "INDETERMINATE"
    RECLAIMED = "RECLAIMED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class SideEffectClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    EXTERNAL_IDEMPOTENT = "EXTERNAL_IDEMPOTENT"
    MUTATING_SERIAL = "MUTATING_SERIAL"
    FENCED_MUTATION = "FENCED_MUTATION"


_GROUP_TRANSITIONS: Mapping[DispatchGroupState, frozenset[DispatchGroupState]] = {
    DispatchGroupState.PLANNED: frozenset({DispatchGroupState.ADMITTED, DispatchGroupState.HALTED}),
    DispatchGroupState.ADMITTED: frozenset({
        DispatchGroupState.DISPATCHING,
        DispatchGroupState.RUNNING,
        DispatchGroupState.JOINING,
        DispatchGroupState.FAILED,
        DispatchGroupState.CANCELLED,
        DispatchGroupState.INDETERMINATE,
        DispatchGroupState.HALTED,
    }),
    DispatchGroupState.DISPATCHING: frozenset({
        DispatchGroupState.RUNNING,
        DispatchGroupState.JOINING,
        DispatchGroupState.FAILED,
        DispatchGroupState.CANCELLED,
        DispatchGroupState.INDETERMINATE,
        DispatchGroupState.HALTED,
    }),
    DispatchGroupState.RUNNING: frozenset({
        DispatchGroupState.DISPATCHING,
        DispatchGroupState.JOINING,
        DispatchGroupState.FAILED,
        DispatchGroupState.CANCELLED,
        DispatchGroupState.INDETERMINATE,
        DispatchGroupState.HALTED,
    }),
    DispatchGroupState.JOINING: frozenset({
        DispatchGroupState.SUCCEEDED,
        DispatchGroupState.FAILED,
        DispatchGroupState.CANCELLED,
        DispatchGroupState.INDETERMINATE,
        DispatchGroupState.HALTED,
        DispatchGroupState.REPLAN_PENDING,
    }),
    DispatchGroupState.REPLAN_PENDING: frozenset({
        DispatchGroupState.SUPERSEDED,
        DispatchGroupState.FAILED,
        DispatchGroupState.HALTED,
    }),
    DispatchGroupState.SUCCEEDED: frozenset(),
    DispatchGroupState.FAILED: frozenset(),
    DispatchGroupState.CANCELLED: frozenset(),
    DispatchGroupState.INDETERMINATE: frozenset(),
    DispatchGroupState.HALTED: frozenset(),
    DispatchGroupState.SUPERSEDED: frozenset(),
}

_WAVE_TRANSITIONS: Mapping[DispatchWaveState, frozenset[DispatchWaveState]] = {
    DispatchWaveState.PLANNED: frozenset({DispatchWaveState.ADMITTED}),
    # The durable dispatch event is emitted after the in-memory admission
    # transition; replay therefore validates the combined ADMITTED -> RUNNING
    # edge while live execution may still record DISPATCHING internally.
    DispatchWaveState.ADMITTED: frozenset({DispatchWaveState.DISPATCHING, DispatchWaveState.RUNNING, DispatchWaveState.TERMINAL}),
    DispatchWaveState.DISPATCHING: frozenset({DispatchWaveState.RUNNING, DispatchWaveState.TERMINAL}),
    DispatchWaveState.RUNNING: frozenset({DispatchWaveState.TERMINAL}),
    DispatchWaveState.TERMINAL: frozenset(),
}
