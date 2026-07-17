from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from threading import RLock, local
from typing import Final


DEFAULT_DIAGNOSTIC_CAPACITY: Final = 128
MAX_DIAGNOSTIC_CAPACITY: Final = 1024
_MAX_EXCEPTION_CHAIN_DEPTH: Final = 8
_LOWER_HEX: Final = frozenset("0123456789abcdef")


class RuntimeDiagnosticCategory(str, Enum):
    """Framework-owned, low-cardinality failure classifications."""

    EVENT_STORE_FAILURE = "event_store_failure"
    DELIVERY_STORE_FAILURE = "delivery_store_failure"
    DELIVERY_CLASSIFIER_FAILURE = "delivery_classifier_failure"
    REPLAY_STORE_FAILURE = "replay_store_failure"
    REPLAY_CHECKPOINT_FAILURE = "replay_checkpoint_failure"
    REPLAY_REPORT_FAILURE = "replay_report_failure"
    REPLAY_QUARANTINE_FAILURE = "replay_quarantine_failure"
    DIAGNOSTIC_SINK_FAILURE = "diagnostic_sink_failure"
    TELEMETRY_FAILURE = "telemetry_failure"


class RuntimeDiagnosticComponent(str, Enum):
    """Framework-owned component labels safe for local sinks and telemetry."""

    EVENT_PUBLISHER = "event_publisher"
    DELIVERY_CONSUMER_REGISTRY = "delivery_consumer_registry"
    DELIVERY_RUNTIME = "delivery_runtime"
    REPLAY_ENGINE = "replay_engine"
    EVENT_RUNTIME_FALLBACK = "event_runtime_fallback"


class RuntimeDiagnosticOperation(str, Enum):
    """Closed, low-cardinality operation labels for runtime diagnostics."""

    PUBLISH = "publish"
    SUBSCRIPTION_REGISTRATION = "subscription_registration"
    SUBSCRIPTION_STATUS_UPDATE = "subscription_status_update"
    SUBSCRIPTION_LOOKUP = "subscription_lookup"
    DELIVERY_CLAIM = "delivery_claim"
    DELIVERY_STATS = "delivery_stats"
    DEAD_LETTER_LOOKUP = "dead_letter_lookup"
    DEAD_LETTER_REQUEUE = "dead_letter_requeue"
    AUTHORIZED_REDELIVERY = "authorized_redelivery"
    DELIVERY_SETTLEMENT = "delivery_settlement"
    CONSUMER_ERROR_CLASSIFICATION = "consumer_error_classification"
    REPLAY_BEGIN_FAILED = "replay_begin_failed"
    REPLAY_RUNNING_REPORT_UPDATE_FAILED = "replay_running_report_update_failed"
    REPLAY_CHECKPOINT_READ_FAILED = "replay_checkpoint_read_failed"
    REPLAY_SUCCESS_REPORT_UPDATE_FAILED = "replay_success_report_update_failed"
    SOURCE_READ_FAILED = "source_read_failed"
    REPLAY_PROGRESS_REPORT_UPDATE_FAILED = "replay_progress_report_update_failed"
    QUARANTINE_WRITE = "quarantine_write"
    REPLAY_FAILURE_REPORT_UPDATE_FAILED = "replay_failure_report_update_failed"
    REPLAY_CHECKPOINT_WRITE_FAILED = "replay_checkpoint_write_failed"
    REPLAY_BEGIN_REPORT_INVALID = "replay_begin_report_invalid"
    REPLAY_REPORT_UPDATE_INVALID = "replay_report_update_invalid"
    REPLAY_CHECKPOINT_READ_INVALID = "replay_checkpoint_read_invalid"
    SOURCE_READ_INVALID = "source_read_invalid"
    REPLAY_CHECKPOINT_WRITE_INVALID = "replay_checkpoint_write_invalid"
    LOCAL_SINK = "local_sink"
    TELEMETRY_COUNTER = "telemetry_counter"


