from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.events.canonical import (
    DEFAULT_MAX_EXTENSION_BYTES,
    DEFAULT_MAX_EXTENSION_COUNT,
    DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
    BusinessContext,
    ProducerIdentity,
    canonical_json_bytes,
    checksum_for,
)
from framework.events.errors import (
    EventExtensionLimitError,
    EventPayloadTooLargeError,
    EventStoreCapacityError,
)
from framework.events.runtime import (
    CheckpointKey,
    DeliveryClaimRequest,
    DeliveryLimits,
    DeliveryQuery,
    DeliveryState,
    DurableDeliveryRuntime,
    DurableSubscription,
    LeasePolicy,
    ReplayMode,
    ReplayStartRequest,
    StreamReadRequest,
    SubscriptionFilter,
    SubscriptionStart,
    SubscriptionStartPolicy,
)
from framework.events.runtime.publisher import EventPublishRequest, EventRuntime
from framework.events.runtime.replay_engine import (
    DeterministicReplayEngine,
    ReplayReducerRegistration,
    ReplayReducerRegistry,
)
from framework.events.schema import (
    EventSchemaCatalog,
    EventSchemaRegistration,
    default_event_schema_catalog,
)
from framework.events.subscriber import ConsumerDeliveryContext, ConsumerOutcome
from framework.shared.json import stable_json_dumps
from infrastructure.storage.events.postgres import (
    DEFAULT_POOL_MAX_SIZE,
    DEFAULT_POOL_MIN_SIZE,
    DEFAULT_POOL_TIMEOUT_SECONDS,
    PostgresDurableEventStore,
)
from infrastructure.storage.events.replay_checkpoints import SQLiteReplayCheckpointStore
from infrastructure.storage.events.sqlite import SQLiteEventStore


EVIDENCE_SCHEMA = "newsroom.durable-event-benchmark/v2"
BENCHMARK_EVENT_TYPE = "io.newsroom.event.benchmark"
BENCHMARK_DATA_SCHEMA = "io.newsroom.event.benchmark/v1"
BENCHMARK_TENANT_PREFIX = "tenant-event-benchmark"
CANONICAL_EVENT_TARGET_BYTES = 4 * 1024
FIXED_DURATION_SECONDS = 600
FIXED_READ_REPLAY_EVENT_COUNT = 10_000
SQLITE_TARGET_RATE = 25
POSTGRES_TARGET_RATE = 100
POSTGRES_WRITER_COUNT = 8
RECOVERY_LEASE_SECONDS = 5.0
COMMITTED_RECOVERY_TIMEOUT_SECONDS = 300
DELIVERY_PROBE_EVENT_COUNT = 100
EXPECTED_POSTGRES_CLEANUP_SCOPE_COUNT = 5
_OCCURRED_AT_BASE = datetime(2026, 7, 17, tzinfo=UTC)


class BenchmarkFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class _DeliveryResult:
    acknowledged: int
    duplicate_consumer_calls: int
    dispatch_errors: Mapping[str, int]
    end_to_end_latencies_ms: tuple[float, ...]
    batch_latencies_ms: tuple[float, ...]
    elapsed_seconds: float
    peak_pending_estimate: int
    pending_after_drain: int
    checkpoint_mismatches: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledged": self.acknowledged,
            "duplicate_consumer_calls": self.duplicate_consumer_calls,
            "dispatch_errors": dict(self.dispatch_errors),
            "end_to_end_latency_ms": _latency_summary_optional(
                self.end_to_end_latencies_ms
            ),
            "batch_latency_ms": _latency_summary_optional(self.batch_latencies_ms),
            "elapsed_seconds": self.elapsed_seconds,
            "achieved_rate_events_per_second": (
                self.acknowledged / self.elapsed_seconds
                if self.elapsed_seconds > 0
                else 0.0
            ),
            "peak_pending_estimate": self.peak_pending_estimate,
            "pending_after_drain": self.pending_after_drain,
            "checkpoint_mismatches": self.checkpoint_mismatches,
        }


@dataclass(frozen=True)
class _WorkloadResult:
    name: str
    backend: str
    duration_seconds: float
    target_rate: float
    writer_count: int
    attempted: int
    committed: int
    errors: Mapping[str, int]
    latencies_ms: tuple[float, ...]
    stream_count: int
    lost_events: int
    duplicate_sequences: int
    sequence_gaps: int
    checksum_failures: int
    canonical_event_sizes_bytes: tuple[int, ...]
    inline_payload_sizes_bytes: tuple[int, ...]
    committed_recovery: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        error_count = sum(self.errors.values())
        return {
            "name": self.name,
            "backend": self.backend,
            "duration_seconds": self.duration_seconds,
            "target_rate_events_per_second": self.target_rate,
            "writer_count": self.writer_count,
            "attempted": self.attempted,
            "committed": self.committed,
            "errors": error_count,
            "error_classes": dict(self.errors),
            "achieved_rate_events_per_second": (
                self.committed / self.duration_seconds
                if self.duration_seconds > 0
                else 0.0
            ),
            "append_latency_ms": _latency_summary(self.latencies_ms),
            "stream_count": self.stream_count,
            "lost_events": self.lost_events,
            "duplicate_sequences": self.duplicate_sequences,
            "sequence_gaps": self.sequence_gaps,
            "checksum_failures": self.checksum_failures,
            "canonical_event_size_bytes": _size_summary(
                self.canonical_event_sizes_bytes
            ),
            "inline_payload_size_bytes": _size_summary(
                self.inline_payload_sizes_bytes
            ),
            "committed_recovery": dict(self.committed_recovery),
        }


@dataclass(frozen=True)
class _PostgresCleanupScope:
    tenant_id: str
    subscription_ids: tuple[str, ...]
    stream_ids: tuple[str, ...]


class _StoreRegistry:
    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._stores: list[Any] = []

    def create(self) -> Any:
        store = self._factory()
        self._stores.append(store)
        return store

    def close(self) -> None:
        while self._stores:
            store = self._stores.pop()
            close = getattr(store, "close", None)
            if callable(close):
                close()


class _DeliveryTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._publish_started: dict[str, float] = {}
        self._committed = 0
        self._consumer_calls: list[str] = []
        self._latencies_ms: list[float] = []
        self._batch_latencies_ms: list[float] = []
        self._dispatch_errors: Counter[str] = Counter()
        self._peak_pending = 0

    def publish_started(self, event_id: str, started: float) -> None:
        with self._lock:
            self._publish_started[event_id] = started

    def publish_committed(self) -> None:
        with self._lock:
            self._committed += 1
            self._update_peak_pending()

    def consumed(self, event_id: str, completed: float) -> None:
        with self._lock:
            started = self._publish_started.get(event_id)
            if started is not None:
                self._latencies_ms.append(max(0.0, completed - started) * 1000)
            self._consumer_calls.append(event_id)
            self._update_peak_pending()

    def batch_completed(self, latency_ms: float) -> None:
        with self._lock:
            self._batch_latencies_ms.append(latency_ms)

    def dispatch_failed(self, error: BaseException) -> None:
        with self._lock:
            self._dispatch_errors[type(error).__name__] += 1

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return self._committed, len(self._consumer_calls)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            duplicates = len(self._consumer_calls) - len(set(self._consumer_calls))
            return {
                "committed": self._committed,
                "acknowledged": len(self._consumer_calls),
                "duplicate_consumer_calls": duplicates,
                "latencies_ms": tuple(self._latencies_ms),
                "batch_latencies_ms": tuple(self._batch_latencies_ms),
                "dispatch_errors": dict(self._dispatch_errors),
                "peak_pending": self._peak_pending,
            }

    def _update_peak_pending(self) -> None:
        pending = max(0, self._committed - len(self._consumer_calls))
        self._peak_pending = max(self._peak_pending, pending)


class _AckConsumer:
    def __init__(self, consumer_id: str, tracker: _DeliveryTracker) -> None:
        self.consumer_id = consumer_id
        self._tracker = tracker

    def consume(
        self,
        event: Any,
        context: ConsumerDeliveryContext,
    ) -> ConsumerOutcome:
        del context
        self._tracker.consumed(event.event_id, time.perf_counter())
        return ConsumerOutcome.ack()


