from __future__ import annotations

import contextvars
import math
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Callable, Generic, Iterator, Protocol, TypeVar

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


class LocalRetryBudgetExhaustedError(RuntimeExecutionError):
    """Raised when one logical operation has no local attempt slot left."""

    def __init__(self, *, max_attempts: int) -> None:
        super().__init__(
            "local retry budget exhausted",
            code="attempt_local_retry_exhausted",
            details={"max_attempts": max_attempts},
        )


class RetryCreditExhaustedError(RuntimeExecutionError):
    """Raised when the root execution has no retry credit left."""

    def __init__(self, *, max_total_retries: int) -> None:
        super().__init__(
            "root retry credit exhausted",
            code="attempt_global_retry_exhausted",
            details={"max_total_retries": max_total_retries},
        )


class DeadlineAdmissionRejectedError(RuntimeExecutionError):
    """Raised when a child cannot meet its declared start window."""

    def __init__(self, *, details: dict[str, object]) -> None:
        super().__init__(
            "attempt deadline admission rejected",
            code="attempt_deadline_admission_rejected",
            details=details,
        )


class ParentCancelledBeforeStartError(RuntimeExecutionError):
    """Raised when cancellation arrives before an attempt starts."""

    def __init__(self) -> None:
        super().__init__(
            "parent cancelled before attempt start",
            code="attempt_parent_cancelled_before_start",
        )


class AttemptCapacityExhaustedError(RuntimeExecutionError):
    """Raised when no bounded attempt-execution slot is available."""

    def __init__(self, *, max_active: int) -> None:
        super().__init__(
            "attempt execution capacity exhausted",
            code="attempt_capacity_exhausted",
            details={"max_active": max_active},
        )


class AttemptIndeterminateError(RuntimeExecutionError):
    """Raised when a descendant may have completed an unconfirmed effect."""

    def __init__(self, attempt_id: str) -> None:
        super().__init__(
            "attempt has an indeterminate descendant",
            code="attempt_indeterminate",
            details={"attempt_id": attempt_id},
        )


class AttemptLifecycleEmissionError(RuntimeExecutionError):
    """Raised when an authoritative attempt lifecycle fact cannot be recorded."""

    def __init__(self, phase: str, cause: BaseException) -> None:
        super().__init__(
            f"attempt {phase} lifecycle emission failed",
            code="attempt_lifecycle_emission_failed",
            details={"phase": phase, "error_type": type(cause).__name__},
        )


class AttemptCleanupError(RuntimeExecutionError):
    """Raised when an admitted attempt cannot prove resource cleanup."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(
            "attempt cleanup failed",
            code="attempt_cleanup_failed",
            details={"error_type": type(cause).__name__},
        )


class AttemptState(str, Enum):
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class LocalRetryBudget:
    """Attempt limit owned by one logical operation."""

    max_attempts: int
    _used: int = field(default=0, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

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

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "max_attempts": self.max_attempts,
                "used_attempts": self._used,
                "remaining_attempts": max(0, self.max_attempts - self._used),
            }

    def can_claim(self) -> bool:
        with self._lock:
            return self._used < self.max_attempts

    def claim(self) -> int:
        """Reserve the next local physical attempt number."""

        with self._lock:
            if self._used >= self.max_attempts:
                raise LocalRetryBudgetExhaustedError(max_attempts=self.max_attempts)
            self._used += 1
            return self._used

    def reserve(self, *, retry: bool) -> int:
        """Reserve an attempt; ``retry`` is explicit for auditability."""

        return self.claim()


@dataclass(slots=True)
class RetryCreditLedger:
    """Root-scoped ceiling counting retries, never first attempts."""

    max_total_retries: int
    _used_retries: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.max_total_retries) is not int or self.max_total_retries < 0:
            raise ValueError("max_total_retries must be a non-negative integer")

    @property
    def used_retries(self) -> int:
        with self._lock:
            return self._used_retries

    @property
    def remaining_retries(self) -> int:
        with self._lock:
            return max(0, self.max_total_retries - self._used_retries)

    def claim(self) -> str:
        with self._lock:
            if self._used_retries >= self.max_total_retries:
                raise RetryCreditExhaustedError(
                    max_total_retries=self.max_total_retries
                )
            self._used_retries += 1
            return uuid.uuid4().hex

    def rollback(self) -> None:
        with self._lock:
            if self._used_retries <= 0:
                raise RuntimeError("retry credit rollback underflow")
            self._used_retries -= 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "max_total_retries": self.max_total_retries,
                "used_retries": self._used_retries,
                "remaining_retries": max(
                    0, self.max_total_retries - self._used_retries
                ),
            }

    def can_claim(self) -> bool:
        with self._lock:
            return self._used_retries < self.max_total_retries


@dataclass(frozen=True, slots=True)
class DeadlineAdmissionPolicy:
    timeout_seconds: float | None = None
    min_start_window_seconds: float = 0.0
    cancellation_grace_seconds: float = 0.0
    completion_reserve_seconds: float = 0.0
    admission_details: dict[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        values = (
            self.min_start_window_seconds,
            self.cancellation_grace_seconds,
            self.completion_reserve_seconds,
        )
        if self.timeout_seconds is not None:
            values = (*values, self.timeout_seconds)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in values
        ):
            raise ValueError("deadline policy values must be finite and non-negative")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when set")
        if (
            self.timeout_seconds is not None
            and self.min_start_window_seconds > self.timeout_seconds
        ):
            raise ValueError(
                "min_start_window_seconds must not exceed timeout_seconds"
            )

    def to_dict(self) -> dict[str, float | None]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "min_start_window_seconds": self.min_start_window_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "completion_reserve_seconds": self.completion_reserve_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    """Root hard deadline and retry/terminal reserves."""

    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    hard_deadline: float | None = None
    retry_credits: RetryCreditLedger = field(
        default_factory=lambda: RetryCreditLedger(max_total_retries=0)
    )
    verify_reserve_seconds: float = 0.0
    commit_reserve_seconds: float = 0.0
    cancellation_grace_seconds: float = 0.0
    cancel_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )
    capacity: AttemptExecutionCapacity | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.execution_id:
            raise ValueError("execution_id is required")
        for name in (
            "verify_reserve_seconds",
            "commit_reserve_seconds",
            "cancellation_grace_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.hard_deadline is not None and not math.isfinite(float(self.hard_deadline)):
            raise ValueError("hard_deadline must be finite when set")

    @property
    def root_reserve_seconds(self) -> float:
        return self.verify_reserve_seconds + self.commit_reserve_seconds

    def snapshot(self, *, now: float | None = None) -> dict[str, object]:
        """Return diagnostics; resume must create a fresh execution scope."""

        remaining = None
        if self.hard_deadline is not None and now is not None:
            remaining = max(0.0, self.hard_deadline - float(now))
        return {
            "schema_version": "attempt-execution-limits/v1",
            "execution_id": self.execution_id,
            "hard_deadline_remaining_seconds": remaining,
            "root_reserve_seconds": self.root_reserve_seconds,
            "cancellation_grace_seconds": self.cancellation_grace_seconds,
            "verify_reserve_seconds": self.verify_reserve_seconds,
            "commit_reserve_seconds": self.commit_reserve_seconds,
            "retry_credits": self.retry_credits.snapshot(),
        }


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Stable logical operation scope shared by its physical retries."""

    operation_id: str
    operation_kind: str
    idempotency_key: str
    local_budget: LocalRetryBudget
    admission_policy: DeadlineAdmissionPolicy = field(
        default_factory=DeadlineAdmissionPolicy
    )
    execution_limits: ExecutionLimits | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or not self.operation_kind or not self.idempotency_key:
            raise ValueError("operation_id, operation_kind, and idempotency_key are required")


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    operation_id: str
    operation_kind: str
    idempotency_key: str
    attempt_id: str
    local_attempt_no: int
    parent_attempt_id: str | None = None
    retry_credit_id: str | None = None
    reserved_local_slot: bool = True

    def __post_init__(self) -> None:
        if not all(
            (
                self.operation_id,
                self.operation_kind,
                self.idempotency_key,
                self.attempt_id,
            )
        ):
            raise ValueError("attempt identity fields are required")
        if type(self.local_attempt_no) is not int or self.local_attempt_no < 1:
            raise ValueError("local_attempt_no must be a positive integer")


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    admitted: bool
    reason_code: str | None
    effective_deadline: float | None
    execution_window_seconds: float | None
    local_attempt_no: int | None = None
    retry_credit_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)