@dataclass(frozen=True, slots=True)
class RuntimeFallbackDiagnostic:
    """A bounded process diagnostic containing no caller or event values."""

    category: RuntimeDiagnosticCategory
    component: str
    operation: str
    occurred_at: datetime
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", RuntimeDiagnosticCategory(self.category))
        object.__setattr__(
            self,
            "component",
            RuntimeDiagnosticComponent(self.component).value,
        )
        object.__setattr__(
            self,
            "operation",
            RuntimeDiagnosticOperation(self.operation).value,
        )
        occurred_at = self.occurred_at
        if not isinstance(occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "occurred_at", occurred_at.astimezone(UTC))
        fingerprint = str(self.fingerprint).lower()
        if not _is_sha256_fingerprint(fingerprint):
            raise ValueError("fingerprint must be sha256:<64 lowercase hex>")
        object.__setattr__(self, "fingerprint", fingerprint)

    @property
    def deduplication_key(self) -> tuple[str, str, str, str]:
        return (
            self.category.value,
            self.component,
            self.operation,
            self.fingerprint,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category.value,
            "component": self.component,
            "operation": self.operation,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "fingerprint": self.fingerprint,
        }


RuntimeDiagnosticSink = Callable[[RuntimeFallbackDiagnostic], None]


class LocalRuntimeDiagnosticFallback:
    """Bounded, nonrecursive fallback independent of the event runtime.

    The in-process ring is always the first and authoritative fallback. Optional
    local sinks and telemetry counters receive only the immutable safe record.
    Their failures are retained locally when spare capacity exists, never evict
    the originating diagnostic, and are not sent back through either callback,
    an event store, or a bus.
    """

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_DIAGNOSTIC_CAPACITY,
        sink: RuntimeDiagnosticSink | None = None,
        telemetry_counter: RuntimeDiagnosticSink | None = None,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise TypeError("capacity must be an integer")
        if capacity < 1 or capacity > MAX_DIAGNOSTIC_CAPACITY:
            raise ValueError(
                f"capacity must be between 1 and {MAX_DIAGNOSTIC_CAPACITY}"
            )
        if sink is not None and not callable(sink):
            raise TypeError("sink must be callable")
        if telemetry_counter is not None and not callable(telemetry_counter):
            raise TypeError("telemetry_counter must be callable")
        self._capacity = capacity
        self._sink = sink
        self._telemetry_counter = telemetry_counter
        self._records: OrderedDict[
            tuple[str, str, str, str], RuntimeFallbackDiagnostic
        ] = OrderedDict()
        self._lock = RLock()
        self._reentrancy = local()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def degraded(self) -> bool:
        with self._lock:
            return bool(self._records)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def snapshot(self) -> tuple[RuntimeFallbackDiagnostic, ...]:
        with self._lock:
            return tuple(self._records.values())

    def record(
        self,
        *,
        category: RuntimeDiagnosticCategory,
        component: RuntimeDiagnosticComponent,
        operation: RuntimeDiagnosticOperation,
        error: Exception,
    ) -> RuntimeFallbackDiagnostic | None:
        """Record at most one diagnostic for a safe failure fingerprint.

        Ordinary callback and internal failures are contained so this method
        cannot replace the business/store exception being reported. Process
        control exceptions are deliberately not caught.
        """

        if getattr(self._reentrancy, "active", False):
            return None
        self._reentrancy.active = True
        try:
            if not isinstance(error, Exception):
                return None
            diagnostic = _diagnostic(
                category=category,
                component=component,
                operation=operation,
                error=error,
            )
            if not self._insert(diagnostic):
                return diagnostic
            self._notify(
                self._sink,
                diagnostic,
                failure_category=RuntimeDiagnosticCategory.DIAGNOSTIC_SINK_FAILURE,
                failure_operation=RuntimeDiagnosticOperation.LOCAL_SINK,
            )
            self._notify(
                self._telemetry_counter,
                diagnostic,
                failure_category=RuntimeDiagnosticCategory.TELEMETRY_FAILURE,
                failure_operation=RuntimeDiagnosticOperation.TELEMETRY_COUNTER,
            )
            return diagnostic
        except Exception:
            return None
        finally:
            self._reentrancy.active = False

    def _insert(self, diagnostic: RuntimeFallbackDiagnostic) -> bool:
        key = diagnostic.deduplication_key
        with self._lock:
            if key in self._records:
                return False
            self._records[key] = diagnostic
            while len(self._records) > self._capacity:
                self._records.popitem(last=False)
        return True

    def _insert_secondary(self, diagnostic: RuntimeFallbackDiagnostic) -> bool:
        """Insert callback-failure evidence only when it cannot evict a primary."""

        key = diagnostic.deduplication_key
        with self._lock:
            if key in self._records or len(self._records) >= self._capacity:
                return False
            self._records[key] = diagnostic
        return True

    def _notify(
        self,
        callback: RuntimeDiagnosticSink | None,
        diagnostic: RuntimeFallbackDiagnostic,
        *,
        failure_category: RuntimeDiagnosticCategory,
        failure_operation: RuntimeDiagnosticOperation,
    ) -> None:
        if callback is None:
            return
        try:
            callback(diagnostic)
        except Exception as error:
            # This path is intentionally local-only. Calling either callback
            # again would make the fallback recursively dependent on itself.
            try:
                self._insert_secondary(
                    _diagnostic(
                        category=failure_category,
                        component=RuntimeDiagnosticComponent.EVENT_RUNTIME_FALLBACK,
                        operation=failure_operation,
                        error=error,
                    )
                )
            except Exception:
                return