def run_benchmark(
    *,
    workspace: str | Path,
    postgres_dsn: str | None,
    duration_seconds: int = FIXED_DURATION_SECONDS,
    read_replay_event_count: int = FIXED_READ_REPLAY_EVENT_COUNT,
    evidence_path: str | Path | None = None,
    qualification: bool = True,
) -> dict[str, Any]:
    _validate_run_configuration(
        duration_seconds=duration_seconds,
        read_replay_event_count=read_replay_event_count,
        postgres_dsn=postgres_dsn,
        qualification=qualification,
    )
    postgres_metadata = (
        None if postgres_dsn is None else _postgres_metadata(postgres_dsn)
    )
    _validate_postgres_target(
        postgres_metadata,
        qualification=qualification,
    )
    root = _prepare_workspace(workspace)
    evidence_target = (
        root / "benchmark-evidence.json"
        if evidence_path is None
        else Path(evidence_path).resolve(strict=False)
    )
    catalog = _benchmark_catalog()
    padding_bytes, calibration = _calibrate_payload_padding(root, catalog)
    started_at = datetime.now(UTC)

    sqlite_database = root / "sqlite" / "events.sqlite3"
    sqlite_store = SQLiteEventStore(sqlite_database)
    sqlite_scope = uuid4().hex
    sqlite_result = _run_append_workload(
        name="sqlite_single_stream",
        backend="sqlite",
        store_factory=lambda: SQLiteEventStore(sqlite_database),
        duration_seconds=duration_seconds,
        target_rate=SQLITE_TARGET_RATE,
        writer_count=1,
        scope=sqlite_scope,
        stream_ids=(_stream_id(sqlite_scope, 0),),
        catalog=catalog,
        padding_bytes=padding_bytes,
        committed_recovery=lambda streams, tenant, expected: (
            _probe_committed_recovery_subprocess(
                backend="sqlite",
                database=sqlite_database,
                stream_ids=streams,
                tenant_id=tenant,
                expected_count=expected,
            )
        ),
    )

    backlog_limits: list[dict[str, Any]] = []
    dispatcher_recovery: list[dict[str, Any]] = []
    delivery_results: list[dict[str, Any]] = []
    postgres_results: list[_WorkloadResult] = []
    postgres_cleanup: dict[str, Any] = {
        "executed": False,
        "scopes": [],
        "deleted_rows": {},
        "rows_after_cleanup": {},
        "passed": False,
    }
    if postgres_dsn:
        cleanup_scopes: list[_PostgresCleanupScope] = []
        postgres_stores = _StoreRegistry(
            lambda: PostgresDurableEventStore(postgres_dsn)
        )
        try:
            for name, stream_count in (
                ("postgres_same_stream", 1),
                ("postgres_multiple_streams", POSTGRES_WRITER_COUNT),
            ):
                scope = uuid4().hex
                streams = tuple(
                    _stream_id(scope, index) for index in range(stream_count)
                )
                cleanup_scopes.append(
                    _PostgresCleanupScope(
                        tenant_id=_tenant_id(scope),
                        subscription_ids=(f"benchmark-subscription:{scope}",),
                        stream_ids=streams,
                    )
                )
                postgres_results.append(
                    _run_append_workload(
                        name=name,
                        backend="postgresql",
                        store_factory=postgres_stores.create,
                        duration_seconds=duration_seconds,
                        target_rate=POSTGRES_TARGET_RATE,
                        writer_count=POSTGRES_WRITER_COUNT,
                        scope=scope,
                        stream_ids=streams,
                        catalog=catalog,
                        padding_bytes=padding_bytes,
                        committed_recovery=lambda recovery_streams, tenant, expected,
                        dsn=postgres_dsn: _probe_committed_recovery_subprocess(
                            backend="postgresql",
                            database=None,
                            stream_ids=recovery_streams,
                            tenant_id=tenant,
                            expected_count=expected,
                            postgres_dsn=dsn,
                        ),
                    )
                )

            delivery_scope = uuid4().hex
            delivery_streams = tuple(
                _stream_id(delivery_scope, index)
                for index in range(DELIVERY_PROBE_EVENT_COUNT)
            )
            cleanup_scopes.append(
                _PostgresCleanupScope(
                    tenant_id=_tenant_id(delivery_scope),
                    subscription_ids=(f"benchmark-delivery:{delivery_scope}",),
                    stream_ids=delivery_streams,
                )
            )
            delivery_results.append(
                _run_delivery_workload(
                    backend="postgresql",
                    store_factory=postgres_stores.create,
                    catalog=catalog,
                    scope=delivery_scope,
                )
            )

            backlog_scope = uuid4().hex
            cleanup_scopes.append(
                _PostgresCleanupScope(
                    tenant_id=_tenant_id(backlog_scope),
                    subscription_ids=(f"benchmark-backlog:{backlog_scope}",),
                    stream_ids=(_stream_id(backlog_scope, 0),),
                )
            )
            backlog_limits.append(
                _run_backlog_limit_probe(
                    backend="postgresql",
                    store_factory=postgres_stores.create,
                    catalog=catalog,
                    scope=backlog_scope,
                )
            )

            recovery_scope = uuid4().hex
            cleanup_scopes.append(
                _PostgresCleanupScope(
                    tenant_id=_tenant_id(recovery_scope),
                    subscription_ids=(f"benchmark-recovery:{recovery_scope}",),
                    stream_ids=(_stream_id(recovery_scope, 0),),
                )
            )
            dispatcher_recovery.append(
                _run_dispatcher_recovery_probe(
                    backend="postgresql",
                    store_factory=postgres_stores.create,
                    catalog=catalog,
                    database=None,
                    postgres_dsn=postgres_dsn,
                    scope=recovery_scope,
                )
            )
        finally:
            postgres_stores.close()
            postgres_cleanup = _cleanup_postgres_scopes(
                postgres_dsn,
                cleanup_scopes,
            )

    read_replay = _run_read_replay_workload(
        root=root,
        catalog=catalog,
        event_count=read_replay_event_count,
        padding_bytes=padding_bytes,
    )
    size_limits = _run_size_limit_probe(root=root, catalog=catalog)
    delivery_results.insert(
        0,
        _run_delivery_workload(
            backend="sqlite",
            store_factory=lambda: SQLiteEventStore(
                root / "delivery" / "sqlite-delivery.sqlite3"
            ),
            catalog=catalog,
        ),
    )
    backlog_limits.insert(
        0,
        _run_backlog_limit_probe(
            backend="sqlite",
            store_factory=lambda: SQLiteEventStore(
                root / "limits" / "sqlite-backlog.sqlite3"
            ),
            catalog=catalog,
        ),
    )
    dispatcher_recovery.insert(
        0,
        _run_dispatcher_recovery_probe(
            backend="sqlite",
            store_factory=lambda: SQLiteEventStore(
                root / "recovery" / "sqlite-delivery.sqlite3"
            ),
            catalog=catalog,
            database=root / "recovery" / "sqlite-delivery.sqlite3",
        ),
    )

    finished_at = datetime.now(UTC)
    results = [sqlite_result, *postgres_results]
    machine = _machine_metadata(root)
    sqlite_metadata = _sqlite_metadata(sqlite_store, sqlite_database)
    gates = _evaluate_gates(
        results=results,
        read_replay=read_replay,
        size_limits=size_limits,
        delivery_results=delivery_results,
        backlog_limits=backlog_limits,
        dispatcher_recovery=dispatcher_recovery,
        duration_seconds=duration_seconds,
        read_replay_event_count=read_replay_event_count,
        machine=machine,
        sqlite_metadata=sqlite_metadata,
        postgres_metadata=postgres_metadata,
        postgres_cleanup=postgres_cleanup,
    )
    correctness_passed = all(gates["correctness"].values())
    slo_passed = all(gates["slo"].values())
    qualification_passed = all(gates["qualification"].values())
    if correctness_passed and slo_passed and qualification_passed:
        overall_status = "passed"
    elif not qualification and correctness_passed:
        overall_status = "smoke_passed"
    else:
        overall_status = "failed"

    evidence: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "run_kind": "qualification" if qualification else "smoke",
        "started_at": _utc_text(started_at),
        "finished_at": _utc_text(finished_at),
        "workload": {
            "duration_seconds": duration_seconds,
            "canonical_event_target_bytes": CANONICAL_EVENT_TARGET_BYTES,
            "payload_padding_bytes": padding_bytes,
            "payload_calibration": calibration,
            "sqlite": {
                "writers": 1,
                "rate_events_per_second": SQLITE_TARGET_RATE,
                "stream_modes": ["single_stream"],
            },
            "postgresql": {
                "writers": POSTGRES_WRITER_COUNT,
                "aggregate_rate_events_per_second": POSTGRES_TARGET_RATE,
                "stream_modes": ["same_stream", "multiple_streams"],
            },
            "read_replay_event_count": read_replay_event_count,
            "dispatcher": {
                "consumer_outcome": "ACK",
                "event_count_per_backend": DELIVERY_PROBE_EVENT_COUNT,
                "stream_count_per_backend": DELIVERY_PROBE_EVENT_COUNT,
                "batch_and_in_flight": DeliveryLimits().batch_size,
            },
        },
        "machine": machine,
        "versions": _version_metadata(),
        "configuration": {
            "sqlite": sqlite_metadata,
            "postgresql": postgres_metadata,
            "runtime_defaults": {
                "lease_duration_seconds": LeasePolicy().duration_seconds,
                "delivery_limits": _delivery_limits_dict(DeliveryLimits()),
                "inline_payload_limit_bytes": DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
                "extension_count_limit": DEFAULT_MAX_EXTENSION_COUNT,
                "extension_bytes_limit": DEFAULT_MAX_EXTENSION_BYTES,
            },
        },
        "append_results": [result.to_dict() for result in results],
        "delivery_results": delivery_results,
        "read_replay": read_replay,
        "limit_probes": {
            "size": size_limits,
            "backlog": backlog_limits,
        },
        "dispatcher_recovery": dispatcher_recovery,
        "postgres_cleanup": postgres_cleanup,
        "gates": gates,
        "overall_status": overall_status,
    }
    evidence["evidence_checksum"] = checksum_for(evidence)
    evidence_target.parent.mkdir(parents=True, exist_ok=True)
    evidence_target.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if overall_status == "failed" or (qualification and overall_status != "passed"):
        raise BenchmarkFailure(f"benchmark failed; evidence={evidence_target}")
    return evidence


