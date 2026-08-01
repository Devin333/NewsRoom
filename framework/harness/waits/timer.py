from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import RLock

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.canonical import canonical_checksum
from framework.harness.workflow.dsl import WaitKind
from framework.harness.waits.models import (
    HarnessWaitRegistrationRecord,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
)
from framework.harness.waits.ports import (
    HarnessTimerDeadlineResolverPort,
    HarnessTimerWakeSinkPort,
    HarnessWaitTimeoutSinkPort,
)


class HarnessLiveTimerAdapter:
    """Live timer scheduler whose replay path never reads the current clock."""

    def __init__(
        self,
        *,
        deadline_resolver: HarnessTimerDeadlineResolverPort,
        wake_sink: HarnessTimerWakeSinkPort,
        timeout_sink: HarnessWaitTimeoutSinkPort | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(deadline_resolver, HarnessTimerDeadlineResolverPort):
            raise TypeError(
                "deadline_resolver must implement HarnessTimerDeadlineResolverPort"
            )
        if not isinstance(wake_sink, HarnessTimerWakeSinkPort):
            raise TypeError("wake_sink must implement HarnessTimerWakeSinkPort")
        if timeout_sink is not None and not isinstance(
            timeout_sink,
            HarnessWaitTimeoutSinkPort,
        ):
            raise TypeError(
                "timeout_sink must implement HarnessWaitTimeoutSinkPort"
            )
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._deadline_resolver = deadline_resolver
        self._wake_sink = wake_sink
        self._timeout_sink = timeout_sink
        self._clock = clock
        self._registrations: dict[str, HarnessWaitRegistrationRecord] = {}
        self._lock = RLock()

    @property
    def registration_count(self) -> int:
        with self._lock:
            return len(self._registrations)

    def register_timer(self, registration: HarnessWaitRegistrationRecord) -> None:
        if not isinstance(registration, HarnessWaitRegistrationRecord):
            raise TypeError("registration must be HarnessWaitRegistrationRecord")
        if registration.deadline_ref is None:
            raise HarnessValidationError(
                "timer registration requires a durable deadline ref",
                code="timer_deadline_missing",
            )
        key = registration.scope.scope_ref
        with self._lock:
            existing = self._registrations.get(key)
            if existing is not None and existing != registration:
                raise HarnessValidationError(
                    "timer scope was registered with conflicting content",
                    code="wait_timer_registration_conflict",
                )
            self._registrations[key] = registration

    def cancel_timer(self, registration: HarnessWaitRegistrationRecord) -> None:
        if not isinstance(registration, HarnessWaitRegistrationRecord):
            raise TypeError("registration must be HarnessWaitRegistrationRecord")
        key = registration.scope.scope_ref
        with self._lock:
            existing = self._registrations.get(key)
            if existing is None:
                return
            if existing != registration:
                raise HarnessValidationError(
                    "timer cancellation does not match its registration",
                    code="wait_timer_registration_conflict",
                )
            self._registrations.pop(key, None)

    def poll_due(
        self,
    ) -> tuple[HarnessWaitTimerWakeRecord | HarnessWaitTimeoutRecord, ...]:
        """Read the live clock once and submit every due wake in stable order."""

        now = _aware_datetime(self._clock(), "clock")
        with self._lock:
            registrations = tuple(
                sorted(
                    self._registrations.values(),
                    key=lambda item: (
                        item.registered_sequence,
                        item.scope.scope_ref,
                    ),
                )
            )
        emitted: list[HarnessWaitTimerWakeRecord | HarnessWaitTimeoutRecord] = []
        for registration in registrations:
            assert registration.deadline_ref is not None
            deadline = _aware_datetime(
                self._deadline_resolver.resolve_deadline(
                    registration.deadline_ref
                ),
                "deadline",
            )
            if deadline > now:
                continue
            event_ref = canonical_checksum(
                {
                    "registration_ref": registration.registration_ref,
                    "deadline_ref": registration.deadline_ref,
                }
            )
            if registration.kind is WaitKind.TIMER:
                wake: HarnessWaitTimerWakeRecord | HarnessWaitTimeoutRecord = (
                    HarnessWaitTimerWakeRecord(
                        scope=registration.scope,
                        deadline_ref=registration.deadline_ref,
                        timer_event_ref=event_ref,
                        recorded_sequence=0,
                    )
                )
                self._wake_sink.record_timer_wake(wake)
            else:
                if self._timeout_sink is None:
                    raise HarnessValidationError(
                        "a non-timer deadline requires a timeout sink",
                        code="wait_timeout_sink_missing",
                    )
                timeout = HarnessWaitTimeoutRecord(
                    scope=registration.scope,
                    deadline_ref=registration.deadline_ref,
                    timeout_event_ref=event_ref,
                    timed_out_sequence=0,
                )
                self._timeout_sink.record_wait_timeout(timeout)
                wake = timeout
            with self._lock:
                current = self._registrations.get(registration.scope.scope_ref)
                if current == registration:
                    self._registrations.pop(registration.scope.scope_ref, None)
            emitted.append(wake)
        return tuple(emitted)

    @staticmethod
    def replay_recorded_wake(
        registration: HarnessWaitRegistrationRecord,
        wake: HarnessWaitTimerWakeRecord,
    ) -> HarnessWaitTimerWakeRecord:
        """Validate a recorded wake without resolving a deadline or reading a clock."""

        if not isinstance(registration, HarnessWaitRegistrationRecord):
            raise TypeError("registration must be HarnessWaitRegistrationRecord")
        if not isinstance(wake, HarnessWaitTimerWakeRecord):
            raise TypeError("wake must be HarnessWaitTimerWakeRecord")
        if registration.kind is not WaitKind.TIMER:
            raise HarnessValidationError(
                "recorded timer wake requires a timer registration",
                code="wait_timer_kind_mismatch",
            )
        if (
            wake.scope != registration.scope
            or wake.deadline_ref != registration.deadline_ref
        ):
            raise HarnessValidationError(
                "recorded timer wake does not match its registration",
                code="graph_wait_deadline_mismatch",
            )
        return wake

    @staticmethod
    def replay_recorded_timeout(
        registration: HarnessWaitRegistrationRecord,
        timeout: HarnessWaitTimeoutRecord,
    ) -> HarnessWaitTimeoutRecord:
        """Validate a recorded timeout without reading a deadline or clock."""

        if not isinstance(registration, HarnessWaitRegistrationRecord):
            raise TypeError("registration must be HarnessWaitRegistrationRecord")
        if not isinstance(timeout, HarnessWaitTimeoutRecord):
            raise TypeError("timeout must be HarnessWaitTimeoutRecord")
        if registration.kind is WaitKind.TIMER:
            raise HarnessValidationError(
                "recorded timeout cannot resolve a timer Wait",
                code="wait_timer_kind_mismatch",
            )
        if (
            timeout.scope != registration.scope
            or timeout.deadline_ref != registration.deadline_ref
        ):
            raise HarnessValidationError(
                "recorded timeout does not match its registration",
                code="graph_wait_deadline_mismatch",
            )
        return timeout


def _aware_datetime(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise HarnessValidationError(
            f"{field_name} must be timezone-aware",
            code="invalid_wait_timer_datetime",
        )
    return value


__all__ = ["HarnessLiveTimerAdapter"]