class AttemptLifecycleSink(Protocol):
    """Boundary adapter for durable or local attempt lifecycle facts.

    Sinks are authoritative by default. Local observability adapters can set
    ``required = False`` so their own failure never changes admission or
    execution semantics.
    """

    def rejected(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        admission: AdmissionResult,
    ) -> None: ...

    def started(self, *, context: "AttemptContext") -> None: ...

    def terminal(self, *, outcome: "AttemptOutcome[object]") -> None: ...


@dataclass(frozen=True, slots=True)
class CompositeAttemptLifecycleSink:
    """One authoritative lifecycle sink plus optional soft projections.

    The supervisor normally flattens composites before binding them to an
    ``AttemptContext``. Cross-store atomicity is impossible, so a composite
    rejects configurations with more than one required sink.
    """

    sinks: tuple[AttemptLifecycleSink, ...]

    def __post_init__(self) -> None:
        resolved = _unique_attempt_sinks(self.sinks)
        _validate_single_authoritative_sink(resolved)
        object.__setattr__(self, "sinks", resolved)

    def rejected(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        admission: AdmissionResult,
    ) -> None:
        _dispatch_rejected_sinks(
            self.sinks,
            operation_id=operation_id,
            operation_kind=operation_kind,
            idempotency_key=idempotency_key,
            admission=admission,
        )

    def started(self, *, context: "AttemptContext") -> None:
        _dispatch_started_sinks(self.sinks, context=context)

    def terminal(self, *, outcome: "AttemptOutcome[object]") -> None:
        _dispatch_terminal_sinks(self.sinks, outcome=outcome)


@dataclass(slots=True)
class AttemptReservation:
    """Atomic reservation which can be committed or rolled back exactly once."""

    local_budget: LocalRetryBudget
    local_attempt_no: int
    retry_ledger: RetryCreditLedger | None = None
    retry_credit_id: str | None = None
    committed: bool = False
    rolled_back: bool = False
    _local_lock_held: bool = field(default=True, init=False, repr=False)

    def commit(self) -> None:
        if self.committed or self.rolled_back:
            raise RuntimeError("attempt reservation already finalized")
        self.committed = True
        self._release_local_lock()

    def rollback(self) -> None:
        if self.committed:
            raise RuntimeError("committed attempt reservation cannot roll back")
        if self.rolled_back:
            return
        if self.local_budget._used <= 0:
            raise RuntimeError("local attempt rollback underflow")
        self.local_budget._used -= 1
        if self.retry_ledger is not None and self.retry_credit_id is not None:
            self.retry_ledger.rollback()
        self.rolled_back = True
        self._release_local_lock()

    def _release_local_lock(self) -> None:
        if self._local_lock_held:
            self.local_budget._lock.release()
            self._local_lock_held = False

class AttemptExecutionCapacity:
    """Non-blocking bound on live, supervised attempt threads."""

    def __init__(self, max_active: int = 128) -> None:
        if type(max_active) is not int or max_active < 1:
            raise ValueError("max_active must be a positive integer")
        self.max_active = max_active
        self._slots = threading.BoundedSemaphore(max_active)
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def acquire(self) -> bool:
        if not self._slots.acquire(blocking=False):
            return False
        with self._lock:
            self._active += 1
        return True

    def release(self) -> None:
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("attempt execution capacity released too many times")
            self._active -= 1
        self._slots.release()


DEFAULT_ATTEMPT_EXECUTION_CAPACITY = AttemptExecutionCapacity()