def verify_evidence(
    path: str | Path,
    *,
    allow_smoke: bool = False,
) -> dict[str, Any]:
    evidence_path = Path(path).resolve(strict=True)
    value = json.loads(evidence_path.read_text(encoding="utf-8"))
    if value.get("schema") != EVIDENCE_SCHEMA:
        raise BenchmarkFailure("unexpected benchmark evidence schema")
    supplied = value.pop("evidence_checksum", None)
    expected = checksum_for(value)
    if supplied != expected:
        raise BenchmarkFailure("benchmark evidence checksum mismatch")
    value["evidence_checksum"] = supplied
    gates = value.get("gates")
    if not isinstance(gates, dict) or not all(
        isinstance(gates.get(section), dict)
        for section in ("correctness", "slo", "qualification")
    ):
        raise BenchmarkFailure("benchmark evidence gates are incomplete")
    status = value.get("overall_status")
    if status == "passed":
        if not all(
            all(bool(item) for item in gates[section].values())
            for section in ("correctness", "slo", "qualification")
        ):
            raise BenchmarkFailure("passed evidence contains a failed gate")
    elif status == "smoke_passed" and allow_smoke:
        if not all(bool(item) for item in gates["correctness"].values()):
            raise BenchmarkFailure("smoke evidence contains a failed correctness gate")
    else:
        raise BenchmarkFailure("benchmark evidence is not a qualified success")
    return value


def _run_append_workload(
    *,
    name: str,
    backend: str,
    store_factory: Callable[[], Any],
    duration_seconds: int,
    target_rate: int,
    writer_count: int,
    scope: str,
    stream_ids: tuple[str, ...],
    catalog: EventSchemaCatalog,
    padding_bytes: int,
    committed_recovery: Callable[[tuple[str, ...], str, int], Mapping[str, Any]],
) -> _WorkloadResult:
    total = duration_seconds * target_rate
    interval = 1.0 / target_rate
    tenant_id = _tenant_id(scope)
    with ExitStack() as stack:
        stores = [
            stack.enter_context(_owned_store(store_factory()))
            for _ in range(writer_count)
        ]
        runtimes = [
            EventRuntime(store=store, schema_catalog=catalog) for store in stores
        ]
        latencies = [0.0] * total
        errors: Counter[str] = Counter()
        error_lock = threading.Lock()
        start = time.perf_counter()

        def writer_loop(writer: int) -> None:
            runtime = runtimes[writer]
            for index in range(writer, total, writer_count):
                deadline = start + index * interval
                remaining = deadline - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)
                event_id = _event_id(scope, index)
                stream_id = stream_ids[index % len(stream_ids)]
                request = _publish_request(
                    event_id=event_id,
                    stream_id=stream_id,
                    value=index,
                    scope=scope,
                    tenant_id=tenant_id,
                    padding_bytes=padding_bytes,
                )
                before = time.perf_counter()
                try:
                    runtime.publish(request)
                except Exception as exc:
                    with error_lock:
                        errors[type(exc).__name__] += 1
                finally:
                    latencies[index] = (time.perf_counter() - before) * 1000

        with ThreadPoolExecutor(max_workers=writer_count) as executor:
            list(executor.map(writer_loop, range(writer_count)))
        elapsed = time.perf_counter() - start

        reader = stores[0]
        committed = 0
        duplicate_sequences = 0
        sequence_gaps = 0
        checksum_failures = 0
        canonical_sizes: list[int] = []
        payload_sizes: list[int] = []
        for stream_id in stream_ids:
            page_events = _read_all(reader, stream_id, tenant_id=tenant_id)
            committed += len(page_events)
            sequences = [event.stream_sequence for event in page_events]
            duplicate_sequences += len(sequences) - len(set(sequences))
            sequence_gaps += sum(
                actual != expected
                for actual, expected in zip(
                    sequences,
                    range(1, len(sequences) + 1),
                )
            )
            for event in page_events:
                try:
                    event.verify_integrity()
                    catalog.validate(
                        event.event_type,
                        event.data_schema,
                        event.payload,
                    )
                except Exception:
                    checksum_failures += 1
                canonical_sizes.append(len(canonical_json_bytes(event.to_dict())))
                payload_sizes.append(len(canonical_json_bytes(event.payload)))

        recovery = committed_recovery(stream_ids, tenant_id, committed)
        return _WorkloadResult(
            name=name,
            backend=backend,
            duration_seconds=elapsed,
            target_rate=target_rate,
            writer_count=writer_count,
            attempted=total,
            committed=committed,
            errors=dict(errors),
            latencies_ms=tuple(latencies),
            stream_count=len(stream_ids),
            lost_events=max(0, total - committed),
            duplicate_sequences=duplicate_sequences,
            sequence_gaps=sequence_gaps,
            checksum_failures=checksum_failures,
            canonical_event_sizes_bytes=tuple(canonical_sizes),
            inline_payload_sizes_bytes=tuple(payload_sizes),
            committed_recovery=dict(recovery),
        )


