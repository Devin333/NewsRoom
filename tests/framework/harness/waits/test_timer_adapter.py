from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.harness.waits.models import (
    HarnessWaitRegistrationRecord,
    HarnessWaitScope,
    HarnessWaitTimeoutRecord,
    HarnessWaitTimerWakeRecord,
)
from framework.harness.waits.timer import HarnessLiveTimerAdapter


class _DeadlineResolver:
    def __init__(self, deadline: datetime) -> None:
        self.deadline = deadline
        self.calls = 0

    def resolve_deadline(self, deadline_ref: str) -> datetime:
        assert deadline_ref == _ref("deadline")
        self.calls += 1
        return self.deadline


class _WakeSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.wakes: list[HarnessWaitTimerWakeRecord] = []

    def record_timer_wake(self, wake: HarnessWaitTimerWakeRecord) -> None:
        if self.fail:
            raise RuntimeError("canonical wake store unavailable")
        self.wakes.append(wake)


class _TimeoutSink:
    def __init__(self) -> None:
        self.timeouts: list[HarnessWaitTimeoutRecord] = []

    def record_wait_timeout(self, timeout: HarnessWaitTimeoutRecord) -> None:
        self.timeouts.append(timeout)


def test_live_timer_polls_clock_and_records_stable_wake() -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    resolver = _DeadlineResolver(now - timedelta(seconds=1))
    sink = _WakeSink()
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return now

    adapter = HarnessLiveTimerAdapter(
        deadline_resolver=resolver,
        wake_sink=sink,
        clock=clock,
    )
    registration = _registration()
    adapter.register_timer(registration)
    adapter.register_timer(registration)

    wakes = adapter.poll_due()

    assert clock_calls == 1
    assert resolver.calls == 1
    assert wakes == tuple(sink.wakes)
    assert wakes[0].recorded_sequence == 0
    assert adapter.registration_count == 0


def test_failed_wake_commit_keeps_registration_for_retry() -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    sink = _WakeSink(fail=True)
    adapter = HarnessLiveTimerAdapter(
        deadline_resolver=_DeadlineResolver(now),
        wake_sink=sink,
        clock=lambda: now,
    )
    adapter.register_timer(_registration())

    with pytest.raises(RuntimeError, match="store unavailable"):
        adapter.poll_due()

    assert adapter.registration_count == 1


def test_replay_recorded_wake_never_calls_clock_or_deadline_resolver() -> None:
    registration = _registration()
    wake = HarnessWaitTimerWakeRecord(
        registration.scope,
        registration.deadline_ref,
        _ref("recorded-wake"),
        12,
    )
    resolver = _DeadlineResolver(datetime(2099, 1, 1, tzinfo=UTC))
    clock_calls = 0

    def forbidden_live_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        raise AssertionError("timer replay consulted the live clock")

    adapter = HarnessLiveTimerAdapter(
        deadline_resolver=resolver,
        wake_sink=_WakeSink(),
        clock=forbidden_live_clock,
    )

    replayed = adapter.replay_recorded_wake(registration, wake)

    assert replayed is wake
    assert resolver.calls == 0
    assert clock_calls == 0


def test_non_timer_deadline_emits_timeout_record() -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    timeout_sink = _TimeoutSink()
    adapter = HarnessLiveTimerAdapter(
        deadline_resolver=_DeadlineResolver(now),
        wake_sink=_WakeSink(),
        timeout_sink=timeout_sink,
        clock=lambda: now,
    )
    registration = _registration(kind="signal")
    adapter.register_timer(registration)

    emitted = adapter.poll_due()

    assert len(emitted) == 1
    assert isinstance(emitted[0], HarnessWaitTimeoutRecord)
    assert timeout_sink.timeouts == [emitted[0]]
    assert HarnessLiveTimerAdapter.replay_recorded_timeout(
        registration,
        emitted[0],
    ) is emitted[0]


def _registration(*, kind: str = "timer") -> HarnessWaitRegistrationRecord:
    return HarnessWaitRegistrationRecord(
        HarnessWaitScope(
            "timer-wait",
            "run-1",
            "node-1",
            _ref("tenant"),
            _ref("identity"),
            "newsroom.timer@1",
            _ref("correlation"),
        ),
        kind,
        5,
        _ref("deadline"),
    )


def _ref(value: str) -> str:
    return checksum_for({"value": value})