def derive_idempotency_key(
    parent_key: str,
    child_kind: str,
    child_id: str,
    *,
    max_length: int = 256,
) -> str:
    """Derive a stable bounded key for one logical child operation."""

    parent = str(parent_key).strip()
    kind = str(child_kind).strip()
    identity = str(child_id).strip()
    if not parent or not kind or not identity:
        raise ValueError("parent_key, child_kind, and child_id are required")
    if type(max_length) is not int or max_length < 32:
        raise ValueError("max_length must be an integer greater than or equal to 32")
    raw = f"{parent}:{kind}:{identity}"
    if len(raw) <= max_length:
        return raw
    digest = sha256(raw.encode("utf-8")).hexdigest()[:24]
    prefix_length = max(1, max_length - len(digest) - 1)
    return f"{raw[:prefix_length]}:{digest}"


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
    local_attempt_no: int = 1
    operation_id: str | None = None
    operation_kind: str = "attempt"
    parent_attempt_id: str | None = None
    retry_credit_id: str | None = None
    execution_limits: ExecutionLimits | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    completion_reserve_seconds: float = 0.0
    admission_details: dict[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    deadline: float | None = None
    clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
        compare=False,
    )
    cancel_event: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
        compare=False,
    )
    parent_cancel_event: threading.Event | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    local_budget: LocalRetryBudget | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    lifecycle_sinks: tuple[AttemptLifecycleSink, ...] = field(
        default_factory=tuple,
        repr=False,
        compare=False,
    )
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
        if isinstance(self.local_attempt_no, bool) or self.local_attempt_no < 1:
            raise ValueError("local_attempt_no must be a positive integer")
        if not self.operation_id:
            object.__setattr__(self, "operation_id", self.idempotency_key)
        if (
            not math.isfinite(float(self.completion_reserve_seconds))
            or self.completion_reserve_seconds < 0
        ):
            raise ValueError("completion_reserve_seconds must be finite and non-negative")
        object.__setattr__(self, "admission_details", dict(self.admission_details))
        object.__setattr__(
            self,
            "lifecycle_sinks",
            _unique_attempt_sinks(self.lifecycle_sinks),
        )

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        local_attempt_no: int = 1,
        operation_id: str | None = None,
        operation_kind: str = "attempt",
        parent_attempt_id: str | None = None,
        retry_credit_id: str | None = None,
        execution_limits: ExecutionLimits | None = None,
        completion_reserve_seconds: float = 0.0,
        admission_details: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
        attempt_id: str | None = None,
        local_budget: LocalRetryBudget | None = None,
        lifecycle_sinks: tuple[AttemptLifecycleSink, ...] = (),
        cancel_event: threading.Event | None = None,
        parent_cancel_event: threading.Event | None = None,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> "AttemptContext":
        resolved_deadline = deadline
        if resolved_deadline is None and timeout_seconds is not None and timeout_seconds > 0:
            resolved_deadline = clock() + float(timeout_seconds)
        return cls(
            attempt_id=attempt_id or uuid.uuid4().hex,
            idempotency_key=idempotency_key,
            local_attempt_no=local_attempt_no,
            operation_id=operation_id,
            operation_kind=operation_kind,
            parent_attempt_id=parent_attempt_id,
            retry_credit_id=retry_credit_id,
            execution_limits=execution_limits,
            completion_reserve_seconds=completion_reserve_seconds,
            admission_details=dict(admission_details or {}),
            deadline=resolved_deadline,
            clock=clock,
            cancel_event=cancel_event or threading.Event(),
            parent_cancel_event=parent_cancel_event,
            local_budget=local_budget,
            lifecycle_sinks=lifecycle_sinks,
        )

    @property
    def attempt_no(self) -> int:
        """Compatibility spelling for local attempt number."""

        return self.local_attempt_no

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return (
            self.cancel_event.is_set()
            or bool(
                self.parent_cancel_event is not None
                and self.parent_cancel_event.is_set()
            )
            or bool(
                self.execution_limits is not None
                and self.execution_limits.cancel_event.is_set()
            )
        )

    @property
    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - self.clock())

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AttemptCancelledError(self.attempt_id)

    def raise_if_indeterminate(self) -> None:
        if self.has_indeterminate_descendant:
            raise AttemptIndeterminateError(self.attempt_id)

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


def _flatten_attempt_sinks(
    sink: AttemptLifecycleSink | None,
) -> tuple[AttemptLifecycleSink, ...]:
    if sink is None:
        return ()
    if isinstance(sink, CompositeAttemptLifecycleSink):
        return sink.sinks
    return (sink,)


def _unique_attempt_sinks(
    sinks: tuple[AttemptLifecycleSink, ...],
) -> tuple[AttemptLifecycleSink, ...]:
    unique: list[AttemptLifecycleSink] = []
    positions: dict[object, int] = {}
    for sink in sinks:
        for candidate in _flatten_attempt_sinks(sink):
            authority_key = (
                getattr(candidate, "authority_key", None)
                if _attempt_sink_is_required(candidate)
                else None
            )
            try:
                identity: object = (
                    ("authority", authority_key)
                    if authority_key is not None
                    else ("object", id(candidate))
                )
                hash(identity)
            except (TypeError, ValueError):
                identity = ("object", id(candidate))
            previous = positions.get(identity)
            if previous is not None:
                # The most local adapter has the most accurate trace context
                # while writing to the same authoritative store.
                if authority_key is not None:
                    unique[previous] = candidate
                continue
            positions[identity] = len(unique)
            unique.append(candidate)
    return tuple(unique)


def _validate_single_authoritative_sink(
    sinks: tuple[AttemptLifecycleSink, ...],
) -> None:
    if sum(1 for sink in sinks if _attempt_sink_is_required(sink)) > 1:
        raise ValueError(
            "an attempt lifecycle may have only one authoritative sink; "
            "additional projections must set required = False"
        )


def _ordered_attempt_sinks(
    sinks: tuple[AttemptLifecycleSink, ...],
) -> tuple[AttemptLifecycleSink, ...]:
    """Run the authoritative projection before failure-isolated telemetry."""

    return tuple(
        sorted(
            sinks,
            key=lambda sink: 0 if _attempt_sink_is_required(sink) else 1,
        )
    )