def _run_delivery_workload(
    *,
    backend: str,
    store_factory: Callable[[], Any],
    catalog: EventSchemaCatalog,
    scope: str | None = None,
) -> dict[str, Any]:
    scope = uuid4().hex if scope is None else scope
    tenant_id = _tenant_id(scope)
    store = store_factory()
    tracker = _DeliveryTracker()
    subscription = DurableSubscription(
        subscription_id=f"benchmark-delivery:{scope}",
        subscription_version=1,
        consumer_id=f"benchmark-delivery-consumer:{scope}",
        event_filter=SubscriptionFilter(
            event_types=frozenset({BENCHMARK_EVENT_TYPE}),
            data_schemas=frozenset({BENCHMARK_DATA_SCHEMA}),
        ),
        start=SubscriptionStart(policy=SubscriptionStartPolicy.LATEST),
        tenant_id=tenant_id,
    )
    delivery_runtime = DurableDeliveryRuntime(store)
    delivery_runtime.register(
        subscription,
        _AckConsumer(subscription.consumer_id, tracker),
    )
    publisher = EventRuntime(store=store, schema_catalog=catalog)
    publish_latencies: list[float] = []
    publish_errors: Counter[str] = Counter()
    for index in range(DELIVERY_PROBE_EVENT_COUNT):
        event_id = _event_id(scope, index)
        before = time.perf_counter()
        tracker.publish_started(event_id, before)
        try:
            publisher.publish(
                _publish_request(
                    event_id=event_id,
                    stream_id=_stream_id(scope, index),
                    value=index,
                    scope=scope,
                    tenant_id=tenant_id,
                    padding_bytes=32,
                )
            )
            tracker.publish_committed()
        except Exception as exc:
            publish_errors[type(exc).__name__] += 1
        finally:
            publish_latencies.append((time.perf_counter() - before) * 1000)

    pending_before = store.pending_delivery_stats(subscription.key).pending_count
    dispatch_started = time.perf_counter()
    dispatch_errors: Counter[str] = Counter()
    while True:
        committed, consumed = tracker.counts()
        if consumed >= committed:
            break
        before = time.perf_counter()
        try:
            result = delivery_runtime.dispatch_batch(
                subscription.key,
                lease_owner=f"benchmark-delivery-worker:{scope}",
            )
        except Exception as exc:
            dispatch_errors[type(exc).__name__] += 1
            break
        tracker.batch_completed((time.perf_counter() - before) * 1000)
        if not result.attempts:
            dispatch_errors["empty_delivery_batch"] += 1
            break
    dispatch_elapsed = time.perf_counter() - dispatch_started

    snapshot = tracker.snapshot()
    pending_after = store.pending_delivery_stats(subscription.key).pending_count
    checkpoint_mismatches = 0
    for index in range(DELIVERY_PROBE_EVENT_COUNT):
        checkpoint = store.get_checkpoint(
            CheckpointKey(
                subscription.subscription_id,
                subscription.subscription_version,
                _stream_id(scope, index),
                tenant_id,
            )
        )
        if checkpoint is None or checkpoint.highest_contiguous_terminal_sequence != 1:
            checkpoint_mismatches += 1
    combined_dispatch_errors = Counter(snapshot["dispatch_errors"])
    combined_dispatch_errors.update(dispatch_errors)
    result = _DeliveryResult(
        acknowledged=int(snapshot["acknowledged"]),
        duplicate_consumer_calls=int(snapshot["duplicate_consumer_calls"]),
        dispatch_errors=dict(combined_dispatch_errors),
        end_to_end_latencies_ms=tuple(snapshot["latencies_ms"]),
        batch_latencies_ms=tuple(snapshot["batch_latencies_ms"]),
        elapsed_seconds=dispatch_elapsed,
        peak_pending_estimate=int(snapshot["peak_pending"]),
        pending_after_drain=pending_after,
        checkpoint_mismatches=checkpoint_mismatches,
    )
    return {
        "backend": backend,
        "event_count": DELIVERY_PROBE_EVENT_COUNT,
        "stream_count": DELIVERY_PROBE_EVENT_COUNT,
        "configured_limits": _delivery_limits_dict(subscription.limits),
        "publish_errors": dict(publish_errors),
        "publish_latency_ms": _latency_summary(publish_latencies),
        "pending_before_dispatch": pending_before,
        **result.to_dict(),
        "passed": not publish_errors
        and result.acknowledged == DELIVERY_PROBE_EVENT_COUNT
        and result.duplicate_consumer_calls == 0
        and not result.dispatch_errors
        and result.pending_after_drain == 0
        and result.checkpoint_mismatches == 0,
    }


def _run_read_replay_workload(
    *,
    root: Path,
    catalog: EventSchemaCatalog,
    event_count: int,
    padding_bytes: int,
) -> dict[str, Any]:
    database = root / "read-replay" / "events.sqlite3"
    store = SQLiteEventStore(database)
    runtime = EventRuntime(store=store, schema_catalog=catalog)
    scope = uuid4().hex
    stream_id = _stream_id(scope, 0)
    tenant_id = _tenant_id(scope)
    for index in range(event_count):
        runtime.publish(
            _publish_request(
                event_id=_event_id(scope, index),
                stream_id=stream_id,
                value=index,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=padding_bytes,
            )
        )

    started = time.perf_counter()
    events = _read_all(store, stream_id, tenant_id=tenant_id)
    checksum_failures = 0
    for event in events:
        try:
            event.verify_integrity()
            catalog.validate(event.event_type, event.data_schema, event.payload)
        except Exception:
            checksum_failures += 1
    ordered_read_seconds = time.perf_counter() - started

    registry = ReplayReducerRegistry()
    registry.register(
        ReplayReducerRegistration(
            reducer_id="benchmark-counter",
            version="1",
            reducer=_count_reducer,
            initial_state={"count": 0},
        )
    )
    checkpoint_store = SQLiteReplayCheckpointStore(database)
    engine = DeterministicReplayEngine(
        store,
        catalog,
        registry,
        checkpoint_store,
        runtime_version="benchmark-runtime/v1",
        schema_catalog_version="benchmark-catalog/v1",
        clock=lambda: datetime.now(UTC),
        page_size=1000,
    )
    replay_started = time.perf_counter()
    replay = engine.rebuild_state(
        ReplayStartRequest(
            replay_id=f"benchmark-replay-{uuid4().hex}",
            mode=ReplayMode.REBUILD_STATE,
            source_stream_id=stream_id,
            requested_at=datetime.now(UTC),
            tenant_id=tenant_id,
        ),
        reducer_id="benchmark-counter",
        reducer_version="1",
    )
    replay_seconds = time.perf_counter() - replay_started
    return {
        "event_count": event_count,
        "ordered_read_seconds": ordered_read_seconds,
        "replay_seconds": replay_seconds,
        "read_with_schema_checksum_seconds": ordered_read_seconds,
        "state_count": replay.state["count"],
        "lost_events": event_count - len(events),
        "duplicate_sequences": len(events)
        - len({event.stream_sequence for event in events}),
        "checksum_failures": checksum_failures,
        "canonical_event_size_bytes": _size_summary(
            tuple(len(canonical_json_bytes(event.to_dict())) for event in events)
        ),
    }


def _run_size_limit_probe(
    *,
    root: Path,
    catalog: EventSchemaCatalog,
) -> dict[str, Any]:
    database = root / "limits" / "size.sqlite3"
    store = SQLiteEventStore(database)
    runtime = EventRuntime(store=store, schema_catalog=catalog)
    scope = uuid4().hex
    tenant_id = _tenant_id(scope)
    stream_id = _stream_id(scope, 0)

    cases = (
        (
            "inline_payload_over_64_kib",
            EventPayloadTooLargeError,
            _publish_request(
                event_id=_event_id(scope, 1),
                stream_id=stream_id,
                value=1,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
            ),
        ),
        (
            "extension_count_over_32",
            EventExtensionLimitError,
            _publish_request(
                event_id=_event_id(scope, 2),
                stream_id=stream_id,
                value=2,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=32,
                extensions={
                    f"io.newsroom.benchmark.field_{index}": index
                    for index in range(DEFAULT_MAX_EXTENSION_COUNT + 1)
                },
            ),
        ),
        (
            "extension_bytes_over_8_kib",
            EventExtensionLimitError,
            _publish_request(
                event_id=_event_id(scope, 3),
                stream_id=stream_id,
                value=3,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=32,
                extensions={
                    "io.newsroom.benchmark.large": "x"
                    * DEFAULT_MAX_EXTENSION_BYTES
                },
            ),
        ),
    )
    results: dict[str, bool] = {}
    for name, expected_error, request in cases:
        rejected = False
        try:
            runtime.publish(request)
        except expected_error:
            rejected = True
        results[name] = rejected and store.get_event(
            request.event_id,
            tenant_id=tenant_id,
        ) is None
    return {
        "backend": "sqlite",
        "configured_limits": {
            "inline_payload_bytes": DEFAULT_MAX_INLINE_PAYLOAD_BYTES,
            "extension_count": DEFAULT_MAX_EXTENSION_COUNT,
            "extension_bytes": DEFAULT_MAX_EXTENSION_BYTES,
        },
        "assertions": results,
        "passed": all(results.values()),
    }


