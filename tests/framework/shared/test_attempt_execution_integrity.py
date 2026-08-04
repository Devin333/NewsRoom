from __future__ import annotations

import threading
import time

from framework.shared.attempts import (
    AttemptCapacityExhaustedError,
    AttemptExecutionCapacity,
    AttemptState,
    AttemptSupervisor,
)


def test_non_cooperative_attempts_are_admitted_by_a_hard_capacity_limit() -> None:
    release = threading.Event()
    capacity = AttemptExecutionCapacity(max_active=2)
    supervisor = AttemptSupervisor(
        cancellation_grace_seconds=0.001,
        capacity=capacity,
    )

    def block() -> None:
        release.wait(1)

    first = supervisor.run(
        block,
        timeout_seconds=0.001,
        idempotency_key="capacity:first",
    )
    second = supervisor.run(
        block,
        timeout_seconds=0.001,
        idempotency_key="capacity:second",
    )
    third = supervisor.run(
        block,
        timeout_seconds=0.001,
        idempotency_key="capacity:third",
    )

    assert first.state is AttemptState.TIMED_OUT
    assert second.state is AttemptState.TIMED_OUT
    assert isinstance(third.error, AttemptCapacityExhaustedError)
    assert third.state is AttemptState.FAILED
    assert capacity.active == 2

    release.set()
    deadline = time.monotonic() + 1
    while capacity.active and time.monotonic() < deadline:
        time.sleep(0.005)
    assert capacity.active == 0