def _compute_admission_window(
    *,
    now: float,
    requested_timeout: float | None,
    policy: DeadlineAdmissionPolicy,
    parent_available_deadline: float | None,
    execution_limits: ExecutionLimits | None,
) -> tuple[float | None, float | None, dict[str, object]]:
    requested_until = (
        now + float(requested_timeout)
        if requested_timeout is not None and requested_timeout > 0
        else None
    )
    parent_until = parent_available_deadline
    root_until = None
    if execution_limits is not None and execution_limits.hard_deadline is not None:
        root_until = execution_limits.hard_deadline - execution_limits.root_reserve_seconds
    # A local timeout bounds the callable itself. Parent/root boundaries are
    # completion boundaries, so child cancellation and completion windows
    # must be removed before admission. This keeps a standalone short timeout
    # startable while still protecting every enclosing hard deadline.
    child_reserve = (
        policy.cancellation_grace_seconds
        + policy.completion_reserve_seconds
    )
    execution_candidates = [
        value
        for value in (
            requested_until,
            (
                parent_until - child_reserve
                if parent_until is not None
                else None
            ),
            (
                root_until - child_reserve
                if root_until is not None
                else None
            ),
        )
        if value is not None
    ]
    effective_deadline = min(execution_candidates) if execution_candidates else None
    completion_candidates = [
        value
        for value in (
            (
                requested_until + child_reserve
                if requested_until is not None
                else None
            ),
            parent_until,
            root_until,
        )
        if value is not None
    ]
    completion_until = min(completion_candidates) if completion_candidates else None
    window = (
        effective_deadline - now
        if effective_deadline is not None
        else None
    )
    details: dict[str, object] = {
        "now_monotonic": now,
        "requested_until": requested_until,
        "parent_available_until": parent_until,
        "root_available_until": root_until,
        "completion_until": completion_until,
        "effective_deadline": effective_deadline,
        "execution_window_seconds": window,
        "min_start_window_seconds": policy.min_start_window_seconds,
        "cancellation_grace_seconds": policy.cancellation_grace_seconds,
        "completion_reserve_seconds": policy.completion_reserve_seconds,
    }
    return effective_deadline, window, details


def _reserve_attempt(
    *,
    local_budget: LocalRetryBudget,
    retry_ledger: RetryCreditLedger | None,
) -> AttemptReservation:
    local_budget._lock.acquire()
    try:
        if local_budget._used >= local_budget.max_attempts:
            raise LocalRetryBudgetExhaustedError(
                max_attempts=local_budget.max_attempts
            )
        local_attempt_no = local_budget._used + 1
        retry_credit_id: str | None = None
        if local_attempt_no > 1:
            if retry_ledger is None:
                raise RetryCreditExhaustedError(max_total_retries=0)
            retry_credit_id = retry_ledger.claim()
        local_budget._used = local_attempt_no
        return AttemptReservation(
            local_budget=local_budget,
            local_attempt_no=local_attempt_no,
            retry_ledger=retry_ledger,
            retry_credit_id=retry_credit_id,
        )
    except BaseException:
        local_budget._lock.release()
        raise


@dataclass(frozen=True, slots=True)
class AttemptOutcome(Generic[T]):
    context: AttemptContext | None
    state: AttemptState
    value: T | None = None
    error: BaseException | None = field(default=None, repr=False, compare=False)
    timed_out: bool = False
    termination_confirmed: bool = True
    indeterminate: bool = False
    elapsed_seconds: float = 0.0
    started: bool = True
    reason_code: str | None = None
    admission: AdmissionResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.state is AttemptState.SUCCEEDED


@dataclass(frozen=True, slots=True)
class AttemptFinalization(Generic[T]):
    """A finalized outcome with reversible caller-owned publication.

    ``rollback`` must restore staged caller state when the authoritative
    terminal fact cannot be persisted. ``complete`` releases the transaction
    only after that fact is durable. Both callbacks must be idempotent.
    """

    outcome: AttemptOutcome[T]
    rollback: Callable[[], None]
    complete: Callable[[], None]

    def __post_init__(self) -> None:
        if not callable(self.rollback) or not callable(self.complete):
            raise TypeError("attempt finalization callbacks must be callable")


def _attempt_sink_is_required(sink: AttemptLifecycleSink) -> bool:
    """Treat lifecycle sinks as authoritative unless they opt out explicitly."""

    try:
        return bool(getattr(sink, "required", True))
    except Exception:
        # A malformed optional telemetry adapter must not silently make a
        # durable lifecycle fact optional.
        return True


def _dispatch_rejected_sinks(
    sinks: tuple[AttemptLifecycleSink, ...],
    *,
    operation_id: str,
    operation_kind: str,
    idempotency_key: str,
    admission: AdmissionResult,
) -> None:
    for sink in _ordered_attempt_sinks(sinks):
        try:
            sink.rejected(
                operation_id=operation_id,
                operation_kind=operation_kind,
                idempotency_key=idempotency_key,
                admission=admission,
            )
        except BaseException as exc:  # noqa: BLE001 - boundary adapter failure
            if _attempt_sink_is_required(sink):
                raise AttemptLifecycleEmissionError("rejected", exc) from exc


def _started_compensation_outcome(
    *,
    context: AttemptContext,
    cause: BaseException,
) -> AttemptOutcome[object]:
    error = AttemptLifecycleEmissionError("started", cause)
    return AttemptOutcome(
        context=context,
        state=AttemptState.FAILED,
        error=error,
        elapsed_seconds=0.0,
        reason_code=error.code,
    )


def _dispatch_started_sinks(
    sinks: tuple[AttemptLifecycleSink, ...],
    *,
    context: AttemptContext,
) -> None:
    successful: list[AttemptLifecycleSink] = []
    for sink in _ordered_attempt_sinks(sinks):
        try:
            sink.started(context=context)
        except BaseException as exc:  # noqa: BLE001 - boundary adapter failure
            if not _attempt_sink_is_required(sink):
                continue
            compensation = _started_compensation_outcome(
                context=context,
                cause=exc,
            )
            # Only sinks that acknowledged the start may receive a terminal
            # compensation. Sending a terminal fact to the failing sink would
            # create terminal-without-start when its failure happened before
            # persistence. Required sinks own atomic start persistence.
            for observed_sink in successful:
                try:
                    observed_sink.terminal(outcome=compensation)
                except BaseException:
                    pass
            raise AttemptLifecycleEmissionError("started", exc) from exc
        else:
            successful.append(sink)


def _dispatch_terminal_sinks(
    sinks: tuple[AttemptLifecycleSink, ...],
    *,
    outcome: AttemptOutcome[object],
) -> None:
    for sink in _ordered_attempt_sinks(sinks):
        try:
            sink.terminal(outcome=outcome)
        except BaseException as exc:  # noqa: BLE001 - boundary adapter failure
            if _attempt_sink_is_required(sink):
                raise AttemptLifecycleEmissionError("terminal", exc) from exc