def _run_backlog_limit_probe(
    *,
    backend: str,
    store_factory: Callable[[], Any],
    catalog: EventSchemaCatalog,
    scope: str | None = None,
) -> dict[str, Any]:
    store = store_factory()
    scope = uuid4().hex if scope is None else scope
    tenant_id = _tenant_id(scope)
    stream_id = _stream_id(scope, 0)
    limits = DeliveryLimits(
        batch_size=2,
        max_in_flight=2,
        max_concurrency=1,
        pending_warning_threshold=2,
        pending_hard_limit=3,
    )
    subscription = DurableSubscription(
        subscription_id=f"benchmark-backlog:{scope}",
        subscription_version=1,
        consumer_id=f"benchmark-backlog-consumer:{scope}",
        event_filter=SubscriptionFilter(
            event_types=frozenset({BENCHMARK_EVENT_TYPE})
        ),
        start=SubscriptionStart(policy=SubscriptionStartPolicy.LATEST),
        limits=limits,
        tenant_id=tenant_id,
    )
    tracker = _DeliveryTracker()
    DurableDeliveryRuntime(store).register(
        subscription,
        _AckConsumer(subscription.consumer_id, tracker),
    )
    runtime = EventRuntime(store=store, schema_catalog=catalog)
    for index in range(limits.pending_hard_limit):
        runtime.publish(
            _publish_request(
                event_id=_event_id(scope, index),
                stream_id=stream_id,
                value=index,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=32,
            )
        )
    rejected_id = _event_id(scope, limits.pending_hard_limit)
    rejected = False
    try:
        runtime.publish(
            _publish_request(
                event_id=rejected_id,
                stream_id=stream_id,
                value=limits.pending_hard_limit,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=32,
            )
        )
    except EventStoreCapacityError:
        rejected = True
    stats = store.pending_delivery_stats(subscription.key)
    assertions = {
        "hard_limit_rejected_before_commit": rejected
        and store.get_event(rejected_id, tenant_id=tenant_id) is None,
        "pending_count_bounded": stats.pending_count == limits.pending_hard_limit,
        "warning_threshold_reported": stats.warning_threshold_reached,
        "capacity_remaining_zero": stats.capacity_remaining == 0,
        "sequence_not_allocated_on_rejection": store.get_stream_high_watermark(
            stream_id,
            tenant_id=tenant_id,
        )
        == limits.pending_hard_limit,
    }
    return {
        "backend": backend,
        "limits": _delivery_limits_dict(limits),
        "stats": {
            "pending_count": stats.pending_count,
            "lag": stats.lag,
            "warning_threshold_reached": stats.warning_threshold_reached,
            "capacity_remaining": stats.capacity_remaining,
        },
        "assertions": assertions,
        "passed": all(assertions.values()),
    }


