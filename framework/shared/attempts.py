from __future__ import annotations

import contextvars
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generic, Iterator, TypeVar

from framework.shared.errors import RuntimeExecutionError


T = TypeVar("T")


class AttemptCancelledError(RuntimeExecutionError):
    """Raised by cooperative work after its attempt has been cancelled."""

    def __init__(self, attempt_id: str) -> None:
        super().__init__(
            "attempt was cancelled",
            code="attempt_cancelled",
            details={"attempt_id": attempt_id},
        )


class AttemptBudgetExhaustedError(RuntimeExecutionError):
    """Raised when a shared logical-operation attempt budget is exhausted."""

    def __init__(self, *, max_attempts: int) -> None:
        super().__init__(
            "attempt budget exhausted",
            code="attempt_budget_exhausted",
            details={"max_attempts": max_attempts},
        )


class AttemptState(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class AttemptBudget:
    """Thread-safe total-attempt budget shared by nested runtime layers."""

    max_attempts: int
    _used: int = field(default=0, init=False, repr=False)
    _ceiling: int | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_attempts - self._used)

    def claim(self) -> int:
        """Reserve one attempt and return its one-based fencing generation."""

        with self._lock:
            if self._used >= self.max_attempts:
                raise AttemptBudgetExhaustedError(max_attempts=self.max_attempts)
            self._used += 1
            return self._used

    def expand_to(self, max_attempts: int) -> None:
        """Raise, but never shrink, the shared logical-operation capacity."""

        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        with self._lock:
            target = (
                min(max_attempts, self._ceiling)
                if self._ceiling is not None
                else max_attempts
            )
            if target > self.max_attempts:
                self.max_attempts = target

    def cap_at(self, max_attempts: int) -> None:
        """Apply a shared total-attempt ceiling without invalidating claims."""

        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        with self._lock:
            self._ceiling = (
                max_attempts
                if self._ceiling is None
                else min(self._ceiling, max_attempts)
            )
            self.max_attempts = max(self._used, min(self.max_attempts, self._ceiling))


@dataclass(frozen=True, slots=True)
class AttemptContext:
    """Immutable identity plus cooperative coordination for one attempt.

    The event handles and shared budget are intentionally internally mutable;
    callers cannot replace them on the frozen context. Calling :meth:`cancel`
    requests cooperation and never asserts that a callable or descendant
    thread has terminated.
    """

    attempt_id: str
    idempotency_key: str
    fencing_token: int
    deadline: float | None = None
    cancel_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )
    budget: AttemptBudget | None = field(default=None, repr=False, compare=False)
    descendant_unconfirmed_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )
    descendant_indeterminate_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id is required")
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")
        if isinstance(self.fencing_token, bool) or self.fencing_token < 1:
            raise ValueError("fencing_token must be a positive integer")

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        fencing_token: int = 1,
        timeout_seconds: float | None = None,
        attempt_id: str | None = None,
        budget: AttemptBudget | None = None,
        cancel_event: threading.Event | None = None,
    ) -> "AttemptContext":
        deadline = (
            time.monotonic() + float(timeout_seconds)
            if timeout_seconds is not None and timeout_seconds > 0
            else None
        )
        return cls(
            attempt_id=attempt_id or uuid.uuid4().hex,
            idempotency_key=idempotency_key,
            fencing_token=fencing_token,
            deadline=deadline,
            cancel_event=cancel_event or threading.Event(),
            budget=budget,
        )

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AttemptCancelledError(self.attempt_id)

    def mark_descendant_unconfirmed(self) -> None:
        self.descendant_unconfirmed_event.set()
        self.descendant_indeterminate_event.set()

    def mark_descendant_indeterminate(self) -> None:
        self.descendant_indeterminate_event.set()

    @property
    def has_unconfirmed_descendant(self) -> bool:
        return self.descendant_unconfirmed_event.is_set()

    @property
    def has_indeterminate_descendant(self) -> bool:
        return self.descendant_indeterminate_event.is_set()


_CURRENT_ATTEMPT_CONTEXT: contextvars.ContextVar[AttemptContext | None] = (
    contextvars.ContextVar("framework_attempt_context", default=None)
)


def current_attempt_context() -> AttemptContext | None:
    """Return the attempt bound to the current execution context, if any."""

    return _CURRENT_ATTEMPT_CONTEXT.get()


@contextmanager
def bind_attempt_context(context: AttemptContext) -> Iterator[AttemptContext]:
    token = _CURRENT_ATTEMPT_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_ATTEMPT_CONTEXT.reset(token)


@dataclass(frozen=True, slots=True)
class AttemptOutcome(Generic[T]):
    context: AttemptContext
    state: AttemptState
    value: T | None = None
    error: BaseException | None = field(default=None, repr=False, compare=False)
    timed_out: bool = False
    termination_confirmed: bool = True
    indeterminate: bool = False
    elapsed_seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.state is AttemptState.SUCCEEDED