def _diagnostic(
    *,
    category: RuntimeDiagnosticCategory,
    component: RuntimeDiagnosticComponent,
    operation: RuntimeDiagnosticOperation,
    error: Exception,
) -> RuntimeFallbackDiagnostic:
    normalized_category = RuntimeDiagnosticCategory(category)
    normalized_component = RuntimeDiagnosticComponent(component).value
    normalized_operation = RuntimeDiagnosticOperation(operation).value
    return RuntimeFallbackDiagnostic(
        category=normalized_category,
        component=normalized_component,
        operation=normalized_operation,
        occurred_at=datetime.now(UTC),
        fingerprint=_failure_fingerprint(
            normalized_category,
            normalized_component,
            normalized_operation,
            error,
        ),
    )


def _failure_fingerprint(
    category: RuntimeDiagnosticCategory,
    component: str,
    operation: str,
    error: Exception,
) -> str:
    digest = sha256()
    digest.update(b"newsroom-event-runtime-fallback-v1\0")
    for value in (category.value, component, operation):
        digest.update(value.encode("ascii"))
        digest.update(b"\0")

    current: BaseException | None = error
    seen: set[int] = set()
    depth = 0
    while (
        current is not None
        and id(current) not in seen
        and depth < _MAX_EXCEPTION_CHAIN_DEPTH
    ):
        seen.add(id(current))
        error_type = type(current)
        # Type identity is useful for correlation but is hashed rather than
        # retained. Exception messages, args, locals, and traceback frames are
        # never read.
        digest.update(error_type.__module__.encode("utf-8", errors="replace"))
        digest.update(b".")
        digest.update(error_type.__qualname__.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        current = cause
        depth += 1
    return f"sha256:{digest.hexdigest()}"


def _is_sha256_fingerprint(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in _LOWER_HEX for character in value[7:])
    )


__all__ = [
    "DEFAULT_DIAGNOSTIC_CAPACITY",
    "LocalRuntimeDiagnosticFallback",
    "MAX_DIAGNOSTIC_CAPACITY",
    "RuntimeDiagnosticCategory",
    "RuntimeDiagnosticComponent",
    "RuntimeDiagnosticOperation",
    "RuntimeDiagnosticSink",
    "RuntimeFallbackDiagnostic",
]