def _run_dispatcher_recovery_probe(
    *,
    backend: str,
    store_factory: Callable[[], Any],
    catalog: EventSchemaCatalog,
    database: Path | None,
    postgres_dsn: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    store = store_factory()
    scope = uuid4().hex if scope is None else scope
    tenant_id = _tenant_id(scope)
    stream_id = _stream_id(scope, 0)
    subscription = DurableSubscription(
        subscription_id=f"benchmark-recovery:{scope}",
        subscription_version=1,
        consumer_id=f"benchmark-recovery-consumer:{scope}",
        event_filter=SubscriptionFilter(
            event_types=frozenset({BENCHMARK_EVENT_TYPE})
        ),
        start=SubscriptionStart(policy=SubscriptionStartPolicy.LATEST),
        lease_policy=LeasePolicy(RECOVERY_LEASE_SECONDS),
        tenant_id=tenant_id,
    )
    tracker = _DeliveryTracker()
    DurableDeliveryRuntime(store).register(
        subscription,
        _AckConsumer(subscription.consumer_id, tracker),
    )
    EventRuntime(store=store, schema_catalog=catalog).publish(
        _publish_request(
            event_id=_event_id(scope, 0),
            stream_id=stream_id,
            value=0,
            scope=scope,
            tenant_id=tenant_id,
            padding_bytes=32,
        )
    )
    recovery_started = time.perf_counter()
    child = _claim_and_crash_subprocess(
        backend=backend,
        database=database,
        subscription=subscription,
        postgres_dsn=postgres_dsn,
    )
    claimed_records = store.list_deliveries(
        DeliveryQuery(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            tenant_id=tenant_id,
        )
    ).records
    claimed = claimed_records[0] if len(claimed_records) == 1 else None
    lease_expires_at = None if claimed is None else claimed.lease_expires_at
    if lease_expires_at is not None:
        remaining = (lease_expires_at - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            time.sleep(remaining + 0.15)

    restarted_store = store_factory()
    restarted_tracker = _DeliveryTracker()
    restarted_consumer = _AckConsumer(subscription.consumer_id, restarted_tracker)
    restarted_runtime = DurableDeliveryRuntime(restarted_store)
    restarted_runtime.consumers.attach(subscription.key, restarted_consumer)
    batch = restarted_runtime.dispatch_batch(
        subscription.key,
        lease_owner=f"benchmark-recovery-worker:{scope}",
        limit=1,
    )
    elapsed = time.perf_counter() - recovery_started
    pending_after = restarted_store.pending_delivery_stats(subscription.key).pending_count
    recovered_attempt = batch.attempts[0] if len(batch.attempts) == 1 else None
    assertions = {
        "worker_process_died_after_claim": child.returncode == 91,
        "lease_was_durable": claimed is not None
        and claimed.state is DeliveryState.CLAIMED
        and claimed.attempt_count == 1,
        "expired_claim_recovered": recovered_attempt is not None
        and recovered_attempt.state is DeliveryState.ACKED
        and recovered_attempt.attempt_count == 2,
        "pending_drained": pending_after == 0,
        "reclaimed_within_two_leases": elapsed <= 2 * RECOVERY_LEASE_SECONDS,
    }
    return {
        "backend": backend,
        "lease_duration_seconds": RECOVERY_LEASE_SECONDS,
        "worker_exit_code": child.returncode,
        "recovery_elapsed_seconds": elapsed,
        "recovery_limit_seconds": 2 * RECOVERY_LEASE_SECONDS,
        "assertions": assertions,
        "passed": all(assertions.values()),
    }


def _claim_and_crash_subprocess(
    *,
    backend: str,
    database: Path | None,
    subscription: DurableSubscription,
    postgres_dsn: str | None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "scripts.durable_event_benchmark",
        "_claim-and-crash",
        "--backend",
        backend,
        "--subscription-id",
        subscription.subscription_id,
        "--subscription-version",
        str(subscription.subscription_version),
        "--lease-owner",
        f"dead-benchmark-worker:{subscription.subscription_id}",
        "--lease-seconds",
        str(subscription.lease_policy.duration_seconds),
    ]
    if database is not None:
        command.extend(("--database", str(database)))
    environment = os.environ.copy()
    if postgres_dsn is not None:
        environment["NEWSROOM_BENCHMARK_RECOVERY_DSN"] = postgres_dsn
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _probe_committed_recovery_subprocess(
    *,
    backend: str,
    database: Path | None,
    stream_ids: tuple[str, ...],
    tenant_id: str,
    expected_count: int,
    postgres_dsn: str | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "scripts.durable_event_benchmark",
        "_probe-committed-recovery",
        "--backend",
        backend,
        "--tenant-id",
        tenant_id,
        "--expected-count",
        str(expected_count),
    ]
    for stream_id in stream_ids:
        command.extend(("--stream-id", stream_id))
    if database is not None:
        command.extend(("--database", str(database)))
    environment = os.environ.copy()
    if postgres_dsn is not None:
        environment["NEWSROOM_BENCHMARK_RECOVERY_DSN"] = postgres_dsn
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=COMMITTED_RECOVERY_TIMEOUT_SECONDS,
    )
    parsed: dict[str, Any] = {}
    if completed.returncode == 0:
        try:
            value = json.loads(completed.stdout)
            if isinstance(value, dict):
                parsed = value
        except json.JSONDecodeError:
            parsed = {}
    return {
        "process_exit_code": completed.returncode,
        "expected_count": expected_count,
        "recovered_count": parsed.get("recovered_count"),
        "duplicate_sequences": parsed.get("duplicate_sequences"),
        "checksum_failures": parsed.get("checksum_failures"),
        "all_committed_events_readable": completed.returncode == 0
        and parsed.get("recovered_count") == expected_count
        and parsed.get("duplicate_sequences") == 0
        and parsed.get("checksum_failures") == 0,
    }


def _probe_committed_recovery_command(args: argparse.Namespace) -> int:
    with _owned_store(
        _store_for_internal_command(args.backend, args.database)
    ) as store:
        catalog = _benchmark_catalog()
        recovered_count = 0
        duplicate_sequences = 0
        checksum_failures = 0
        for stream_id in args.stream_id:
            events = _read_all(store, stream_id, tenant_id=args.tenant_id)
            recovered_count += len(events)
            sequences = [event.stream_sequence for event in events]
            duplicate_sequences += len(sequences) - len(set(sequences))
            for event in events:
                try:
                    event.verify_integrity()
                    catalog.validate(
                        event.event_type,
                        event.data_schema,
                        event.payload,
                    )
                except Exception:
                    checksum_failures += 1
    output = {
        "recovered_count": recovered_count,
        "duplicate_sequences": duplicate_sequences,
        "checksum_failures": checksum_failures,
    }
    print(stable_json_dumps(output))
    return 0 if recovered_count == args.expected_count and not (
        duplicate_sequences or checksum_failures
    ) else 1


def _claim_and_crash_command(args: argparse.Namespace) -> int:
    store = _store_for_internal_command(args.backend, args.database)
    claims = store.claim_deliveries(
        DeliveryClaimRequest(
            subscription_id=args.subscription_id,
            subscription_version=args.subscription_version,
            lease_owner=args.lease_owner,
            requested_at=datetime.now(UTC),
            lease_duration_seconds=args.lease_seconds,
            limit=1,
        )
    )
    if len(claims) != 1:
        return 1
    os._exit(91)


def _store_for_internal_command(backend: str, database: str | None) -> Any:
    if backend == "sqlite":
        if not database:
            raise BenchmarkFailure("SQLite recovery command requires a database")
        return SQLiteEventStore(database, initialize=False)
    dsn = os.getenv("NEWSROOM_BENCHMARK_RECOVERY_DSN")
    if not dsn:
        raise BenchmarkFailure("PostgreSQL recovery command requires a DSN")
    return PostgresDurableEventStore(dsn)


def _calibrate_payload_padding(
    root: Path,
    catalog: EventSchemaCatalog,
) -> tuple[int, dict[str, int]]:
    store = SQLiteEventStore(root / "calibration" / "events.sqlite3")
    runtime = EventRuntime(store=store, schema_catalog=catalog)
    scope = "0" * 32
    tenant_id = _tenant_id(scope)
    stream_id = _stream_id(scope, 0)
    padding_bytes = 3_000
    measured_size = 0
    measured_payload_size = 0
    for attempt in range(5):
        event = runtime.publish(
            _publish_request(
                event_id=_event_id(scope, attempt),
                stream_id=stream_id,
                value=attempt,
                scope=scope,
                tenant_id=tenant_id,
                padding_bytes=padding_bytes,
            )
        )
        measured_size = len(canonical_json_bytes(event.to_dict()))
        measured_payload_size = len(canonical_json_bytes(event.payload))
        difference = CANONICAL_EVENT_TARGET_BYTES - measured_size
        if abs(difference) <= 1:
            break
        padding_bytes = max(1, padding_bytes + difference)
    return padding_bytes, {
        "sample_canonical_event_bytes": measured_size,
        "sample_inline_payload_bytes": measured_payload_size,
    }


def _publish_request(
    *,
    event_id: str,
    stream_id: str,
    value: int,
    scope: str,
    tenant_id: str,
    padding_bytes: int,
    extensions: Mapping[str, Any] | None = None,
) -> EventPublishRequest:
    return EventPublishRequest(
        event_id=event_id,
        event_type=BENCHMARK_EVENT_TYPE,
        data_schema=BENCHMARK_DATA_SCHEMA,
        source="scripts.durable_event_benchmark",
        occurred_at=_OCCURRED_AT_BASE + timedelta(microseconds=value + 1),
        stream_id=stream_id,
        business_context=BusinessContext(run_id=f"benchmark-{scope}"),
        producer=ProducerIdentity(component="durable-event-benchmark", version="2"),
        tenant_id=tenant_id,
        payload={"value": value, "padding": "x" * padding_bytes},
        extensions={} if extensions is None else extensions,
    )


def _benchmark_catalog() -> EventSchemaCatalog:
    catalog = default_event_schema_catalog()
    catalog.register(
        EventSchemaRegistration(
            event_type=BENCHMARK_EVENT_TYPE,
            data_schema=BENCHMARK_DATA_SCHEMA,
            json_schema={
                "type": "object",
                "required": ["value", "padding"],
                "properties": {
                    "value": {"type": "integer"},
                    "padding": {"type": "string"},
                },
                "additionalProperties": False,
            },
            current=True,
            authoritative_context_fields=("run_id",),
        )
    )
    return catalog


def _count_reducer(state: Any, event: Any) -> dict[str, int]:
    del event
    return {"count": state["count"] + 1}


def _read_all(store: Any, stream_id: str, *, tenant_id: str) -> list[Any]:
    events: list[Any] = []
    cursor = None
    while True:
        page = store.read_stream(
            StreamReadRequest(
                stream_id=stream_id,
                tenant_id=tenant_id,
                cursor=cursor,
                limit=1000,
            )
        )
        events.extend(page.events)
        cursor = page.next_cursor
        if cursor is None:
            return events


def _evaluate_gates(
    *,
    results: list[_WorkloadResult],
    read_replay: dict[str, Any],
    size_limits: dict[str, Any],
    delivery_results: list[dict[str, Any]],
    backlog_limits: list[dict[str, Any]],
    dispatcher_recovery: list[dict[str, Any]],
    duration_seconds: int,
    read_replay_event_count: int,
    machine: dict[str, Any],
    sqlite_metadata: dict[str, Any],
    postgres_metadata: dict[str, Any] | None,
    postgres_cleanup: dict[str, Any],
) -> dict[str, dict[str, bool]]:
    by_name = {result.name: result for result in results}
    correctness: dict[str, bool] = {
        "append_zero_loss_duplicate_gap_or_checksum_error": all(
            result.lost_events == 0
            and result.duplicate_sequences == 0
            and result.sequence_gaps == 0
            and result.checksum_failures == 0
            and sum(result.errors.values()) == 0
            for result in results
        ),
        "delivery_zero_loss_duplicate_or_checkpoint_error": bool(delivery_results)
        and all(bool(result["passed"]) for result in delivery_results),
        "committed_recovery_100_percent_readable": all(
            bool(result.committed_recovery.get("all_committed_events_readable"))
            for result in results
        ),
        "read_replay_zero_loss_duplicate_or_checksum_error": (
            read_replay["lost_events"] == 0
            and read_replay["duplicate_sequences"] == 0
            and read_replay["checksum_failures"] == 0
            and read_replay["state_count"] == read_replay_event_count
        ),
        "payload_and_extension_limits_enforced": bool(size_limits["passed"]),
        "backlog_limits_enforced": bool(backlog_limits)
        and all(bool(item["passed"]) for item in backlog_limits),
        "dispatcher_worker_death_recovered": bool(dispatcher_recovery)
        and all(bool(item["passed"]) for item in dispatcher_recovery),
        "postgres_benchmark_scopes_cleaned": postgres_metadata is None
        or bool(postgres_cleanup.get("passed")),
    }

    sqlite = by_name.get("sqlite_single_stream")
    postgres_same = by_name.get("postgres_same_stream")
    postgres_multiple = by_name.get("postgres_multiple_streams")
    slo: dict[str, bool] = {
        "sqlite_append_p95_le_25_ms": _latency_at_most(sqlite, 95, 25),
        "sqlite_append_p99_le_100_ms": _latency_at_most(sqlite, 99, 100),
        "sqlite_target_rate_sustained": _target_rate_sustained(sqlite),
        "postgres_same_stream_p95_le_50_ms": _latency_at_most(
            postgres_same, 95, 50
        ),
        "postgres_same_stream_p99_le_200_ms": _latency_at_most(
            postgres_same, 99, 200
        ),
        "postgres_same_stream_target_rate_sustained": _target_rate_sustained(
            postgres_same
        ),
        "postgres_multiple_streams_p95_le_50_ms": _latency_at_most(
            postgres_multiple, 95, 50
        ),
        "postgres_multiple_streams_p99_le_200_ms": _latency_at_most(
            postgres_multiple, 99, 200
        ),
        "postgres_multiple_streams_target_rate_sustained": (
            _target_rate_sustained(postgres_multiple)
        ),
        "ordered_read_10k_le_30_seconds": read_replay_event_count == 10_000
        and read_replay["read_with_schema_checksum_seconds"] <= 30,
        "sqlite_dispatcher_recovery_within_two_leases": _recovery_slo_passed(
            dispatcher_recovery,
            "sqlite",
        ),
        "postgres_dispatcher_recovery_within_two_leases": _recovery_slo_passed(
            dispatcher_recovery,
            "postgresql",
        ),
    }
    qualification_gates: dict[str, bool] = {
        "fixed_duration_600_seconds": duration_seconds == FIXED_DURATION_SECONDS,
        "fixed_read_replay_10000_events": (
            read_replay_event_count == FIXED_READ_REPLAY_EVENT_COUNT
        ),
        "sqlite_workload_executed": sqlite is not None,
        "postgres_same_stream_workload_executed": postgres_same is not None,
        "postgres_multiple_streams_workload_executed": postgres_multiple is not None,
        "sqlite_delivery_workload_executed": any(
            result["backend"] == "sqlite" for result in delivery_results
        ),
        "postgres_delivery_workload_executed": any(
            result["backend"] == "postgresql" for result in delivery_results
        ),
        "canonical_event_average_within_five_percent_of_4_kib": bool(results)
        and all(_canonical_size_matches_target(result) for result in results),
        "machine_cpu_ram_disk_evidence_complete": _machine_evidence_complete(machine),
        "sqlite_configuration_evidence_complete": all(
            key in sqlite_metadata
            for key in ("configured_pragma", "observed_pragma", "database_size_bytes")
        ),
        "postgres_configuration_evidence_complete": postgres_metadata is not None
        and bool(postgres_metadata.get("settings")),
        "postgres_cleanup_evidence_complete": bool(
            postgres_cleanup.get("executed")
        )
        and postgres_cleanup.get("scope_count")
        == EXPECTED_POSTGRES_CLEANUP_SCOPE_COUNT
        and bool(postgres_cleanup.get("passed")),
    }
    return {
        "correctness": correctness,
        "slo": slo,
        "qualification": qualification_gates,
    }


def _latency_at_most(
    result: _WorkloadResult | None,
    percentile: int,
    limit_ms: float,
) -> bool:
    if result is None:
        return False
    return _percentile(sorted(result.latencies_ms), percentile) <= limit_ms


def _target_rate_sustained(result: _WorkloadResult | None) -> bool:
    if result is None or result.duration_seconds <= 0:
        return False
    achieved = result.committed / result.duration_seconds
    return achieved >= result.target_rate * 0.98


def _canonical_size_matches_target(result: _WorkloadResult) -> bool:
    if not result.canonical_event_sizes_bytes:
        return False
    average = statistics.fmean(result.canonical_event_sizes_bytes)
    return 0.95 * CANONICAL_EVENT_TARGET_BYTES <= average <= (
        1.05 * CANONICAL_EVENT_TARGET_BYTES
    )


def _recovery_slo_passed(
    recoveries: Sequence[Mapping[str, Any]],
    backend: str,
) -> bool:
    matching = [item for item in recoveries if item.get("backend") == backend]
    return len(matching) == 1 and bool(
        matching[0]["assertions"]["reclaimed_within_two_leases"]
    )


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ValueError("latency summary requires at least one value")
    ordered = sorted(float(value) for value in values)
    return {
        "min": ordered[0],
        "mean": statistics.fmean(ordered),
        "p50": _percentile(ordered, 50),
        "p95": _percentile(ordered, 95),
        "p99": _percentile(ordered, 99),
        "max": ordered[-1],
    }


def _latency_summary_optional(
    values: Sequence[float],
) -> dict[str, float] | None:
    return None if not values else _latency_summary(values)


def _size_summary(values: Sequence[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    summary = _latency_summary(tuple(float(value) for value in values))
    return {"count": len(values), **summary}


def _percentile(ordered: Sequence[float], percentile: int) -> float:
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _machine_metadata(workspace: Path) -> dict[str, Any]:
    disk_usage = shutil.disk_usage(workspace)
    metadata: dict[str, Any] = {
        "hostname": platform.node(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "memory_bytes": _portable_memory_bytes(),
        "workspace_volume": {
            "root": Path(workspace.anchor).as_posix(),
            "size_bytes": disk_usage.total,
            "free_bytes": disk_usage.free,
        },
    }
    if sys.platform == "win32":
        metadata.update(_windows_machine_metadata(workspace))
    return metadata


def _portable_memory_bytes() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return int(page_size * page_count)
    except (AttributeError, OSError, ValueError):
        return None


def _windows_machine_metadata(workspace: Path) -> dict[str, Any]:
    script = (
        "$computer=Get-CimInstance Win32_ComputerSystem;"
        "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
        "$drive=[IO.Path]::GetPathRoot($env:NEWSROOM_BENCHMARK_WORKSPACE)."
        "TrimEnd([char]92);"
        "$volume=Get-CimInstance Win32_LogicalDisk | "
        "Where-Object DeviceID -eq $drive | Select-Object -First 1;"
        "$disk=Get-PhysicalDisk | Sort-Object DeviceId | Select-Object -First 1;"
        "[pscustomobject]@{model=$computer.Model;"
        "memory_bytes=$computer.TotalPhysicalMemory;cpu=$cpu.Name;"
        "cpu_cores=$cpu.NumberOfCores;logical_cpus=$cpu.NumberOfLogicalProcessors;"
        "disk_filesystem=$volume.FileSystem;disk_volume_size_bytes=$volume.Size;"
        "disk_volume_free_bytes=$volume.FreeSpace;disk_model=$disk.FriendlyName;"
        "disk_media_type=$disk.MediaType;disk_bus_type=$disk.BusType;"
        "disk_physical_size_bytes=$disk.Size}|ConvertTo-Json -Compress"
    )
    environment = os.environ.copy()
    environment["NEWSROOM_BENCHMARK_WORKSPACE"] = str(workspace)
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            timeout=20,
            env=environment,
        )
        value = json.loads(output)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _machine_evidence_complete(machine: Mapping[str, Any]) -> bool:
    cpu = machine.get("cpu") or machine.get("processor")
    memory = machine.get("memory_bytes")
    volume = machine.get("workspace_volume")
    return bool(
        machine.get("os")
        and cpu
        and isinstance(memory, int)
        and memory > 0
        and isinstance(volume, dict)
        and int(volume.get("size_bytes", 0)) > 0
    )


def _version_metadata() -> dict[str, Any]:
    import psycopg
    import psycopg_pool

    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "sqlite": sqlite3.sqlite_version,
        "psycopg": psycopg.__version__,
        "psycopg_pool": psycopg_pool.__version__,
    }


def _sqlite_metadata(store: SQLiteEventStore, database: Path) -> dict[str, Any]:
    with sqlite3.connect(database) as connection:
        observed = {
            "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
            "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
            "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
            "wal_autocheckpoint": int(
                connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
            ),
            "auto_vacuum": int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]),
        }
    return {
        "database": database.name,
        "configured_pragma": dict(store.durability_policy),
        "observed_pragma": observed,
        "database_size_bytes": database.stat().st_size,
    }