class AttemptSupervisor:
    """Admit and execute physical attempts without ghost consumption."""

    def __init__(
        self,
        *,
        cancellation_grace_seconds: float = 0.1,
        capacity: AttemptExecutionCapacity | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        grace = float(cancellation_grace_seconds)
        if not math.isfinite(grace) or grace < 0:
            raise ValueError("cancellation_grace_seconds must be finite and non-negative")
        if not callable(clock):
            raise ValueError("clock must be callable")
        self.cancellation_grace_seconds = grace
        self.capacity = capacity or DEFAULT_ATTEMPT_EXECUTION_CAPACITY
        self.clock = clock

    def run(
        self,
        fn: Callable[[], T],
        *,
        timeout_seconds: float | None,
        idempotency_key: str,
        operation_id: str | None = None,
        operation_kind: str = "attempt",
        attempt_id: str | None = None,
        local_budget: LocalRetryBudget | None = None,
        retry_ledger: RetryCreditLedger | None = None,
        admission_policy: DeadlineAdmissionPolicy | None = None,
        execution_limits: ExecutionLimits | None = None,
        parent_available_deadline: float | None = None,
        cancel_event: threading.Event | None = None,
        parent_cancel_event: threading.Event | None = None,
        parent_context: AttemptContext | None = None,
        prepare: Callable[[AttemptIdentity], Callable[[], None] | None] | None = None,
        finalize: Callable[
            [AttemptOutcome[T]],
            AttemptOutcome[T] | AttemptFinalization[T],
        ]
        | None = None,
        event_sink: AttemptLifecycleSink | None = None,
    ) -> AttemptOutcome[T]:
        if not callable(fn):
            raise ValueError("fn must be callable")
        resolved_operation_id = str(operation_id or idempotency_key).strip()
        resolved_kind = str(operation_kind).strip()
        resolved_key = str(idempotency_key).strip()
        if not resolved_operation_id or not resolved_kind or not resolved_key:
            raise ValueError("operation identity fields are required")

        if parent_context is not None:
            parent_cancel_event = parent_context.cancel_event
            execution_limits = execution_limits or parent_context.execution_limits
            if parent_available_deadline is None and parent_context.deadline is not None:
                parent_available_deadline = parent_context.deadline
        lifecycle_sinks = _unique_attempt_sinks(
            (
                *(parent_context.lifecycle_sinks if parent_context is not None else ()),
                *_flatten_attempt_sinks(event_sink),
            )
        )
        _validate_single_authoritative_sink(lifecycle_sinks)
        if execution_limits is not None:
            if retry_ledger is not None and retry_ledger is not execution_limits.retry_credits:
                raise ValueError("retry_ledger must be the root execution ledger")
            retry_ledger = execution_limits.retry_credits
        local_budget = local_budget or LocalRetryBudget(max_attempts=1)
        retry_ledger = retry_ledger or RetryCreditLedger(
            max_total_retries=max(0, local_budget.max_attempts - 1)
        )
        policy = admission_policy or DeadlineAdmissionPolicy(
            timeout_seconds=timeout_seconds,
            cancellation_grace_seconds=self.cancellation_grace_seconds,
        )
        requested_timeout = (
            policy.timeout_seconds
            if policy.timeout_seconds is not None
            else timeout_seconds
        )
        now = self.clock()
        effective_deadline, window, deadline_details = _compute_admission_window(
            now=now,
            requested_timeout=requested_timeout,
            policy=policy,
            parent_available_deadline=parent_available_deadline,
            execution_limits=execution_limits,
        )
        snapshots = self._snapshots(local_budget, retry_ledger)
        if self._cancelled_before_start(
            parent_context=parent_context,
            cancel_event=cancel_event,
            parent_cancel_event=parent_cancel_event,
            execution_limits=execution_limits,
        ):
            return self._rejected(
                error=ParentCancelledBeforeStartError(),
                effective_deadline=effective_deadline,
                window=window,
                details={**deadline_details, **snapshots},
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )
        if window is not None and (
            window <= 0 or window < policy.min_start_window_seconds
        ):
            details = {
                **deadline_details,
                **snapshots,
                "min_start_window_seconds": policy.min_start_window_seconds,
            }
            return self._rejected(
                error=DeadlineAdmissionRejectedError(details=details),
                effective_deadline=effective_deadline,
                window=window,
                details=details,
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )
        if not local_budget.can_claim():
            return self._rejected(
                error=LocalRetryBudgetExhaustedError(
                    max_attempts=local_budget.max_attempts
                ),
                effective_deadline=effective_deadline,
                window=window,
                details={**deadline_details, **snapshots},
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )
        if local_budget.used > 0 and not retry_ledger.can_claim():
            return self._rejected(
                error=RetryCreditExhaustedError(
                    max_total_retries=retry_ledger.max_total_retries
                ),
                effective_deadline=effective_deadline,
                window=window,
                details={**deadline_details, **snapshots},
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )

        capacity = (
            execution_limits.capacity
            if execution_limits is not None
            and execution_limits.capacity is not None
            else self.capacity
        )
        if not capacity.acquire():
            return self._rejected(
                error=AttemptCapacityExhaustedError(max_active=capacity.max_active),
                effective_deadline=effective_deadline,
                window=window,
                details={**deadline_details, **snapshots},
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )
        try:
            reservation = _reserve_attempt(
                local_budget=local_budget,
                retry_ledger=retry_ledger,
            )
        except (LocalRetryBudgetExhaustedError, RetryCreditExhaustedError) as exc:
            capacity.release()
            return self._rejected(
                error=exc,
                effective_deadline=effective_deadline,
                window=window,
                details={
                    **deadline_details,
                    **self._snapshots(local_budget, retry_ledger),
                },
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )

        identity = AttemptIdentity(
            operation_id=resolved_operation_id,
            operation_kind=resolved_kind,
            idempotency_key=resolved_key,
            attempt_id=attempt_id or uuid.uuid4().hex,
            local_attempt_no=reservation.local_attempt_no,
            parent_attempt_id=(
                parent_context.attempt_id if parent_context is not None else None
            ),
            retry_credit_id=reservation.retry_credit_id,
        )
        try:
            self._raise_if_start_window_closed(
                effective_deadline=effective_deadline,
                policy=policy,
                parent_context=parent_context,
                cancel_event=cancel_event,
                parent_cancel_event=parent_cancel_event,
                execution_limits=execution_limits,
                deadline_details=deadline_details,
            )
            context = AttemptContext.create(
                attempt_id=identity.attempt_id,
                idempotency_key=identity.idempotency_key,
                local_attempt_no=identity.local_attempt_no,
                operation_id=identity.operation_id,
                operation_kind=identity.operation_kind,
                parent_attempt_id=identity.parent_attempt_id,
                retry_credit_id=identity.retry_credit_id,
                execution_limits=execution_limits,
                completion_reserve_seconds=policy.completion_reserve_seconds,
                admission_details={
                    **deadline_details,
                    **self._snapshots(local_budget, retry_ledger),
                    "min_start_window_seconds": policy.min_start_window_seconds,
                },
                deadline=effective_deadline,
                local_budget=local_budget,
                lifecycle_sinks=lifecycle_sinks,
                cancel_event=cancel_event,
                parent_cancel_event=parent_cancel_event,
                clock=self.clock,
            )
        except BaseException as exc:
            reservation.rollback()
            capacity.release()
            if isinstance(
                exc,
                (ParentCancelledBeforeStartError, DeadlineAdmissionRejectedError),
            ):
                error = exc
            else:
                error = RuntimeExecutionError(
                    "attempt preparation failed",
                    code="attempt_preparation_failed",
                    details={"error_type": type(exc).__name__},
                )
            return self._rejected(
                error=error,
                effective_deadline=effective_deadline,
                window=(
                    effective_deadline - self.clock()
                    if effective_deadline is not None
                    else None
                ),
                details={
                    **deadline_details,
                    **self._snapshots(local_budget, retry_ledger),
                },
                operation_id=resolved_operation_id,
                operation_kind=resolved_kind,
                idempotency_key=resolved_key,
                lifecycle_sinks=lifecycle_sinks,
            )

        has_supervision = (
            effective_deadline is not None
            or parent_context is not None
            or cancel_event is not None
            or parent_cancel_event is not None
            or execution_limits is not None
        )
        if not has_supervision:
            return self._run_inline(
                fn,
                identity=identity,
                context=context,
                parent_context=parent_context,
                reservation=reservation,
                capacity=capacity,
                prepare=prepare,
                finalize=finalize,
            )
        return self._run_threaded(
            fn,
            identity=identity,
            context=context,
            parent_context=parent_context,
            reservation=reservation,
            capacity=capacity,
            cancellation_grace_seconds=policy.cancellation_grace_seconds,
            prepare=prepare,
            finalize=finalize,
        )

    def _run_inline(
        self,
        fn: Callable[[], T],
        *,
        identity: AttemptIdentity,
        context: AttemptContext,
        parent_context: AttemptContext | None,
        reservation: AttemptReservation,
        capacity: AttemptExecutionCapacity,
        prepare: Callable[[AttemptIdentity], Callable[[], None] | None] | None,
        finalize: Callable[
            [AttemptOutcome[T]],
            AttemptOutcome[T] | AttemptFinalization[T],
        ]
        | None,
    ) -> AttemptOutcome[T]:
        started = self.clock()
        cleanup: Callable[[], None] | None = None
        try:
            self._emit_started(context)
            reservation.commit()
        except BaseException:
            reservation.rollback()
            capacity.release()
            raise
        try:
            cleanup = self._prepare_started_attempt(prepare, identity)
        except BaseException as exc:
            capacity.release()
            outcome = self._completed_outcome(
                context=context,
                parent_context=parent_context,
                value=None,
                error=self._preparation_error(exc),
                elapsed_seconds=self.clock() - started,
            )
            return self._finalize_started_outcome(
                outcome,
                parent_context=parent_context,
                cleanup=cleanup,
                finalize=None,
            )
        try:
            with bind_attempt_context(context):
                context.raise_if_cancelled()
                value = fn()
        except BaseException as exc:  # noqa: BLE001 - runtime carries failures
            outcome = self._completed_outcome(
                context=context,
                parent_context=parent_context,
                value=None,
                error=exc,
                elapsed_seconds=self.clock() - started,
            )
        else:
            outcome = self._completed_outcome(
                context=context,
                parent_context=parent_context,
                value=value,
                error=None,
                elapsed_seconds=self.clock() - started,
            )
        finally:
            capacity.release()
        return self._finalize_started_outcome(
            outcome,
            parent_context=parent_context,
            cleanup=cleanup,
            finalize=finalize,
        )

    def _run_threaded(
        self,
        fn: Callable[[], T],
        *,
        identity: AttemptIdentity,
        context: AttemptContext,
        parent_context: AttemptContext | None,
        reservation: AttemptReservation,
        capacity: AttemptExecutionCapacity,
        cancellation_grace_seconds: float,
        prepare: Callable[[AttemptIdentity], Callable[[], None] | None] | None,
        finalize: Callable[
            [AttemptOutcome[T]],
            AttemptOutcome[T] | AttemptFinalization[T],
        ]
        | None,
    ) -> AttemptOutcome[T]:
        started = self.clock()
        completed = threading.Event()
        start_gate = threading.Event()
        start_aborted = threading.Event()
        result: list[T] = []
        failure: list[BaseException] = []
        finished_at: list[float] = []
        cleanup: Callable[[], None] | None = None

        def invoke() -> None:
            start_gate.wait()
            if start_aborted.is_set():
                completed.set()
                return
            try:
                with bind_attempt_context(context):
                    context.raise_if_cancelled()
                    result.append(fn())
            except BaseException as exc:  # noqa: BLE001 - runtime carries failures
                failure.append(exc)
            finally:
                finished_at.append(self.clock())
                capacity.release()
                completed.set()

        caller_context = contextvars.copy_context()
        thread = threading.Thread(
            target=lambda: caller_context.run(invoke),
            daemon=True,
            name=f"framework-attempt:{context.attempt_id[:12]}",
        )
        try:
            thread.start()
            self._emit_started(context)
            reservation.commit()
        except BaseException:
            start_aborted.set()
            start_gate.set()
            if thread.is_alive():
                thread.join()
            reservation.rollback()
            capacity.release()
            raise
        try:
            cleanup = self._prepare_started_attempt(prepare, identity)
        except BaseException as exc:
            start_aborted.set()
            start_gate.set()
            thread.join()
            capacity.release()
            outcome = self._completed_outcome(
                context=context,
                parent_context=parent_context,
                value=None,
                error=self._preparation_error(exc),
                elapsed_seconds=self.clock() - started,
            )
            return self._finalize_started_outcome(
                outcome,
                parent_context=parent_context,
                cleanup=cleanup,
                finalize=None,
            )
        remaining_after_prepare = context.remaining_seconds
        if remaining_after_prepare is not None and remaining_after_prepare <= 0:
            context.cancel()
        start_gate.set()

        completed_before_deadline = False
        while True:
            if completed.is_set():
                completion_time = finished_at[0]
                completed_before_deadline = (
                    not context.cancelled
                    and (
                        context.deadline is None
                        or completion_time <= context.deadline
                    )
                )
                break
            if context.cancelled:
                context.cancel()
            remaining = context.remaining_seconds
            if (remaining is not None and remaining <= 0) or context.cancelled:
                break
            wait_seconds = 0.05 if remaining is None else min(remaining, 0.05)
            completed.wait(wait_seconds)
        if completed_before_deadline:
            thread.join()
            outcome = self._completed_outcome(
                context=context,
                parent_context=parent_context,
                value=result[0] if result else None,
                error=failure[0] if failure else None,
                elapsed_seconds=self.clock() - started,
            )
            return self._finalize_started_outcome(
                outcome,
                parent_context=parent_context,
                cleanup=cleanup,
                finalize=finalize,
            )

        context.cancel()
        callable_terminated = completed.wait(cancellation_grace_seconds)
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
        outcome = AttemptOutcome(
            context=context,
            state=AttemptState.TIMED_OUT,
            timed_out=True,
            termination_confirmed=termination_confirmed,
            indeterminate=indeterminate,
            elapsed_seconds=self.clock() - started,
        )
        return self._finalize_started_outcome(
            outcome,
            parent_context=parent_context,
            cleanup=cleanup,
            finalize=finalize,
        )

    @staticmethod
    def _prepare_started_attempt(
        prepare: Callable[[AttemptIdentity], Callable[[], None] | None] | None,
        identity: AttemptIdentity,
    ) -> Callable[[], None] | None:
        if prepare is None:
            return None
        cleanup = prepare(identity)
        if cleanup is not None and not callable(cleanup):
            raise TypeError("prepare must return a callable cleanup or None")
        return cleanup

    @staticmethod
    def _preparation_error(exc: BaseException) -> RuntimeExecutionError:
        if isinstance(exc, RuntimeExecutionError):
            return exc
        return RuntimeExecutionError(
            "attempt preparation failed",
            code="attempt_preparation_failed",
            details={"error_type": type(exc).__name__},
        )

    @staticmethod
    def _emit_started(context: AttemptContext) -> None:
        _dispatch_started_sinks(context.lifecycle_sinks, context=context)

    def _finalize_started_outcome(
        self,
        outcome: AttemptOutcome[T],
        *,
        parent_context: AttemptContext | None,
        cleanup: Callable[[], None] | None,
        finalize: Callable[
            [AttemptOutcome[T]],
            AttemptOutcome[T] | AttemptFinalization[T],
        ]
        | None,
    ) -> AttemptOutcome[T]:
        context = outcome.context
        if context is None:
            raise RuntimeError("terminal attempt outcome is missing context")
        finalized = outcome
        rollback: Callable[[], None] | None = None
        complete: Callable[[], None] | None = None
        if finalize is not None:
            try:
                with bind_attempt_context(context):
                    candidate = finalize(outcome)
                if isinstance(candidate, AttemptFinalization):
                    rollback = candidate.rollback
                    complete = candidate.complete
                    candidate_outcome = candidate.outcome
                else:
                    candidate_outcome = candidate
                if not isinstance(candidate_outcome, AttemptOutcome):
                    raise TypeError("attempt finalize must return AttemptOutcome")
                if candidate_outcome.context is not context:
                    raise ValueError("attempt finalize must preserve its context")
                if (
                    not candidate_outcome.started
                    or candidate_outcome.state is AttemptState.REJECTED
                ):
                    raise ValueError("attempt finalize must preserve a started outcome")
                finalized = candidate_outcome
            except BaseException as exc:  # noqa: BLE001 - fail closed on finalization
                rollback_error = self._rollback_finalization(rollback)
                finalized = self._indeterminate_finalization_outcome(
                    outcome,
                    parent_context=parent_context,
                    error=RuntimeExecutionError(
                        "attempt outcome finalization failed",
                        code="attempt_outcome_finalization_failed",
                        details={
                            "error_type": type(exc).__name__,
                            **(
                                {
                                    "rollback_error_type": type(
                                        rollback_error
                                    ).__name__
                                }
                                if rollback_error is not None
                                else {}
                            ),
                        },
                    ),
                )
                rollback = None
                complete = None
        self._propagate_finalized_state(finalized, parent_context)
        if cleanup is not None:
            try:
                cleanup()
            except BaseException as exc:  # noqa: BLE001 - cleanup state is unknown
                finalized = self._indeterminate_finalization_outcome(
                    finalized,
                    parent_context=parent_context,
                    error=AttemptCleanupError(exc),
                )
        if finalized.state is not AttemptState.SUCCEEDED and rollback is not None:
            rollback_error = self._rollback_finalization(rollback)
            rollback = None
            complete = None
            if rollback_error is not None:
                finalized = self._indeterminate_finalization_outcome(
                    finalized,
                    parent_context=parent_context,
                    error=RuntimeExecutionError(
                        "attempt finalization rollback failed",
                        code="attempt_finalization_rollback_failed",
                        details={"error_type": type(rollback_error).__name__},
                    ),
                )
        try:
            self._emit_terminal(finalized)
        except BaseException as terminal_error:
            rollback_error = self._rollback_finalization(rollback)
            if rollback_error is not None:
                context.cancel()
                if parent_context is not None:
                    parent_context.mark_descendant_indeterminate()
                raise AttemptLifecycleEmissionError(
                    "terminal_compensation",
                    rollback_error,
                ) from terminal_error
            raise
        if complete is not None:
            try:
                complete()
            except BaseException as exc:  # noqa: BLE001 - durable fact already exists
                context.cancel()
                if parent_context is not None:
                    parent_context.mark_descendant_indeterminate()
                raise AttemptLifecycleEmissionError(
                    "terminal_completion",
                    exc,
                ) from exc
        return finalized

    @staticmethod
    def _rollback_finalization(
        rollback: Callable[[], None] | None,
    ) -> BaseException | None:
        if rollback is None:
            return None
        try:
            rollback()
        except BaseException as exc:  # noqa: BLE001 - preserve compensation failure
            return exc
        return None

    def _propagate_finalized_state(
        self,
        outcome: AttemptOutcome[T],
        parent_context: AttemptContext | None,
    ) -> None:
        context = outcome.context
        if context is None:
            raise RuntimeError("terminal attempt outcome is missing context")
        if outcome.indeterminate or outcome.state is AttemptState.INDETERMINATE:
            context.mark_descendant_indeterminate()
        if outcome.state is AttemptState.TIMED_OUT and not outcome.termination_confirmed:
            context.mark_descendant_unconfirmed()
        self._propagate_descendant_state(context, parent_context)

    @staticmethod
    def _indeterminate_finalization_outcome(
        outcome: AttemptOutcome[T],
        *,
        parent_context: AttemptContext | None,
        error: RuntimeExecutionError,
    ) -> AttemptOutcome[T]:
        context = outcome.context
        if context is None:
            raise RuntimeError("terminal attempt outcome is missing context")
        context.cancel()
        if parent_context is not None:
            parent_context.mark_descendant_indeterminate()
        return AttemptOutcome(
            context=context,
            state=AttemptState.INDETERMINATE,
            error=error,
            timed_out=outcome.timed_out,
            termination_confirmed=outcome.termination_confirmed,
            indeterminate=True,
            elapsed_seconds=outcome.elapsed_seconds,
            reason_code=error.code,
        )

    @staticmethod
    def _emit_terminal(
        outcome: AttemptOutcome[T],
    ) -> None:
        context = outcome.context
        if context is None:
            raise RuntimeError("terminal attempt outcome is missing context")
        _dispatch_terminal_sinks(context.lifecycle_sinks, outcome=outcome)

    def _completed_outcome(
        self,
        *,
        context: AttemptContext,
        parent_context: AttemptContext | None,
        value: T | None,
        error: BaseException | None,
        elapsed_seconds: float,
    ) -> AttemptOutcome[T]:
        if context.has_indeterminate_descendant:
            context.cancel()
            self._propagate_descendant_state(context, parent_context)
            return AttemptOutcome(
                context=context,
                state=(
                    AttemptState.TIMED_OUT
                    if context.has_unconfirmed_descendant
                    else AttemptState.INDETERMINATE
                ),
                error=error,
                timed_out=context.has_unconfirmed_descendant,
                termination_confirmed=not context.has_unconfirmed_descendant,
                indeterminate=True,
                elapsed_seconds=elapsed_seconds,
            )
        if error is not None:
            return AttemptOutcome(
                context=context,
                state=AttemptState.FAILED,
                error=error,
                elapsed_seconds=elapsed_seconds,
            )
        return AttemptOutcome(
            context=context,
            state=AttemptState.SUCCEEDED,
            value=value,
            elapsed_seconds=elapsed_seconds,
        )

    def _raise_if_start_window_closed(
        self,
        *,
        effective_deadline: float | None,
        policy: DeadlineAdmissionPolicy,
        parent_context: AttemptContext | None,
        cancel_event: threading.Event | None,
        parent_cancel_event: threading.Event | None,
        execution_limits: ExecutionLimits | None,
        deadline_details: dict[str, object],
    ) -> None:
        if self._cancelled_before_start(
            parent_context=parent_context,
            cancel_event=cancel_event,
            parent_cancel_event=parent_cancel_event,
            execution_limits=execution_limits,
        ):
            raise ParentCancelledBeforeStartError()
        if effective_deadline is None:
            return
        remaining = effective_deadline - self.clock()
        if remaining <= 0 or remaining < policy.min_start_window_seconds:
            raise DeadlineAdmissionRejectedError(
                details={
                    **deadline_details,
                    "execution_window_seconds": remaining,
                    "min_start_window_seconds": policy.min_start_window_seconds,
                }
            )

    @staticmethod
    def _cancelled_before_start(
        *,
        parent_context: AttemptContext | None,
        cancel_event: threading.Event | None,
        parent_cancel_event: threading.Event | None,
        execution_limits: ExecutionLimits | None,
    ) -> bool:
        return bool(
            (parent_context is not None and parent_context.cancelled)
            or (cancel_event is not None and cancel_event.is_set())
            or (
                parent_cancel_event is not None
                and parent_cancel_event.is_set()
            )
            or (
                execution_limits is not None
                and execution_limits.cancel_event.is_set()
            )
        )

    @staticmethod
    def _snapshots(
        local_budget: LocalRetryBudget,
        retry_ledger: RetryCreditLedger,
    ) -> dict[str, object]:
        return {
            "local_budget": local_budget.snapshot(),
            "root_retry_credits": retry_ledger.snapshot(),
        }

    def _rejected(
        self,
        *,
        error: RuntimeExecutionError,
        effective_deadline: float | None,
        window: float | None,
        details: dict[str, object],
        operation_id: str,
        operation_kind: str,
        idempotency_key: str,
        lifecycle_sinks: tuple[AttemptLifecycleSink, ...],
    ) -> AttemptOutcome[T]:
        admission = AdmissionResult(
            admitted=False,
            reason_code=error.code,
            effective_deadline=effective_deadline,
            execution_window_seconds=window,
            details=details,
        )
        _dispatch_rejected_sinks(
            lifecycle_sinks,
            operation_id=operation_id,
            operation_kind=operation_kind,
            idempotency_key=idempotency_key,
            admission=admission,
        )
        return AttemptOutcome(
            context=None,
            state=AttemptState.REJECTED,
            error=error,
            started=False,
            reason_code=error.code,
            admission=admission,
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
    "AttemptCapacityExhaustedError",
    "AttemptCancelledError",
    "AttemptCleanupError",
    "AttemptContext",
    "AttemptExecutionCapacity",
    "AttemptIndeterminateError",
    "AttemptLifecycleEmissionError",
    "AttemptLifecycleSink",
    "AttemptIdentity",
    "AttemptOutcome",
    "AttemptState",
    "AttemptSupervisor",
    "CompositeAttemptLifecycleSink",
    "AttemptReservation",
    "AdmissionResult",
    "DeadlineAdmissionPolicy",
    "ExecutionLimits",
    "LocalRetryBudget",
    "LocalRetryBudgetExhaustedError",
    "OperationContext",
    "ParentCancelledBeforeStartError",
    "RetryCreditExhaustedError",
    "RetryCreditLedger",
    "DeadlineAdmissionRejectedError",
    "bind_attempt_context",
    "current_attempt_context",
    "derive_idempotency_key",
]