class AttemptSupervisor:
    """Execute callables with bounded, cooperative timeout semantics."""

    def __init__(self, *, cancellation_grace_seconds: float = 0.1) -> None:
        if cancellation_grace_seconds < 0:
            raise ValueError("cancellation_grace_seconds must be non-negative")
        self.cancellation_grace_seconds = float(cancellation_grace_seconds)

    def run(
        self,
        fn: Callable[[], T],
        *,
        timeout_seconds: float | None,
        idempotency_key: str,
        fencing_token: int = 1,
        attempt_id: str | None = None,
        budget: AttemptBudget | None = None,
        cancel_event: threading.Event | None = None,
        parent_cancel_event: threading.Event | None = None,
        parent_context: AttemptContext | None = None,
        claim_budget: bool = True,
    ) -> AttemptOutcome[T]:
        if parent_context is not None:
            parent_cancel_event = parent_context.cancel_event
        if budget is not None and claim_budget:
            fencing_token = budget.claim()
        context = AttemptContext.create(
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            fencing_token=fencing_token,
            timeout_seconds=timeout_seconds,
            budget=budget,
            cancel_event=cancel_event,
        )
        started = time.monotonic()
        if parent_cancel_event is not None and parent_cancel_event.is_set():
            context.cancel()

        has_deadline = timeout_seconds is not None and timeout_seconds > 0
        if not has_deadline and parent_cancel_event is None:
            try:
                with bind_attempt_context(context):
                    context.raise_if_cancelled()
                    value = fn()
            except BaseException as exc:  # noqa: BLE001 - carried to the owning runtime
                if context.has_indeterminate_descendant:
                    context.cancel()
                    self._propagate_descendant_state(context, parent_context)
                    return AttemptOutcome(
                        context=context,
                        state=AttemptState.TIMED_OUT,
                        error=exc,
                        timed_out=True,
                        termination_confirmed=not context.has_unconfirmed_descendant,
                        indeterminate=True,
                        elapsed_seconds=time.monotonic() - started,
                    )
                return AttemptOutcome(
                    context=context,
                    state=AttemptState.FAILED,
                    error=exc,
                    elapsed_seconds=time.monotonic() - started,
                )
            if context.has_indeterminate_descendant:
                context.cancel()
                self._propagate_descendant_state(context, parent_context)
                return AttemptOutcome(
                    context=context,
                    state=AttemptState.TIMED_OUT,
                    timed_out=True,
                    termination_confirmed=not context.has_unconfirmed_descendant,
                    indeterminate=True,
                    elapsed_seconds=time.monotonic() - started,
                )
            return AttemptOutcome(
                context=context,
                state=AttemptState.SUCCEEDED,
                value=value,
                elapsed_seconds=time.monotonic() - started,
            )

        completed = threading.Event()
        result: list[T] = []
        failure: list[BaseException] = []

        def invoke() -> None:
            try:
                with bind_attempt_context(context):
                    context.raise_if_cancelled()
                    result.append(fn())
            except BaseException as exc:  # noqa: BLE001 - carried to the owning runtime
                failure.append(exc)
            finally:
                completed.set()

        thread = threading.Thread(
            target=invoke,
            daemon=True,
            name=f"framework-attempt:{context.attempt_id[:12]}",
        )
        thread.start()
        timeout_deadline = (
            time.monotonic() + float(timeout_seconds)
            if has_deadline
            else None
        )
        completed_before_deadline = False
        while True:
            if parent_cancel_event is not None and parent_cancel_event.is_set():
                context.cancel()
            remaining = (
                timeout_deadline - time.monotonic()
                if timeout_deadline is not None
                else None
            )
            if (remaining is not None and remaining <= 0) or context.cancelled:
                break
            wait_seconds = 0.05 if remaining is None else min(remaining, 0.05)
            if completed.wait(wait_seconds):
                completed_before_deadline = True
                break
        if completed_before_deadline:
            thread.join()
            if context.has_indeterminate_descendant:
                context.cancel()
                self._propagate_descendant_state(context, parent_context)
                return AttemptOutcome(
                    context=context,
                    state=AttemptState.TIMED_OUT,
                    timed_out=True,
                    termination_confirmed=not context.has_unconfirmed_descendant,
                    indeterminate=True,
                    elapsed_seconds=time.monotonic() - started,
                )
            if failure:
                return AttemptOutcome(
                    context=context,
                    state=AttemptState.FAILED,
                    error=failure[0],
                    elapsed_seconds=time.monotonic() - started,
                )
            return AttemptOutcome(
                context=context,
                state=AttemptState.SUCCEEDED,
                value=result[0],
                elapsed_seconds=time.monotonic() - started,
            )

        context.cancel()
        callable_terminated = completed.wait(self.cancellation_grace_seconds)
        if callable_terminated:
            thread.join()
        termination_confirmed = (
            callable_terminated and not context.has_unconfirmed_descendant
        )
        indeterminate = (
            not termination_confirmed or context.has_indeterminate_descendant
        )
        if not termination_confirmed:
            context.mark_descendant_unconfirmed()
        self._propagate_descendant_state(context, parent_context)
        return AttemptOutcome(
            context=context,
            state=AttemptState.TIMED_OUT,
            timed_out=True,
            termination_confirmed=termination_confirmed,
            indeterminate=indeterminate,
            elapsed_seconds=time.monotonic() - started,
        )

    @staticmethod
    def _propagate_descendant_state(
        context: AttemptContext,
        parent_context: AttemptContext | None,
    ) -> None:
        if parent_context is None:
            return
        if context.has_unconfirmed_descendant:
            parent_context.mark_descendant_unconfirmed()
        elif context.has_indeterminate_descendant:
            parent_context.mark_descendant_indeterminate()


__all__ = [
    "AttemptBudget",
    "AttemptBudgetExhaustedError",
    "AttemptCancelledError",
    "AttemptContext",
    "AttemptOutcome",
    "AttemptState",
    "AttemptSupervisor",
    "bind_attempt_context",
    "current_attempt_context",
]