def _postgres_metadata(dsn: str) -> dict[str, Any]:
    import psycopg

    setting_names = (
        "server_version",
        "server_encoding",
        "TimeZone",
        "synchronous_commit",
        "fsync",
        "full_page_writes",
        "wal_level",
        "shared_buffers",
        "effective_cache_size",
        "work_mem",
        "max_connections",
        "checkpoint_timeout",
        "max_wal_size",
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database_name = str(cursor.fetchone()[0])
            settings: dict[str, str] = {}
            for name in setting_names:
                cursor.execute(f'SHOW "{name}"')
                settings[name] = str(cursor.fetchone()[0])
    return {
        "database_name": database_name,
        "driver": f"psycopg/{psycopg.__version__}",
        "connection_lifecycle": (
            "PostgresDurableEventStore instances share one bounded pool by "
            "normalized DSN and pool configuration; benchmark stores release "
            "their references explicitly"
        ),
        "connection_pool": {
            "scope": "shared_by_normalized_dsn_and_pool_configuration",
            "min_size": DEFAULT_POOL_MIN_SIZE,
            "max_size": DEFAULT_POOL_MAX_SIZE,
            "timeout_seconds": DEFAULT_POOL_TIMEOUT_SECONDS,
        },
        "settings": settings,
    }


def _cleanup_postgres_scopes(
    dsn: str,
    scopes: Sequence[_PostgresCleanupScope],
) -> dict[str, Any]:
    import psycopg

    normalized_scopes = tuple(scopes)
    identities = [
        {
            "tenant_id": scope.tenant_id,
            "subscription_ids": list(scope.subscription_ids),
            "stream_ids": list(scope.stream_ids),
        }
        for scope in normalized_scopes
    ]
    if len({scope.tenant_id for scope in normalized_scopes}) != len(
        normalized_scopes
    ):
        return {
            "executed": False,
            "scope_count": len(normalized_scopes),
            "scopes": identities,
            "reason_class": "duplicate_cleanup_tenant_scope",
            "passed": False,
        }

    scope_evidence: list[dict[str, Any]] = []
    try:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                for scope in normalized_scopes:
                    deleted_rows: dict[str, int] = {}
                    rows_after: dict[str, int] = {}
                    statements = _postgres_cleanup_statements(scope)
                    for table, where_clause, params in statements:
                        cursor.execute(
                            f"DELETE FROM {table} WHERE {where_clause}",  # noqa: S608
                            params,
                        )
                        deleted_rows[table] = int(cursor.rowcount)
                    for table, where_clause, params in statements:
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {table} "  # noqa: S608
                            f"WHERE {where_clause}",
                            params,
                        )
                        rows_after[table] = int(cursor.fetchone()[0])
                    scope_evidence.append(
                        {
                            "tenant_id": scope.tenant_id,
                            "subscription_ids": list(scope.subscription_ids),
                            "stream_ids": list(scope.stream_ids),
                            "deleted_rows": deleted_rows,
                            "rows_after_cleanup": rows_after,
                            "passed": all(count == 0 for count in rows_after.values()),
                        }
                    )
            connection.commit()
    except Exception as exc:
        return {
            "executed": True,
            "scope_count": len(normalized_scopes),
            "scopes": identities,
            "reason_class": type(exc).__name__,
            "passed": False,
        }
    return {
        "executed": True,
        "scope_count": len(normalized_scopes),
        "scopes": scope_evidence,
        "deleted_row_count": sum(
            sum(scope["deleted_rows"].values()) for scope in scope_evidence
        ),
        "rows_after_cleanup": sum(
            sum(scope["rows_after_cleanup"].values()) for scope in scope_evidence
        ),
        "passed": bool(scope_evidence)
        and all(bool(scope["passed"]) for scope in scope_evidence),
    }


def _postgres_cleanup_statements(
    scope: _PostgresCleanupScope,
) -> tuple[tuple[str, str, tuple[Any, ...]], ...]:
    subscriptions = list(scope.subscription_ids)
    streams = list(scope.stream_ids)
    tenant = scope.tenant_id
    return (
        (
            "event_redelivery_items",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        (
            "event_redelivery_reports",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        ("event_inbox", "tenant_id = %s", (tenant,)),
        (
            "event_dead_letters",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        (
            "event_deliveries",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        (
            "event_consumer_checkpoints",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        (
            "event_replay_checkpoints",
            "tenant_id = %s AND source_stream_id = ANY(%s)",
            (tenant, streams),
        ),
        (
            "event_replay_reports",
            "tenant_id = %s AND source_stream_id = ANY(%s)",
            (tenant, streams),
        ),
        (
            "event_subscription_status_audit",
            "subscription_id = ANY(%s)",
            (subscriptions,),
        ),
        (
            "event_subscription_stream_states",
            "tenant_id = %s AND subscription_id = ANY(%s) "
            "AND stream_id = ANY(%s)",
            (tenant, subscriptions, streams),
        ),
        (
            "event_subscriptions",
            "tenant_id = %s AND subscription_id = ANY(%s)",
            (tenant, subscriptions),
        ),
        ("event_quarantine", "tenant_id = %s", (tenant,)),
        (
            "durable_events",
            "tenant_id = %s AND stream_id = ANY(%s)",
            (tenant, streams),
        ),
        (
            "event_stream_sequences",
            "tenant_id = %s AND stream_id = ANY(%s)",
            (tenant, streams),
        ),
    )


def _delivery_limits_dict(limits: DeliveryLimits) -> dict[str, int]:
    return {
        "batch_size": limits.batch_size,
        "max_in_flight": limits.max_in_flight,
        "max_concurrency": limits.max_concurrency,
        "pending_warning_threshold": limits.pending_warning_threshold,
        "pending_hard_limit": limits.pending_hard_limit,
    }


def _owned_store(store: Any):
    close = getattr(store, "close", None)
    return closing(store) if callable(close) else nullcontext(store)


def _event_id(scope: str, index: int) -> str:
    return f"benchmark:{scope}:{index:08d}"


def _stream_id(scope: str, index: int) -> str:
    return f"benchmark:{scope}:{index}"


def _tenant_id(scope: str) -> str:
    return f"{BENCHMARK_TENANT_PREFIX}:{scope}"


def _validate_run_configuration(
    *,
    duration_seconds: int,
    read_replay_event_count: int,
    postgres_dsn: str | None,
    qualification: bool,
) -> None:
    if isinstance(duration_seconds, bool) or duration_seconds < 1:
        raise ValueError("duration_seconds must be a positive integer")
    if isinstance(read_replay_event_count, bool) or read_replay_event_count < 1:
        raise ValueError("read_replay_event_count must be a positive integer")
    if qualification and duration_seconds != FIXED_DURATION_SECONDS:
        raise BenchmarkFailure("qualification requires the fixed 600 second workload")
    if qualification and read_replay_event_count != FIXED_READ_REPLAY_EVENT_COUNT:
        raise BenchmarkFailure("qualification requires the fixed 10000 event replay")
    if qualification and not postgres_dsn:
        raise BenchmarkFailure("qualification requires NEWS_TEST_POSTGRES_DSN")


def _validate_postgres_target(
    metadata: Mapping[str, Any] | None,
    *,
    qualification: bool,
) -> None:
    if not qualification:
        return
    if metadata is None:
        raise BenchmarkFailure("qualification requires PostgreSQL metadata")
    database_name = str(metadata.get("database_name", "")).casefold()
    if "test" not in database_name and "benchmark" not in database_name:
        raise BenchmarkFailure(
            "qualification requires an isolated test or benchmark PostgreSQL database"
        )


def _prepare_workspace(value: str | Path) -> Path:
    path = Path(value).resolve(strict=False)
    if path.exists() and any(path.iterdir()):
        raise ValueError("benchmark workspace must be empty")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.durable_event_benchmark",
        description="Run the PRD durable-event fixed workload benchmark.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--workspace", required=True)
    run.add_argument("--evidence")
    run.add_argument("--postgres-dsn", default=os.getenv("NEWS_TEST_POSTGRES_DSN"))
    run.add_argument("--duration-seconds", type=int, default=FIXED_DURATION_SECONDS)
    run.add_argument(
        "--read-replay-events",
        type=int,
        default=FIXED_READ_REPLAY_EVENT_COUNT,
    )
    run.add_argument(
        "--smoke",
        action="store_true",
        help="allow a partial workload while keeping evidence non-qualifying",
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--allow-smoke", action="store_true")

    recovery = commands.add_parser("_probe-committed-recovery", help=argparse.SUPPRESS)
    recovery.add_argument("--backend", choices=("sqlite", "postgresql"), required=True)
    recovery.add_argument("--database")
    recovery.add_argument("--tenant-id", required=True)
    recovery.add_argument("--stream-id", action="append", required=True)
    recovery.add_argument("--expected-count", type=int, required=True)

    crash = commands.add_parser("_claim-and-crash", help=argparse.SUPPRESS)
    crash.add_argument("--backend", choices=("sqlite", "postgresql"), required=True)
    crash.add_argument("--database")
    crash.add_argument("--subscription-id", required=True)
    crash.add_argument("--subscription-version", type=int, required=True)
    crash.add_argument("--lease-owner", required=True)
    crash.add_argument("--lease-seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "_probe-committed-recovery":
        return _probe_committed_recovery_command(args)
    if args.command == "_claim-and-crash":
        return _claim_and_crash_command(args)

    evidence_path: Path | None = None
    try:
        if args.command == "run":
            evidence_path = (
                Path(args.evidence).resolve()
                if args.evidence
                else Path(args.workspace).resolve() / "benchmark-evidence.json"
            )
            evidence = run_benchmark(
                workspace=args.workspace,
                postgres_dsn=args.postgres_dsn,
                duration_seconds=args.duration_seconds,
                read_replay_event_count=args.read_replay_events,
                evidence_path=args.evidence,
                qualification=not args.smoke,
            )
        else:
            evidence_path = Path(args.evidence).resolve()
            evidence = verify_evidence(
                args.evidence,
                allow_smoke=args.allow_smoke,
            )
    except Exception as exc:
        print(
            stable_json_dumps(
                {
                    "status": "failed",
                    "reason_class": type(exc).__name__,
                    "evidence": None if evidence_path is None else str(evidence_path),
                }
            ),
            file=sys.stderr,
        )
        return 1
    print(
        stable_json_dumps(
            {
                "status": evidence["overall_status"],
                "evidence": str(evidence_path),
                "evidence_checksum": evidence["evidence_checksum"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
