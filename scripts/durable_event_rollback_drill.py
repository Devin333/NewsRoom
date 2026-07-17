from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from framework.events.canonical import (
    BusinessContext,
    ProducerIdentity,
    StoredEvent,
    canonical_json_bytes,
    checksum_for,
)
from framework.events.errors import (
    EventIdentityCollisionError,
    EventSecurityError,
    EventUnknownSchemaError,
)
from framework.events.migration_backfill import MigrationBackfillStatus
from framework.events.runtime import (
    AutomaticDeliveryOperation,
    CheckpointKey,
    ConsumerEffectContract,
    DeliveryLimits,
    DeliveryQuery,
    DeliveryState,
    DurableDeliveryRuntime,
    DurableSubscription,
    EffectIdempotencyCapability,
    EffectIdempotencyStrategy,
    IdempotencyCapabilityRegistry,
    RetryPolicy,
    StreamReadRequest,
    SubscriptionFilter,
    SubscriptionStatus,
    effect_idempotency_key,
    subscription_definition_fingerprint,
)
from framework.events.runtime.publisher import EventPublishRequest, EventRuntime
from framework.events.schema import (
    EventSchemaRegistration,
    FieldDisposition,
    SensitivityPolicy,
    default_event_schema_catalog,
)
from framework.events.subscriber import (
    ConsumerDeliveryContext,
    ConsumerOutcome,
    TransientEventProcessingError,
)
from framework.shared.json import stable_json_dumps
from infrastructure.storage.events.migration_reports import (
    JsonMigrationBackfillReportStore,
    write_migration_shadow_report,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore
from interfaces.services.event_migration_service import (
    EventMigrationApplicationService,
    EventMigrationBackfillApplicationService,
    MigrationSourceSelection,
)
from interfaces.services.event_projection_service import EventProjectionService
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizationDecision,
)


EVIDENCE_SCHEMA = "newsroom.durable-event-rollback-drill/v1"
EXTERNAL_EVIDENCE_SCHEMA = "newsroom.durable-event-rollback-external/v1"
QUALIFICATION_EVIDENCE_SCHEMA = "newsroom.durable-event-rollback-qualification/v1"
APPROVAL_RECORD_SCHEMA = "newsroom.durable-event-rollback-approval/v1"
POSTGRES_SNAPSHOT_SCHEMA = "newsroom.durable-event-rollback-postgres-snapshot/v1"
EXTERNAL_EFFECT_AUDIT_SCHEMA = "newsroom.durable-event-rollback-effect-audit/v1"
ORCHESTRATOR_RUN_SCHEMA = "newsroom.durable-event-rollback-orchestrator/v1"
TRAFFIC_CONTROL_SCHEMA = "newsroom.durable-event-rollback-traffic-control/v1"
NEGATIVE_TESTS_SCHEMA = "newsroom.durable-event-rollback-negative-tests/v1"
PROJECTION_EVIDENCE_SCHEMA = "newsroom.durable-event-rollback-projection/v1"
EXTERNAL_ATTESTATION_ALGORITHM = "Ed25519"
DRILL_EVENT_TYPE = "io.newsroom.event.rollback.drill"
DRILL_DATA_SCHEMA = "io.newsroom.event.rollback.drill/v1"
DRILL_RUN_ID = "durable-event-rollback-drill"
DRILL_STREAM_ID = f"run:{DRILL_RUN_ID}"
DRILL_TENANT_ID = "tenant-rollback-drill"
DRILL_SUBSCRIPTION_ID = "rollback-drill-effect"
DRILL_CONSUMER_ID = "rollback-drill-effect-consumer"
DRILL_EFFECT_ID = "rollback-drill-external-effect"

_LOCAL_PHASE_ASSERTIONS = {
    "pre_cutover_shadow_rollback": frozenset(
        {
            "legacy_source_unchanged",
            "shadow_compare_cutover_ready",
            "staging_delivery_rows_zero",
            "staging_data_and_reports_retained",
        }
    ),
    "post_cutover_canonical_writer": frozenset(
        {
            "canonical_event_durable_before_dispatch",
            "event_and_pending_delivery_committed",
            "external_effect_not_run_during_publish",
            "legacy_unpersisted_writer_not_used",
        }
    ),
    "dispatcher_runtime_recomposition": frozenset(
        {
            "claims_paused_before_runtime_recomposition",
            "pending_retry_survived_recomposition",
            "stable_idempotency_key_reused",
            "external_effect_applied_once",
            "duplicate_publish_did_not_rebroadcast",
            "accepted_event_bytes_and_sequence_unchanged",
            "checkpoint_recovered",
        }
    ),
    "rollback_gates_and_sequence_continuity": frozenset(
        {
            "unknown_schema_rejected",
            "forbidden_payload_rejected",
            "identity_collision_rejected",
            "rejected_events_allocated_no_sequence",
            "next_accepted_sequence_is_contiguous",
            "earlier_accepted_event_unchanged",
            "pending_delivery_retained_while_paused",
        }
    ),
    "same_binary_projection_rebuild": frozenset(
        {
            "projection_rebuilt_from_durable_high_watermark",
            "candidate_and_rebuilt_projection_bytes_match",
            "projection_sequence_order_preserved",
            "projection_did_not_write_back_to_store",
            "projection_contains_no_raw_secret",
        }
    ),
}
_LOCAL_PHASE_EVIDENCE_FIELDS = {
    "pre_cutover_shadow_rollback": frozenset(
        {
            "backfill_status",
            "backfill_counts",
            "source_checksum",
            "shadow_report_checksum",
        }
    ),
    "post_cutover_canonical_writer": frozenset(
        {
            "event_id",
            "stream_id",
            "stream_sequence",
            "content_checksum",
            "record_checksum",
        }
    ),
    "dispatcher_runtime_recomposition": frozenset(
        {
            "first_attempt_state",
            "recovered_attempt_state",
            "consumer_invocations",
            "external_effect_rows",
            "checkpoint_sequence",
        }
    ),
    "rollback_gates_and_sequence_continuity": frozenset(
        {
            "watermark_before_rejections",
            "watermark_after_rejections",
            "accepted_sequences",
            "delivery_states",
        }
    ),
    "same_binary_projection_rebuild": frozenset(
        {
            "requested_high_watermark",
            "projection_event_count",
            "projection_checksum",
            "canonical_store_checksum",
        }
    ),
}
_LOCAL_ARTIFACT_ROLES = frozenset(
    {
        "legacy_source",
        "staging_store",
        "backfill_report",
        "shadow_report",
        "canonical_store",
        "external_effect_ledger",
        "candidate_projection",
        "rebuilt_projection",
    }
)
_EXTERNAL_GATE_NAMES = frozenset(
    {
        "actual_deployment_binary_switch",
        "real_postgresql_rollback_and_concurrent_writer_continuity",
        "production_external_effect_provider_idempotency",
        "deployment_orchestrator_and_traffic_control_evidence",
        "accepted_events_and_sequences_preserved",
        "schema_security_identity_integrity_gates_enabled",
        "compatible_projection_rebuilt",
    }
)
_EXTERNAL_ARTIFACT_ROLES = frozenset(
    {
        "orchestrator_run",
        "traffic_control",
        "postgres_before_snapshot",
        "postgres_after_snapshot",
        "external_effect_audit",
        "candidate_projection",
        "rollback_projection",
        "schema_security_negative_tests",
        "approval_record",
    }
)
_IMMUTABLE_RELEASE_DIGEST = re.compile(
    r"(?:[0-9a-f]{40}|[0-9a-f]{64}|sha256:[0-9a-f]{64})\Z"
)
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>]{1,2030}\Z")
_WINDOWS_PRIVATE_KEY_WRITE_MASK = 0x0002 | 0x0004 | 0x0010 | 0x0020 | 0x0040
_MAX_EVIDENCE_CLOCK_SKEW = timedelta(minutes=5)
_PRESERVED_LEDGER_NAMES = (
    "delivery_history",
    "inbox",
    "checkpoint",
    "dead_letter",
)
_EXTERNAL_NEGATIVE_CASES = frozenset(
    {
        "unknown_schema",
        "forbidden_payload",
        "identity_collision",
        "record_checksum_tamper",
    }
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class RollbackDrillInvariantError(RuntimeError):
    """A rollback invariant was not proved by the executable drill."""


class RollbackDrillFailure(RuntimeError):
    """The drill failed after writing bounded failure evidence."""


@dataclass
class _MutableClock:
    current: datetime

    def __post_init__(self) -> None:
        self.current = _utc(self.current)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: float) -> None:
        self.current += timedelta(seconds=float(seconds))


class _AllowProjectionAuthorizer:
    def authorize(self, request):
        return EventAuthorizationDecision(
            request=request,
            authorized=True,
            authorization_evidence_ref="authz://rollback-drill/projection",
        )


class _TargetIdempotencyValidator:
    def __init__(self, clock: _MutableClock) -> None:
        self._clock = clock

    def validate(
        self,
        subscription: DurableSubscription,
    ) -> EffectIdempotencyCapability | None:
        effect = subscription.effect
        if (
            not effect.performs_external_effects
            or effect.consumer_effect_id is None
            or effect.idempotency_strategy
            is not EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY
        ):
            return None
        return EffectIdempotencyCapability(
            subscription_id=subscription.subscription_id,
            subscription_version=subscription.subscription_version,
            consumer_id=subscription.consumer_id,
            consumer_effect_id=effect.consumer_effect_id,
            strategy=effect.idempotency_strategy,
            subscription_fingerprint=subscription_definition_fingerprint(
                subscription
            ),
            validator_id="rollback-drill-target-ledger/v1",
            validated_at=self._clock(),
            supported_operations=frozenset(
                {
                    AutomaticDeliveryOperation.INITIAL_DELIVERY,
                    AutomaticDeliveryOperation.RETRY,
                    AutomaticDeliveryOperation.LEASE_RECOVERY,
                    AutomaticDeliveryOperation.REDELIVERY,
                }
            ),
            tenant_id=subscription.tenant_id,
        )


class _ExternalEffectLedger:
    """A separate durable target that enforces the consumer idempotency key."""

    def __init__(self, database: Path) -> None:
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS applied_effects (
                    idempotency_key TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    content_checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_invocations (
                    invocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    invoked_at TEXT NOT NULL
                );
                """
            )
            connection.commit()

    def apply(
        self,
        *,
        event_id: str,
        content_checksum: str,
        idempotency_key: str,
        invoked_at: datetime,
        fail_after_first_effect: bool,
    ) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO effect_invocations "
                "(idempotency_key, event_id, invoked_at) VALUES (?, ?, ?)",
                (idempotency_key, event_id, _utc_text(invoked_at)),
            )
            connection.execute(
                "INSERT OR IGNORE INTO applied_effects "
                "(idempotency_key, event_id, content_checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    idempotency_key,
                    event_id,
                    content_checksum,
                    _utc_text(invoked_at),
                ),
            )
            row = connection.execute(
                "SELECT event_id, content_checksum FROM applied_effects "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row != (event_id, content_checksum):
                connection.rollback()
                raise RollbackDrillInvariantError(
                    "external_effect_idempotency_collision"
                )
            invocation_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM effect_invocations "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()[0]
            )
            connection.commit()
        if fail_after_first_effect and invocation_count == 1:
            raise TransientEventProcessingError(
                "simulated_ack_response_loss"
            )

    def snapshot(self) -> dict[str, int]:
        with self._connection() as connection:
            return {
                "effect_rows": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM applied_effects"
                    ).fetchone()[0]
                ),
                "invocation_rows": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM effect_invocations"
                    ).fetchone()[0]
                ),
                "distinct_idempotency_keys": int(
                    connection.execute(
                        "SELECT COUNT(DISTINCT idempotency_key) "
                        "FROM effect_invocations"
                    ).fetchone()[0]
                ),
            }

    def checkpoint_wal(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = None
        try:
            yield connection
        finally:
            connection.close()


class _ExternalEffectConsumer:
    consumer_id = DRILL_CONSUMER_ID

    def __init__(
        self,
        *,
        ledger: _ExternalEffectLedger,
        clock: _MutableClock,
        fail_after_first_effect: bool,
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._fail_after_first_effect = fail_after_first_effect

    def consume(self, event, context: ConsumerDeliveryContext) -> ConsumerOutcome:
        _require(
            context.consumer_effect_id == DRILL_EFFECT_ID,
            "consumer_effect_identity_changed",
        )
        _require(
            context.idempotency_key
            == effect_idempotency_key(event.event_id, DRILL_EFFECT_ID),
            "consumer_idempotency_key_changed",
        )
        assert context.idempotency_key is not None
        self._ledger.apply(
            event_id=event.event_id,
            content_checksum=event.content_checksum,
            idempotency_key=context.idempotency_key,
            invoked_at=self._clock(),
            fail_after_first_effect=self._fail_after_first_effect,
        )
        return ConsumerOutcome.ack("effect_idempotently_applied")


def run_rollback_drill(
    *,
    workspace: str | Path,
    evidence_path: str | Path | None = None,
    drill_id: str | None = None,
    candidate_release: str = "local-working-tree-candidate",
    rollback_release: str = "local-working-tree-compatible",
) -> dict[str, Any]:
    root = _prepare_workspace(workspace)
    evidence_target = _local_evidence_target(root, evidence_path)
    normalized_drill_id = _required_text(
        drill_id or f"rollback-drill-{uuid4().hex}",
        "drill_id",
    )
    candidate_release = _required_text(candidate_release, "candidate_release")
    rollback_release = _required_text(rollback_release, "rollback_release")
    started_at = datetime.now(UTC)
    clock = _MutableClock(started_at.replace(microsecond=0))
    phases: list[dict[str, Any]] = []
    artifact_paths: list[tuple[str, Path]] = []
    secret_marker = f"rollback-private-{uuid4().hex}"

    try:
        catalog = _drill_catalog()

        legacy_source = root / "legacy" / "events.jsonl"
        legacy_source.parent.mkdir(parents=True, exist_ok=True)
        legacy_row = {
            "schema_version": "newsroom.event_record.v1",
            "event_id": "rollback-shadow-event-1",
            "event_type": "workflow_started",
            "occurred_at": _utc_text(clock()),
            "run_id": "rollback-shadow-run",
            "payload": {"run_id": "rollback-shadow-run"},
        }
        _write_bytes_atomic(
            legacy_source,
            (stable_json_dumps(legacy_row) + "\n").encode("utf-8"),
        )
        source_checksum_before = _sha256_file(legacy_source)
        staging_database = root / "staging" / "events.sqlite3"
        backfill_report_path = root / "staging" / "backfill-report.json"
        shadow_report_path = root / "staging" / "shadow-report.json"
        staging_store = SQLiteEventStore(staging_database, clock=clock)
        report_store = JsonMigrationBackfillReportStore(backfill_report_path)
        migration = EventMigrationBackfillApplicationService(
            source_service=EventMigrationApplicationService(),
            staging_store=staging_store,
            schema_catalog=catalog,
            report_store=report_store,
            clock=clock,
        )
        report = migration.backfill(
            MigrationSourceSelection.from_inputs(
                legacy_run_jsonl=(legacy_source,)
            ),
            report_id="rollback-pre-cutover",
            resume=False,
        )
        shadow = migration.shadow_compare(report_id=report.report_id)
        write_migration_shadow_report(shadow_report_path, shadow)
        source_checksum_after = _sha256_file(legacy_source)
        staging_deliveries = staging_store.list_deliveries(DeliveryQuery()).records
        _require(
            report.status is MigrationBackfillStatus.SUCCEEDED,
            "pre_cutover_backfill_failed",
        )
        _require(shadow.cutover_ready, "pre_cutover_shadow_mismatch")
        _require(
            source_checksum_before == source_checksum_after,
            "pre_cutover_source_changed",
        )
        _require(not staging_deliveries, "pre_cutover_shadow_dispatched")
        phases.append(
            _passed_phase(
                "pre_cutover_shadow_rollback",
                assertions={
                    "legacy_source_unchanged": True,
                    "shadow_compare_cutover_ready": True,
                    "staging_delivery_rows_zero": True,
                    "staging_data_and_reports_retained": all(
                        path.exists()
                        for path in (
                            staging_database,
                            backfill_report_path,
                            shadow_report_path,
                        )
                    ),
                },
                evidence={
                    "backfill_status": report.status.value,
                    "backfill_counts": dict(report.counts),
                    "source_checksum": source_checksum_after,
                    "shadow_report_checksum": shadow.report_checksum,
                },
            )
        )

        canonical_database = root / "canonical" / "events.sqlite3"
        effects_database = root / "external-target" / "effects.sqlite3"
        effect_ledger = _ExternalEffectLedger(effects_database)
        canonical_store = SQLiteEventStore(canonical_database, clock=clock)
        subscription = _subscription()
        candidate_consumer = _ExternalEffectConsumer(
            ledger=effect_ledger,
            clock=clock,
            fail_after_first_effect=True,
        )
        candidate_delivery = DurableDeliveryRuntime(
            canonical_store,
            idempotency_capabilities=IdempotencyCapabilityRegistry(
                _TargetIdempotencyValidator(clock)
            ),
            clock=clock,
        )
        candidate_delivery.register(subscription, candidate_consumer)
        candidate_publisher = EventRuntime(
            store=canonical_store,
            schema_catalog=catalog,
        )
        first_request = _publish_request(
            event_id="rollback-live-event-1",
            message="accepted-before-dispatcher-rollback",
            occurred_at=clock(),
            private_note=secret_marker,
        )
        first_event = candidate_publisher.publish(
            first_request,
            expected_last_sequence=0,
        )
        first_bytes = canonical_json_bytes(first_event.to_dict())
        durable_before_dispatch = canonical_store.get_event(
            first_event.event_id,
            tenant_id=DRILL_TENANT_ID,
        )
        pending_before_dispatch = canonical_store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                tenant_id=DRILL_TENANT_ID,
            )
        ).records
        _require(first_event.stream_sequence == 1, "cutover_sequence_not_one")
        _require(
            durable_before_dispatch == first_event,
            "subscriber_visible_before_durable_acceptance",
        )
        _require(
            len(pending_before_dispatch) == 1,
            "cutover_event_outbox_not_atomic",
        )
        _require(
            effect_ledger.snapshot()["effect_rows"] == 0,
            "effect_ran_before_dispatch",
        )
        phases.append(
            _passed_phase(
                "post_cutover_canonical_writer",
                assertions={
                    "canonical_event_durable_before_dispatch": True,
                    "event_and_pending_delivery_committed": True,
                    "external_effect_not_run_during_publish": True,
                    "legacy_unpersisted_writer_not_used": True,
                },
                evidence={
                    "event_id": first_event.event_id,
                    "stream_id": first_event.stream_id,
                    "stream_sequence": first_event.stream_sequence,
                    "content_checksum": first_event.content_checksum,
                    "record_checksum": first_event.record_checksum,
                },
            )
        )

        failed_delivery = candidate_delivery.dispatch_batch(
            subscription.key,
            lease_owner="candidate-dispatcher",
            limit=1,
        )
        _require(
            len(failed_delivery.attempts) == 1
            and failed_delivery.attempts[0].state is DeliveryState.RETRY_WAIT,
            "crash_after_effect_did_not_enter_retry",
        )
        candidate_delivery.consumers.pause(
            subscription.key,
            reason="freeze claims before dispatcher rollback",
        )
        paused = canonical_store.get_subscription(subscription.key)
        _require(
            paused is not None and paused.status is SubscriptionStatus.PAUSED,
            "dispatcher_pause_not_durable",
        )

        rollback_store = SQLiteEventStore(
            canonical_database,
            initialize=False,
            clock=clock,
        )
        rollback_consumer = _ExternalEffectConsumer(
            ledger=effect_ledger,
            clock=clock,
            fail_after_first_effect=False,
        )
        rollback_delivery = DurableDeliveryRuntime(
            rollback_store,
            idempotency_capabilities=IdempotencyCapabilityRegistry(
                _TargetIdempotencyValidator(clock)
            ),
            clock=clock,
        )
        attached = rollback_delivery.consumers.attach(
            subscription.key,
            rollback_consumer,
        )
        _require(
            attached.status is SubscriptionStatus.PAUSED,
            "rollback_dispatcher_did_not_observe_pause",
        )
        rollback_delivery.consumers.resume(
            subscription.key,
            reason="compatible dispatcher attached after rollback",
        )
        clock.advance(seconds=2)
        recovered_delivery = rollback_delivery.dispatch_batch(
            subscription.key,
            lease_owner="rollback-dispatcher",
            limit=1,
        )
        _require(
            len(recovered_delivery.attempts) == 1
            and recovered_delivery.attempts[0].state is DeliveryState.ACKED,
            "rollback_dispatcher_did_not_ack_retry",
        )
        duplicate = EventRuntime(
            store=rollback_store,
            schema_catalog=catalog,
        ).publish(first_request)
        no_rebroadcast = rollback_delivery.dispatch_batch(
            subscription.key,
            lease_owner="rollback-dispatcher",
            limit=1,
        )
        first_after_restart = rollback_store.get_event(
            first_event.event_id,
            tenant_id=DRILL_TENANT_ID,
        )
        checkpoint = rollback_store.get_checkpoint(
            CheckpointKey(
                subscription.subscription_id,
                subscription.subscription_version,
                DRILL_STREAM_ID,
                DRILL_TENANT_ID,
            )
        )
        effect_snapshot = effect_ledger.snapshot()
        _require(first_after_restart is not None, "accepted_event_deleted_on_rollback")
        _require(
            canonical_json_bytes(first_after_restart.to_dict()) == first_bytes,
            "accepted_event_changed_on_rollback",
        )
        _require(
            duplicate.stream_sequence == 1,
            "duplicate_publish_reallocated_sequence",
        )
        _require(not no_rebroadcast.attempts, "duplicate_publish_rebroadcast_effect")
        _require(
            effect_snapshot
            == {
                "effect_rows": 1,
                "invocation_rows": 2,
                "distinct_idempotency_keys": 1,
            },
            "external_effect_was_repeated",
        )
        _require(
            checkpoint is not None
            and checkpoint.highest_contiguous_terminal_sequence == 1,
            "rollback_checkpoint_not_recovered",
        )
        phases.append(
            _passed_phase(
                "dispatcher_runtime_recomposition",
                assertions={
                    "claims_paused_before_runtime_recomposition": True,
                    "pending_retry_survived_recomposition": True,
                    "stable_idempotency_key_reused": True,
                    "external_effect_applied_once": True,
                    "duplicate_publish_did_not_rebroadcast": True,
                    "accepted_event_bytes_and_sequence_unchanged": True,
                    "checkpoint_recovered": True,
                },
                evidence={
                    "first_attempt_state": DeliveryState.RETRY_WAIT.value,
                    "recovered_attempt_state": DeliveryState.ACKED.value,
                    "consumer_invocations": effect_snapshot["invocation_rows"],
                    "external_effect_rows": effect_snapshot["effect_rows"],
                    "checkpoint_sequence": (
                        checkpoint.highest_contiguous_terminal_sequence
                        if checkpoint is not None
                        else None
                    ),
                },
            )
        )

        rollback_delivery.consumers.pause(
            subscription.key,
            reason="hold dispatcher during reader and application rollback",
        )
        rollback_publisher = EventRuntime(
            store=rollback_store,
            schema_catalog=catalog,
        )
        watermark_before_gate_checks = rollback_store.get_stream_high_watermark(
            DRILL_STREAM_ID,
            tenant_id=DRILL_TENANT_ID,
        )
        unknown_schema_rejected = _publish_rejected_as(
            rollback_publisher,
            _publish_request(
                event_id="rollback-unknown-schema",
                message="must-not-append",
                occurred_at=clock(),
                data_schema="io.newsroom.event.rollback.drill/v999",
            ),
            EventUnknownSchemaError,
        )
        forbidden_payload_rejected = _publish_rejected_as(
            rollback_publisher,
            _publish_request(
                event_id="rollback-forbidden-payload",
                message="must-not-append",
                occurred_at=clock(),
                blocked_value=secret_marker,
            ),
            EventSecurityError,
        )
        identity_collision_rejected = _publish_rejected_as(
            rollback_publisher,
            _publish_request(
                event_id=first_event.event_id,
                message="changed-after-rollback",
                occurred_at=first_request.occurred_at,
            ),
            EventIdentityCollisionError,
        )
        watermark_after_gate_checks = rollback_store.get_stream_high_watermark(
            DRILL_STREAM_ID,
            tenant_id=DRILL_TENANT_ID,
        )
        second_event = rollback_publisher.publish(
            _publish_request(
                event_id="rollback-live-event-2",
                message="accepted-after-rollback",
                occurred_at=clock(),
            ),
            expected_last_sequence=1,
        )
        accepted_page = rollback_store.read_stream(
            StreamReadRequest(
                DRILL_STREAM_ID,
                tenant_id=DRILL_TENANT_ID,
                through_sequence=2,
                limit=10,
            )
        )
        post_rollback_deliveries = rollback_store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                tenant_id=DRILL_TENANT_ID,
                limit=10,
            )
        ).records
        first_after_second_append = rollback_store.get_event(
            first_event.event_id,
            tenant_id=DRILL_TENANT_ID,
        )
        _require(unknown_schema_rejected, "schema_gate_disabled_by_rollback")
        _require(forbidden_payload_rejected, "security_gate_disabled_by_rollback")
        _require(identity_collision_rejected, "identity_gate_disabled_by_rollback")
        _require(
            watermark_before_gate_checks == watermark_after_gate_checks == 1,
            "rejected_event_allocated_sequence",
        )
        _require(second_event.stream_sequence == 2, "rollback_reused_sequence")
        _require(
            [event.stream_sequence for event in accepted_page.events] == [1, 2],
            "accepted_stream_not_contiguous_after_rollback",
        )
        _require(
            first_after_second_append is not None
            and canonical_json_bytes(first_after_second_append.to_dict()) == first_bytes,
            "earlier_accepted_event_changed_after_new_append",
        )
        _require(
            [record.state for record in post_rollback_deliveries]
            == [DeliveryState.ACKED, DeliveryState.PENDING],
            "pending_delivery_not_preserved_during_rollback",
        )
        _require(
            effect_ledger.snapshot()["effect_rows"] == 1,
            "paused_dispatcher_repeated_external_effect",
        )
        phases.append(
            _passed_phase(
                "rollback_gates_and_sequence_continuity",
                assertions={
                    "unknown_schema_rejected": True,
                    "forbidden_payload_rejected": True,
                    "identity_collision_rejected": True,
                    "rejected_events_allocated_no_sequence": True,
                    "next_accepted_sequence_is_contiguous": True,
                    "earlier_accepted_event_unchanged": True,
                    "pending_delivery_retained_while_paused": True,
                },
                evidence={
                    "watermark_before_rejections": watermark_before_gate_checks,
                    "watermark_after_rejections": watermark_after_gate_checks,
                    "accepted_sequences": [
                        event.stream_sequence for event in accepted_page.events
                    ],
                    "delivery_states": [
                        record.state.value for record in post_rollback_deliveries
                    ],
                },
            )
        )

        rollback_store.checkpoint_wal(mode="TRUNCATE")
        canonical_checksum_before_projection = _sha256_file(canonical_database)
        projection_reader = SQLiteEventStore(
            canonical_database,
            read_only=True,
            initialize=True,
            clock=clock,
        )
        authorization = EventAuthorizationContext(
            principal_id="rollback-drill-operator",
            tenant_id=DRILL_TENANT_ID,
            authentication_evidence_ref="authn://rollback-drill/operator",
        )
        candidate_projection = EventProjectionService(
            reader=projection_reader,
            authorizer=_AllowProjectionAuthorizer(),
            artifact_root=root / "candidate-projection",
            schema_catalog=catalog,
        ).rebuild_run_projection(
            DRILL_RUN_ID,
            requested_high_watermark=2,
            authorization=authorization,
        )
        rebuilt_projection = EventProjectionService(
            reader=projection_reader,
            authorizer=_AllowProjectionAuthorizer(),
            artifact_root=root / "rollback-projection",
            schema_catalog=catalog,
        ).rebuild_run_projection(
            DRILL_RUN_ID,
            requested_high_watermark=2,
            authorization=authorization,
        )
        _require(
            candidate_projection.projection is not None
            and rebuilt_projection.projection is not None,
            "projection_rebuild_unavailable",
        )
        candidate_projection_bytes = candidate_projection.path.read_bytes()
        rebuilt_projection_bytes = rebuilt_projection.path.read_bytes()
        projection_rows = tuple(
            json.loads(line)
            for line in rebuilt_projection_bytes.decode("utf-8").splitlines()
        )
        canonical_checksum_after_projection = _sha256_file(canonical_database)
        _require(
            candidate_projection_bytes == rebuilt_projection_bytes,
            "same_binary_projection_rebuild_changed",
        )
        _require(
            candidate_projection.projection.checksum
            == rebuilt_projection.projection.checksum,
            "same_binary_projection_checksum_changed",
        )
        _require(
            [row["stream_sequence"] for row in projection_rows] == [1, 2],
            "rollback_projection_order_changed",
        )
        _require(
            canonical_checksum_before_projection
            == canonical_checksum_after_projection,
            "projection_rebuild_wrote_back_to_store",
        )
        _require(
            secret_marker.encode("utf-8") not in rebuilt_projection_bytes,
            "projection_contains_raw_secret",
        )
        phases.append(
            _passed_phase(
                "same_binary_projection_rebuild",
                assertions={
                    "projection_rebuilt_from_durable_high_watermark": True,
                    "candidate_and_rebuilt_projection_bytes_match": True,
                    "projection_sequence_order_preserved": True,
                    "projection_did_not_write_back_to_store": True,
                    "projection_contains_no_raw_secret": True,
                },
                evidence={
                    "requested_high_watermark": 2,
                    "projection_event_count": len(projection_rows),
                    "projection_checksum": rebuilt_projection.projection.checksum,
                    "canonical_store_checksum": canonical_checksum_after_projection,
                },
            )
        )

        staging_store.checkpoint_wal(mode="TRUNCATE")
        effect_ledger.checkpoint_wal()
        _require_secret_absent(root, secret_marker)
        artifact_paths.extend(
            (
                ("legacy_source", legacy_source),
                ("staging_store", staging_database),
                ("backfill_report", backfill_report_path),
                ("shadow_report", shadow_report_path),
                ("canonical_store", canonical_database),
                ("external_effect_ledger", effects_database),
                ("candidate_projection", candidate_projection.path),
                ("rebuilt_projection", rebuilt_projection.path),
            )
        )
        artifacts = _artifact_manifest(root, artifact_paths)
        completed_at = datetime.now(UTC)
        evidence = {
            "schema": EVIDENCE_SCHEMA,
            "drill_id": normalized_drill_id,
            "overall_status": "incomplete",
            "execution_scope": "local_single_host_sqlite",
            "started_at": _utc_text(started_at),
            "completed_at": _utc_text(completed_at),
            "artifact_root": ".",
            "release_context": {
                "candidate_release": candidate_release,
                "rollback_release": rollback_release,
                "labels_source": "operator_input",
            },
            "environment": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "sqlite_version": sqlite3.sqlite_version,
                "event_store_policy": dict(rollback_store.durability_policy),
            },
            "phases": phases,
            "artifacts": artifacts,
            "unverified_external_gates": sorted(_EXTERNAL_GATE_NAMES),
        }
        evidence["evidence_checksum"] = checksum_for(evidence)
        _write_bytes_atomic(
            evidence_target,
            (stable_json_dumps(evidence) + "\n").encode("utf-8"),
        )
        _require_secret_absent(root, secret_marker)
        verify_rollback_evidence(
            evidence_target,
            allow_incomplete_local=True,
        )
        return evidence
    except Exception as error:
        failure = {
            "schema": EVIDENCE_SCHEMA,
            "drill_id": normalized_drill_id,
            "overall_status": "failed",
            "execution_scope": "local_single_host_sqlite",
            "started_at": _utc_text(started_at),
            "completed_at": _utc_text(datetime.now(UTC)),
            "workspace": str(root),
            "release_context": {
                "candidate_release": candidate_release,
                "rollback_release": rollback_release,
                "labels_source": "operator_input",
            },
            "phases": phases,
            "failure_reason_class": type(error).__name__,
        }
        failure["evidence_checksum"] = checksum_for(failure)
        try:
            _write_bytes_atomic(
                evidence_target,
                (stable_json_dumps(failure) + "\n").encode("utf-8"),
            )
        except Exception:
            pass
        raise RollbackDrillFailure(
            f"rollback drill failed; evidence={evidence_target}; "
            f"reason_class={type(error).__name__}"
        ) from None


def verify_rollback_evidence(
    path: str | Path,
    *,
    allow_incomplete_local: bool = False,
    trusted_public_key: str | Path | None = None,
    trusted_external_public_key: str | Path | None = None,
    trusted_approval_public_key: str | Path | None = None,
) -> dict[str, Any]:
    evidence_path = Path(path).resolve(strict=True)
    evidence = _read_json_object(evidence_path, "evidence")
    schema = evidence.get("schema")
    if schema == QUALIFICATION_EVIDENCE_SCHEMA:
        _require(not allow_incomplete_local, "qualified_evidence_is_not_local")
        _require(trusted_public_key is not None, "trusted_public_key_required")
        _require(
            trusted_external_public_key is not None,
            "trusted_external_public_key_required",
        )
        _require(
            trusted_approval_public_key is not None,
            "trusted_approval_public_key_required",
        )
        return _verify_qualification_evidence(
            evidence_path,
            evidence,
            trusted_public_key=trusted_public_key,
            trusted_external_public_key=trusted_external_public_key,
            trusted_approval_public_key=trusted_approval_public_key,
        )
    _require(schema == EVIDENCE_SCHEMA, "evidence_schema_mismatch")
    _require(trusted_public_key is None, "local_evidence_must_not_use_trust_key")
    _require(
        trusted_external_public_key is None,
        "local_evidence_must_not_use_external_trust_key",
    )
    _require(
        trusted_approval_public_key is None,
        "local_evidence_must_not_use_approval_trust_key",
    )
    return _verify_local_evidence(
        evidence_path,
        evidence,
        allow_incomplete_local=allow_incomplete_local,
    )


def qualify_rollback_evidence(
    *,
    local_evidence_path: str | Path,
    external_evidence_path: str | Path,
    private_key_path: str | Path,
    trusted_external_public_key: str | Path,
    trusted_approval_public_key: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    local_path = Path(local_evidence_path).resolve(strict=True)
    external_path = Path(external_evidence_path).resolve(strict=True)
    local = verify_rollback_evidence(local_path, allow_incomplete_local=True)
    external_key = _load_public_key(trusted_external_public_key)
    approval_key = _load_public_key(trusted_approval_public_key)
    external = _verify_external_evidence(
        external_path,
        trusted_public_key=external_key,
        trusted_approval_public_key=approval_key,
    )
    _require(
        external["drill_id"] == local["drill_id"],
        "external_drill_id_mismatch",
    )
    local_release = _required_mapping(local.get("release_context"), "release_context")
    _require(
        external["candidate_release_digest"]
        == local_release.get("candidate_release"),
        "candidate_release_mismatch",
    )
    _require(
        external["rollback_release_digest"]
        == local_release.get("rollback_release"),
        "rollback_release_mismatch",
    )
    key = _load_private_key(private_key_path)
    public_key = key.public_key()
    _require_distinct_authorities(public_key, external_key, approval_key)
    generated_at = _utc_text(datetime.now(UTC))
    evidence: dict[str, Any] = {
        "schema": QUALIFICATION_EVIDENCE_SCHEMA,
        "drill_id": local["drill_id"],
        "overall_status": "passed",
        "generated_at": generated_at,
        "drill_completed_at": external["drill_completed_at"],
        "local_evidence": {
            "checksum": local["evidence_checksum"],
            "bundle_path": "local/rollback-evidence.json",
        },
        "external_evidence": {
            "checksum": external["evidence_checksum"],
            "bundle_checksum": _sha256_file(external_path),
            "bundle_path": "external/external-evidence.json",
        },
        "release_context": {
            "candidate_release_digest": external["candidate_release_digest"],
            "rollback_release_digest": external["rollback_release_digest"],
        },
        "postgresql": dict(external["postgresql"]),
        "external_effect": dict(external["external_effect"]),
        "orchestrator": dict(external["orchestrator"]),
        "approval": dict(external["approval"]),
        "external_gates": dict(external["external_gates"]),
        "artifacts": [dict(item) for item in external["artifacts"]],
        "signing": {
            "algorithm": "Ed25519",
            "public_key_fingerprint": _public_key_fingerprint(public_key),
            "external_public_key_fingerprint": _public_key_fingerprint(
                external_key
            ),
            "approval_public_key_fingerprint": _public_key_fingerprint(
                approval_key
            ),
        },
    }
    evidence["evidence_checksum"] = checksum_for(evidence)
    signature = key.sign(_qualification_signature_payload(evidence))
    evidence["signature"] = base64.b64encode(signature).decode("ascii")
    target = Path(output_path).resolve(strict=False)
    _validate_qualification_target(
        target,
        local_path=local_path,
        external_path=external_path,
        private_key_path=Path(private_key_path).resolve(strict=True),
        external_public_key_path=Path(trusted_external_public_key).resolve(
            strict=True
        ),
        approval_public_key_path=Path(trusted_approval_public_key).resolve(
            strict=True
        ),
    )
    _materialize_qualification_bundle(
        target,
        local_path=local_path,
        external_path=external_path,
        external=external,
        evidence=evidence,
        trusted_public_key=public_key,
        trusted_external_public_key=external_key,
        trusted_approval_public_key=approval_key,
    )
    return _verify_qualification_evidence(
        target,
        evidence,
        trusted_public_key=public_key,
        trusted_external_public_key=trusted_external_public_key,
        trusted_approval_public_key=trusted_approval_public_key,
    )


def attest_external_evidence(
    *,
    evidence_path: str | Path,
    private_key_path: str | Path,
    trusted_approval_public_key: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Sign deployment evidence without granting the qualifier that authority."""

    source = Path(evidence_path).resolve(strict=True)
    target = Path(output_path).resolve(strict=False)
    private_path = Path(private_key_path).resolve(strict=True)
    approval_public_path = Path(trusted_approval_public_key).resolve(strict=True)
    _require(
        target not in {source, private_path, approval_public_path},
        "external_attestation_output_alias",
    )
    _require(target.parent == source.parent, "external_attestation_output_must_share_bundle")
    _require(not target.exists(), "external_attestation_output_exists")
    unsigned = _read_json_object(source, "external_evidence")
    _require("attestation" not in unsigned, "external_evidence_already_attested")
    key = _load_private_key(private_path)
    approval_key = _load_public_key(approval_public_path)
    _require_distinct_authorities(key.public_key(), approval_key)
    attestation: dict[str, Any] = {
        "algorithm": EXTERNAL_ATTESTATION_ALGORITHM,
        "public_key_fingerprint": _public_key_fingerprint(key.public_key()),
        "attested_at": _utc_text(datetime.now(UTC)),
    }
    signature = key.sign(_external_attestation_payload(unsigned, attestation))
    attestation["signature"] = base64.b64encode(signature).decode("ascii")
    signed = {**unsigned, "attestation": attestation}
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        _write_bytes_atomic(
            temporary,
            (stable_json_dumps(signed) + "\n").encode("utf-8"),
        )
        verified = _verify_external_evidence(
            temporary,
            trusted_public_key=key.public_key(),
            trusted_approval_public_key=approval_key,
        )
        _publish_new_file(
            temporary,
            target,
            exists_reason="external_attestation_output_exists",
        )
        return verified
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _verify_local_evidence(
    evidence_path: Path,
    evidence: dict[str, Any],
    *,
    allow_incomplete_local: bool,
) -> dict[str, Any]:
    checksum = evidence.pop("evidence_checksum", None)
    _require(checksum == checksum_for(evidence), "evidence_checksum_mismatch")
    _require(
        set(evidence)
        == {
            "schema",
            "drill_id",
            "overall_status",
            "execution_scope",
            "started_at",
            "completed_at",
            "artifact_root",
            "release_context",
            "environment",
            "phases",
            "artifacts",
            "unverified_external_gates",
        },
        "local_evidence_fields_invalid",
    )
    _require(evidence.get("overall_status") == "incomplete", "local_status_not_incomplete")
    _require(
        evidence.get("execution_scope") == "local_single_host_sqlite",
        "local_execution_scope_invalid",
    )
    _require(
        set(evidence.get("unverified_external_gates") or ())
        == _EXTERNAL_GATE_NAMES,
        "local_external_gates_invalid",
    )
    _verify_phases(
        evidence.get("phases"),
        _LOCAL_PHASE_ASSERTIONS,
        evidence_fields=_LOCAL_PHASE_EVIDENCE_FIELDS,
    )
    _verify_local_phase_values(evidence["phases"])
    root = _bundle_root(evidence_path, evidence)
    _verify_artifacts(
        root,
        evidence.get("artifacts"),
        required_roles=_LOCAL_ARTIFACT_ROLES,
    )
    if not allow_incomplete_local:
        raise RollbackDrillInvariantError("drill_not_passed")
    evidence["evidence_checksum"] = checksum
    return evidence


def _verify_external_evidence(
    path: Path,
    *,
    trusted_public_key: Ed25519PublicKey,
    trusted_approval_public_key: Ed25519PublicKey,
) -> dict[str, Any]:
    evidence = _read_json_object(path, "external_evidence")
    attestation = evidence.pop("attestation", None)
    checksum = evidence.pop("evidence_checksum", None)
    _require(checksum == checksum_for(evidence), "external_evidence_checksum_mismatch")
    _require(
        evidence.get("schema") == EXTERNAL_EVIDENCE_SCHEMA,
        "external_evidence_schema_mismatch",
    )
    _require(
        set(evidence)
        == {
            "schema",
            "status",
            "drill_id",
            "drill_completed_at",
            "candidate_release_digest",
            "rollback_release_digest",
            "postgresql",
            "external_effect",
            "orchestrator",
            "approval",
            "external_gates",
            "artifacts",
        },
        "external_evidence_fields_invalid",
    )
    _require(evidence.get("status") == "passed", "external_evidence_not_passed")
    _required_text(evidence.get("drill_id"), "drill_id")
    drill_completed_at = _parse_utc_text(
        evidence.get("drill_completed_at"),
        "drill_completed_at",
    )
    _require_not_future(drill_completed_at, "drill_completed_at")
    for field in ("candidate_release_digest", "rollback_release_digest"):
        digest = _required_text(evidence.get(field), field)
        _require(_IMMUTABLE_RELEASE_DIGEST.fullmatch(digest) is not None, f"{field}_invalid")
    _require(
        evidence["candidate_release_digest"] != evidence["rollback_release_digest"],
        "rollback_release_not_distinct",
    )
    postgresql = _required_mapping(evidence.get("postgresql"), "postgresql")
    _verify_postgresql_evidence(postgresql)
    _verify_external_effect_evidence(
        _required_mapping(evidence.get("external_effect"), "external_effect")
    )
    _verify_orchestrator_evidence(
        _required_mapping(evidence.get("orchestrator"), "orchestrator")
    )
    _verify_approval(
        _required_mapping(evidence.get("approval"), "approval"),
        drill_completed_at=drill_completed_at,
    )
    gates = _required_mapping(evidence.get("external_gates"), "external_gates")
    _require(set(gates) == _EXTERNAL_GATE_NAMES, "external_gate_set_invalid")
    _require(all(value is True for value in gates.values()), "external_gate_failed")
    artifact_paths = _verify_artifacts(
        path.parent,
        evidence.get("artifacts"),
        required_roles=_EXTERNAL_ARTIFACT_ROLES,
    )
    _verify_external_artifact_references(evidence, artifact_paths)
    _verify_external_artifact_contents(evidence, artifact_paths)
    _verify_approval_artifact(
        evidence,
        artifact_paths["approval_record"],
        trusted_public_key=trusted_approval_public_key,
    )
    _require_distinct_authorities(trusted_public_key, trusted_approval_public_key)
    evidence["evidence_checksum"] = checksum
    _verify_external_attestation(
        evidence,
        attestation,
        trusted_public_key=trusted_public_key,
    )
    evidence["attestation"] = attestation
    return evidence


def _verify_qualification_evidence(
    path: Path,
    evidence: dict[str, Any],
    *,
    trusted_public_key: str | Path | Ed25519PublicKey,
    trusted_external_public_key: str | Path | Ed25519PublicKey,
    trusted_approval_public_key: str | Path | Ed25519PublicKey,
) -> dict[str, Any]:
    signature_text = evidence.pop("signature", None)
    checksum = evidence.pop("evidence_checksum", None)
    _require(checksum == checksum_for(evidence), "qualification_checksum_mismatch")
    evidence["evidence_checksum"] = checksum
    _require(
        set(evidence)
        == {
            "schema",
            "drill_id",
            "overall_status",
            "generated_at",
            "drill_completed_at",
            "local_evidence",
            "external_evidence",
            "release_context",
            "postgresql",
            "external_effect",
            "orchestrator",
            "approval",
            "external_gates",
            "artifacts",
            "signing",
            "evidence_checksum",
        },
        "qualification_evidence_fields_invalid",
    )
    key = _coerce_public_key(trusted_public_key)
    external_key = _coerce_public_key(trusted_external_public_key)
    approval_key = _coerce_public_key(trusted_approval_public_key)
    signing = _required_mapping(evidence.get("signing"), "signing")
    _require(
        set(signing)
        == {
            "algorithm",
            "public_key_fingerprint",
            "external_public_key_fingerprint",
            "approval_public_key_fingerprint",
        },
        "signing_fields_invalid",
    )
    _require(signing.get("algorithm") == "Ed25519", "signing_algorithm_invalid")
    _require(
        signing.get("public_key_fingerprint") == _public_key_fingerprint(key),
        "trusted_public_key_mismatch",
    )
    _require(
        signing.get("external_public_key_fingerprint")
        == _public_key_fingerprint(external_key),
        "trusted_external_public_key_mismatch",
    )
    _require(
        signing.get("approval_public_key_fingerprint")
        == _public_key_fingerprint(approval_key),
        "trusted_approval_public_key_mismatch",
    )
    _require_distinct_authorities(key, external_key, approval_key)
    try:
        signature = base64.b64decode(
            _required_text(signature_text, "signature"),
            validate=True,
        )
        key.verify(signature, _qualification_signature_payload(evidence))
    except (ValueError, InvalidSignature) as error:
        raise RollbackDrillInvariantError("qualification_signature_invalid") from error
    _require(evidence.get("overall_status") == "passed", "drill_not_passed")
    drill_completed_at = _parse_utc_text(
        evidence.get("drill_completed_at"),
        "drill_completed_at",
    )
    generated_at = _parse_utc_text(evidence.get("generated_at"), "generated_at")
    _require_not_future(generated_at, "generated_at")
    _require(generated_at >= drill_completed_at, "qualification_predates_drill")
    gates = _required_mapping(evidence.get("external_gates"), "external_gates")
    _require(set(gates) == _EXTERNAL_GATE_NAMES, "external_gate_set_invalid")
    _require(all(value is True for value in gates.values()), "external_gate_failed")
    release = _required_mapping(evidence.get("release_context"), "release_context")
    for field in ("candidate_release_digest", "rollback_release_digest"):
        _require(
            _IMMUTABLE_RELEASE_DIGEST.fullmatch(
                _required_text(release.get(field), field)
            )
            is not None,
            f"{field}_invalid",
        )
    _verify_postgresql_evidence(
        _required_mapping(evidence.get("postgresql"), "postgresql")
    )
    _verify_external_effect_evidence(
        _required_mapping(evidence.get("external_effect"), "external_effect")
    )
    _verify_orchestrator_evidence(
        _required_mapping(evidence.get("orchestrator"), "orchestrator")
    )
    _verify_approval(
        _required_mapping(evidence.get("approval"), "approval"),
        drill_completed_at=drill_completed_at,
    )
    local_ref = _required_mapping(evidence.get("local_evidence"), "local_evidence")
    external_ref = _required_mapping(
        evidence.get("external_evidence"), "external_evidence"
    )
    _require(
        set(local_ref) == {"checksum", "bundle_path"},
        "local_evidence_reference_fields_invalid",
    )
    _require(
        set(external_ref) == {"checksum", "bundle_checksum", "bundle_path"},
        "external_evidence_reference_fields_invalid",
    )
    local_path = _bundle_reference(path.parent, local_ref, "local_evidence")
    external_path = _bundle_reference(path.parent, external_ref, "external_evidence")
    external_bundle_checksum = _required_text(
        external_ref.get("bundle_checksum"),
        "external_evidence.bundle_checksum",
    )
    _require(
        _SHA256.fullmatch(external_bundle_checksum) is not None,
        "external_evidence_bundle_checksum_invalid",
    )
    _require(
        _sha256_file(external_path) == external_bundle_checksum,
        "external_evidence_bundle_checksum_mismatch",
    )
    local = verify_rollback_evidence(local_path, allow_incomplete_local=True)
    external = _verify_external_evidence(
        external_path,
        trusted_public_key=external_key,
        trusted_approval_public_key=approval_key,
    )
    _require(local["evidence_checksum"] == local_ref.get("checksum"), "local_checksum_mismatch")
    _require(
        external["evidence_checksum"] == external_ref.get("checksum"),
        "external_checksum_mismatch",
    )
    _require(evidence.get("drill_id") == local.get("drill_id"), "local_drill_id_mismatch")
    _require(
        evidence.get("drill_id") == external.get("drill_id"),
        "external_drill_id_mismatch",
    )
    _require(
        release
        == {
            "candidate_release_digest": external["candidate_release_digest"],
            "rollback_release_digest": external["rollback_release_digest"],
        },
        "release_context_mismatch",
    )
    local_release = _required_mapping(
        local.get("release_context"),
        "local.release_context",
    )
    _require(
        local_release
        == {
            "candidate_release": release["candidate_release_digest"],
            "rollback_release": release["rollback_release_digest"],
            "labels_source": "operator_input",
        },
        "local_release_context_mismatch",
    )
    _require(
        evidence.get("drill_completed_at") == external.get("drill_completed_at"),
        "drill_completed_at_summary_mismatch",
    )
    external_attestation = _required_mapping(
        external.get("attestation"),
        "external.attestation",
    )
    attested_at = _parse_utc_text(
        external_attestation.get("attested_at"),
        "attested_at",
    )
    _require(generated_at >= attested_at, "qualification_predates_attestation")
    for field in (
        "postgresql",
        "external_effect",
        "orchestrator",
        "approval",
        "external_gates",
        "artifacts",
    ):
        _require(evidence.get(field) == external.get(field), f"{field}_summary_mismatch")
    _verify_artifacts(
        path.parent / "external",
        evidence.get("artifacts"),
        required_roles=_EXTERNAL_ARTIFACT_ROLES,
    )
    evidence["signature"] = signature_text
    return evidence


def _verify_phases(
    value: Any,
    required: Mapping[str, frozenset[str]],
    *,
    evidence_fields: Mapping[str, frozenset[str]],
) -> None:
    _require(isinstance(value, list), "evidence_phases_missing")
    phases: dict[str, Mapping[str, Any]] = {}
    for item in value:
        _require(isinstance(item, Mapping), "evidence_phase_invalid")
        name = _required_text(item.get("phase"), "phase")
        _require(name not in phases, "evidence_phase_duplicate")
        phases[name] = item
    _require(set(phases) == set(required), "evidence_phase_set_invalid")
    for name, expected_assertions in required.items():
        phase = phases[name]
        _require(phase.get("status") == "passed", "evidence_phase_not_passed")
        assertions = _required_mapping(
            phase.get("assertions"),
            f"phase.{name}.assertions",
        )
        _require(
            set(assertions) == expected_assertions,
            f"phase_assertion_set_invalid:{name}",
        )
        _require(
            all(value is True for value in assertions.values()),
            f"phase_assertion_failed:{name}",
        )
        phase_evidence = _required_mapping(
            phase.get("evidence"),
            f"phase.{name}.evidence",
        )
        _require(
            set(phase_evidence) == evidence_fields[name],
            f"phase_evidence_fields_invalid:{name}",
        )


def _verify_local_phase_values(value: Sequence[Mapping[str, Any]]) -> None:
    phases = {str(item["phase"]): item["evidence"] for item in value}
    pre_cutover = phases["pre_cutover_shadow_rollback"]
    _require(pre_cutover.get("backfill_status") == "succeeded", "backfill_not_succeeded")
    for field in ("source_checksum", "shadow_report_checksum"):
        _require(
            _SHA256.fullmatch(_required_text(pre_cutover.get(field), field)) is not None,
            f"{field}_invalid",
        )
    cutover = phases["post_cutover_canonical_writer"]
    _require(cutover.get("stream_sequence") == 1, "cutover_sequence_invalid")
    for field in ("content_checksum", "record_checksum"):
        _require(
            _SHA256.fullmatch(_required_text(cutover.get(field), field)) is not None,
            f"{field}_invalid",
        )
    recomposition = phases["dispatcher_runtime_recomposition"]
    _require(recomposition.get("first_attempt_state") == "retry_wait", "retry_state_invalid")
    _require(recomposition.get("recovered_attempt_state") == "acked", "recovery_state_invalid")
    _require(recomposition.get("consumer_invocations") == 2, "consumer_invocations_invalid")
    _require(recomposition.get("external_effect_rows") == 1, "external_effect_rows_invalid")
    _require(recomposition.get("checkpoint_sequence") == 1, "checkpoint_sequence_invalid")
    continuity = phases["rollback_gates_and_sequence_continuity"]
    _require(
        continuity.get("watermark_before_rejections")
        == continuity.get("watermark_after_rejections")
        == 1,
        "rejection_watermark_invalid",
    )
    _require(continuity.get("accepted_sequences") == [1, 2], "accepted_sequences_invalid")
    _require(continuity.get("delivery_states") == ["acked", "pending"], "delivery_states_invalid")
    projection = phases["same_binary_projection_rebuild"]
    _require(projection.get("requested_high_watermark") == 2, "projection_watermark_invalid")
    _require(projection.get("projection_event_count") == 2, "projection_count_invalid")
    for field in ("projection_checksum", "canonical_store_checksum"):
        _require(
            _SHA256.fullmatch(_required_text(projection.get(field), field)) is not None,
            f"{field}_invalid",
        )


def _verify_artifacts(
    root: Path,
    value: Any,
    *,
    required_roles: frozenset[str],
) -> dict[str, Path]:
    _require(isinstance(value, list), "evidence_artifacts_missing")
    artifacts: dict[str, Mapping[str, Any]] = {}
    artifact_paths: dict[str, Path] = {}
    resolved_paths: set[Path] = set()
    file_identities: set[tuple[int, int]] = set()
    _require_not_reparse_point(root, "evidence_artifact_root_reparse_point")
    resolved_root = root.resolve(strict=True)
    for item in value:
        _require(isinstance(item, Mapping), "evidence_artifact_invalid")
        _require(
            set(item) == {"role", "path", "size_bytes", "checksum"},
            "evidence_artifact_fields_invalid",
        )
        role = _required_text(item.get("role"), "artifact.role")
        _require(role not in artifacts, "evidence_artifact_role_duplicate")
        artifacts[role] = item
        relative = _portable_relative_path(
            item.get("path"),
            "artifact.path",
            absolute_reason="evidence_artifact_path_absolute",
        )
        unresolved_artifact = resolved_root / relative
        _require_path_components_not_reparse(
            resolved_root,
            unresolved_artifact,
            "evidence_artifact_reparse_point",
        )
        artifact = unresolved_artifact.resolve(strict=True)
        _require(
            artifact.is_relative_to(resolved_root),
            "evidence_artifact_escaped_bundle",
        )
        _require(artifact.is_file(), "evidence_artifact_not_regular_file")
        _require(
            artifact not in resolved_paths,
            "evidence_artifact_path_duplicate",
        )
        resolved_paths.add(artifact)
        artifact_stat = artifact.stat()
        file_identity = (int(artifact_stat.st_dev), int(artifact_stat.st_ino))
        _require(
            file_identity not in file_identities,
            "evidence_artifact_file_alias",
        )
        file_identities.add(file_identity)
        artifact_paths[role] = artifact
        size = item.get("size_bytes")
        _require(
            isinstance(size, int) and not isinstance(size, bool) and size >= 0,
            "evidence_artifact_size_invalid",
        )
        checksum = _required_text(item.get("checksum"), "artifact.checksum")
        _require(_SHA256.fullmatch(checksum) is not None, "artifact_checksum_invalid")
        _require(artifact.stat().st_size == size, "evidence_artifact_size_mismatch")
        _require(
            _sha256_file(artifact) == checksum,
            "evidence_artifact_checksum_mismatch",
        )
    _require(set(artifacts) == required_roles, "evidence_artifact_role_set_invalid")
    return artifact_paths


def _verify_external_artifact_references(
    evidence: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
) -> None:
    postgresql = _required_mapping(evidence.get("postgresql"), "postgresql")
    external_effect = _required_mapping(
        evidence.get("external_effect"),
        "external_effect",
    )
    orchestrator = _required_mapping(evidence.get("orchestrator"), "orchestrator")
    approval = _required_mapping(evidence.get("approval"), "approval")
    bindings = {
        ("postgresql.before_snapshot_ref", postgresql.get("before_snapshot_ref")): (
            "postgres_before_snapshot"
        ),
        ("postgresql.after_snapshot_ref", postgresql.get("after_snapshot_ref")): (
            "postgres_after_snapshot"
        ),
        (
            "external_effect.idempotency_contract_ref",
            external_effect.get("idempotency_contract_ref"),
        ): "external_effect_audit",
        ("orchestrator.run_ref", orchestrator.get("run_ref")): "orchestrator_run#run",
        ("orchestrator.traffic_freeze_ref", orchestrator.get("traffic_freeze_ref")): (
            "traffic_control#freeze"
        ),
        (
            "orchestrator.dispatcher_pause_ref",
            orchestrator.get("dispatcher_pause_ref"),
        ): "traffic_control#dispatcher",
        (
            "orchestrator.candidate_deployment_ref",
            orchestrator.get("candidate_deployment_ref"),
        ): "orchestrator_run#candidate",
        (
            "orchestrator.rollback_deployment_ref",
            orchestrator.get("rollback_deployment_ref"),
        ): "orchestrator_run#rollback",
        ("approval.record_ref", approval.get("record_ref")): "approval_record",
    }
    for (field_name, value), role_ref in bindings.items():
        role = role_ref.partition("#")[0]
        _require(role in artifact_paths, f"{field_name}_artifact_missing")
        _require(
            value == f"artifact://rollback/{role_ref}",
            f"{field_name}_artifact_ref_mismatch",
        )
    _require(
        orchestrator.get("candidate_deployment_ref")
        != orchestrator.get("rollback_deployment_ref"),
        "orchestrator_deployment_refs_not_distinct",
    )


def _verify_external_artifact_contents(
    evidence: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
) -> None:
    postgresql = _required_mapping(evidence.get("postgresql"), "postgresql")
    _before_record, before_events = _verify_postgresql_snapshot_artifact(
        evidence,
        postgresql,
        artifact_paths["postgres_before_snapshot"],
        stage="before",
    )
    _after_record, after_events = _verify_postgresql_snapshot_artifact(
        evidence,
        postgresql,
        artifact_paths["postgres_after_snapshot"],
        stage="after",
    )
    preserved_count = _positive_int(
        postgresql.get("preserved_event_count"),
        "preserved_event_count",
    )
    _require(
        len(before_events) == preserved_count,
        "postgres_before_snapshot_count_mismatch",
    )
    _require(
        len(after_events) == preserved_count + 1,
        "postgres_after_snapshot_count_mismatch",
    )
    before_bytes = tuple(canonical_json_bytes(event.to_dict()) for event in before_events)
    after_prefix_bytes = tuple(
        canonical_json_bytes(event.to_dict())
        for event in after_events[:preserved_count]
    )
    _require(
        before_bytes == after_prefix_bytes,
        "accepted_event_prefix_bytes_changed",
    )
    _require(
        after_events[-1].stream_sequence
        == _positive_int(
            postgresql.get("next_accepted_sequence"),
            "next_accepted_sequence",
        ),
        "postgres_next_event_sequence_mismatch",
    )
    _verify_external_effect_artifact(
        evidence,
        artifact_paths["external_effect_audit"],
    )
    _verify_orchestrator_artifacts(evidence, artifact_paths)
    _verify_projection_artifacts(
        evidence,
        artifact_paths,
        expected_events=before_events,
    )
    _verify_negative_test_artifact(
        evidence,
        artifact_paths["schema_security_negative_tests"],
    )


def _verify_postgresql_snapshot_artifact(
    evidence: Mapping[str, Any],
    postgresql: Mapping[str, Any],
    path: Path,
    *,
    stage: str,
) -> tuple[dict[str, Any], tuple[StoredEvent, ...]]:
    record = _read_json_object(path, f"postgres_{stage}_snapshot")
    source_ref, source_checksum = _normalized_source_proof(
        record,
        f"postgres_{stage}_snapshot",
    )
    ledgers = {
        ledger_name: {
            "count": postgresql[f"{ledger_name}_count_{stage}"],
            "checksum": postgresql[f"{ledger_name}_checksum_{stage}"],
        }
        for ledger_name in _PRESERVED_LEDGER_NAMES
    }
    common = {
        "schema": POSTGRES_SNAPSHOT_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "stage": stage,
        "source_ref": source_ref,
        "source_checksum": source_checksum,
        "backend": "postgresql",
        "database_name": postgresql.get("database_name"),
        "server_version": postgresql.get("server_version"),
        "migration_version": postgresql.get("migration_version"),
        "stream_id": postgresql.get("stream_id"),
        "ledgers": ledgers,
        "release_digest": evidence.get(
            "candidate_release_digest"
            if stage == "before"
            else "rollback_release_digest"
        ),
        "captured_at": record.get("captured_at"),
        "events": record.get("events"),
    }
    captured_at = _parse_utc_text(record.get("captured_at"), "captured_at")
    _require_not_future(captured_at, "captured_at")
    rows = record.get("events")
    _require(isinstance(rows, list) and rows, f"postgres_{stage}_events_empty")
    events: list[StoredEvent] = []
    event_ids: set[str] = set()
    for expected_sequence, row in enumerate(rows, start=1):
        _require(isinstance(row, Mapping), f"postgres_{stage}_event_invalid")
        try:
            event = StoredEvent.from_dict(row, verify_checksum=True)
        except Exception as error:
            raise RollbackDrillInvariantError(
                f"postgres_{stage}_event_integrity_invalid"
            ) from error
        _require(
            dict(row) == event.to_dict(),
            f"postgres_{stage}_event_not_canonical",
        )
        _require(
            event.stream_id == postgresql.get("stream_id"),
            f"postgres_{stage}_event_stream_mismatch",
        )
        _require(
            event.stream_sequence == expected_sequence,
            f"postgres_{stage}_event_sequence_gap",
        )
        _require(
            event.event_id not in event_ids,
            f"postgres_{stage}_event_id_duplicate",
        )
        event_ids.add(event.event_id)
        events.append(event)
    computed_source_checksum = checksum_for([event.to_dict() for event in events])
    _require(
        source_checksum == computed_source_checksum,
        f"postgres_{stage}_source_checksum_mismatch",
    )
    if stage == "before":
        prefix_checksum = checksum_for([event.to_dict() for event in events])
        expected = {
            **common,
            "event_count": postgresql.get("preserved_event_count"),
            "prefix_checksum": postgresql.get(
                "preserved_prefix_checksum_before"
            ),
            "watermark": postgresql.get("watermark_before"),
        }
        _require(
            prefix_checksum == postgresql.get("preserved_prefix_checksum_before"),
            "postgres_before_prefix_checksum_mismatch",
        )
    else:
        preserved_count = _positive_int(
            postgresql.get("preserved_event_count"),
            "preserved_event_count",
        )
        prefix_checksum = checksum_for(
            [event.to_dict() for event in events[:preserved_count]]
        )
        expected = {
            **common,
            "event_count": postgresql.get("watermark_after"),
            "preserved_prefix_count": postgresql.get("preserved_event_count"),
            "preserved_prefix_checksum": postgresql.get(
                "preserved_prefix_checksum_after"
            ),
            "watermark_after_rejections": postgresql.get(
                "watermark_after_rejections"
            ),
            "next_accepted_sequence": postgresql.get("next_accepted_sequence"),
            "watermark": postgresql.get("watermark_after"),
            "duplicate_sequences": postgresql.get("duplicate_sequences"),
            "checksum_failures": postgresql.get("checksum_failures"),
            "concurrent_writer_continuity": postgresql.get(
                "concurrent_writer_continuity"
            ),
            "crash_recovery_passed": postgresql.get("crash_recovery_passed"),
        }
        _require(
            prefix_checksum == postgresql.get("preserved_prefix_checksum_after"),
            "postgres_after_prefix_checksum_mismatch",
        )
    _require(record == expected, f"postgres_{stage}_snapshot_content_mismatch")
    _require(
        len(events) == _positive_int(record.get("event_count"), "event_count"),
        f"postgres_{stage}_event_count_mismatch",
    )
    return record, tuple(events)


def _verify_external_effect_artifact(
    evidence: Mapping[str, Any],
    path: Path,
) -> None:
    record = _read_json_object(path, "external_effect_audit")
    source_ref, source_checksum = _normalized_source_proof(
        record,
        "external_effect_audit",
    )
    external_effect = _required_mapping(
        evidence.get("external_effect"),
        "external_effect",
    )
    expected = {
        "schema": EXTERNAL_EFFECT_AUDIT_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "source_ref": source_ref,
        "source_checksum": source_checksum,
        **{
            field: external_effect.get(field)
            for field in (
                "provider",
                "provider_kind",
                "idempotency_key_hash",
                "invocation_count",
                "applied_effect_count",
                "result_checksum_before",
                "result_checksum_after",
                "audited",
            )
        },
    }
    _require(record == expected, "external_effect_artifact_content_mismatch")


def _verify_orchestrator_artifacts(
    evidence: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
) -> None:
    orchestrator = _required_mapping(evidence.get("orchestrator"), "orchestrator")
    run_record = _read_json_object(
        artifact_paths["orchestrator_run"],
        "orchestrator_run",
    )
    run_source_ref, run_source_checksum = _normalized_source_proof(
        run_record,
        "orchestrator_run",
    )
    run_id = _required_text(run_record.get("run_id"), "orchestrator_run.run_id")
    candidate_deployment_id = _required_text(
        run_record.get("candidate_deployment_id"),
        "orchestrator_run.candidate_deployment_id",
    )
    rollback_deployment_id = _required_text(
        run_record.get("rollback_deployment_id"),
        "orchestrator_run.rollback_deployment_id",
    )
    _require(
        candidate_deployment_id != rollback_deployment_id,
        "orchestrator_deployment_ids_not_distinct",
    )
    expected_run = {
        "schema": ORCHESTRATOR_RUN_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "source_ref": run_source_ref,
        "source_checksum": run_source_checksum,
        "run_id": run_id,
        "candidate_deployment_id": candidate_deployment_id,
        "rollback_deployment_id": rollback_deployment_id,
        "candidate_release_digest": evidence.get("candidate_release_digest"),
        "rollback_release_digest": evidence.get("rollback_release_digest"),
        "binary_switch_observed": orchestrator.get("binary_switch_observed"),
        "concurrent_dispatchers_observed": orchestrator.get(
            "concurrent_dispatchers_observed"
        ),
    }
    _require(run_record == expected_run, "orchestrator_run_content_mismatch")

    traffic_record = _read_json_object(
        artifact_paths["traffic_control"],
        "traffic_control",
    )
    traffic_source_ref, traffic_source_checksum = _normalized_source_proof(
        traffic_record,
        "traffic_control",
    )
    expected_traffic = {
        "schema": TRAFFIC_CONTROL_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "source_ref": traffic_source_ref,
        "source_checksum": traffic_source_checksum,
        "traffic_frozen": True,
        "dispatcher_claims_paused": orchestrator.get(
            "claims_frozen_during_switch"
        ),
        "concurrent_dispatchers_observed": orchestrator.get(
            "concurrent_dispatchers_observed"
        ),
    }
    _require(traffic_record == expected_traffic, "traffic_control_content_mismatch")


def _verify_projection_artifacts(
    evidence: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
    *,
    expected_events: Sequence[StoredEvent],
) -> None:
    postgresql = _required_mapping(evidence.get("postgresql"), "postgresql")
    records: dict[str, dict[str, Any]] = {}
    projections: dict[str, tuple[StoredEvent, ...]] = {}
    for role, release_field in (
        ("candidate_projection", "candidate_release_digest"),
        ("rollback_projection", "rollback_release_digest"),
    ):
        record = _read_json_object(artifact_paths[role], role)
        source_ref, source_checksum = _normalized_source_proof(record, role)
        rows = record.get("events")
        _require(isinstance(rows, list) and rows, f"{role}_events_empty")
        events: list[StoredEvent] = []
        for expected_sequence, row in enumerate(rows, start=1):
            _require(isinstance(row, Mapping), f"{role}_event_invalid")
            try:
                event = StoredEvent.from_dict(row, verify_checksum=True)
            except Exception as error:
                raise RollbackDrillInvariantError(
                    f"{role}_event_integrity_invalid"
                ) from error
            _require(
                event.stream_sequence == expected_sequence,
                f"{role}_event_sequence_invalid",
            )
            events.append(event)
        projection_checksum = checksum_for([event.to_dict() for event in events])
        sequence_checksum = checksum_for(
            [event.stream_sequence for event in events]
        )
        expected = {
            "schema": PROJECTION_EVIDENCE_SCHEMA,
            "drill_id": evidence.get("drill_id"),
            "role": role.removesuffix("_projection"),
            "source_ref": source_ref,
            "source_checksum": source_checksum,
            "release_digest": evidence.get(release_field),
            "stream_id": postgresql.get("stream_id"),
            "high_watermark": postgresql.get("watermark_before"),
            "event_count": postgresql.get("preserved_event_count"),
            "ordered_sequence_checksum": sequence_checksum,
            "projection_checksum": projection_checksum,
            "events": record.get("events"),
        }
        for field in ("ordered_sequence_checksum", "projection_checksum"):
            checksum = _required_text(record.get(field), f"{role}.{field}")
            _require(
                _SHA256.fullmatch(checksum) is not None,
                f"{role}_{field}_invalid",
            )
        _require(source_checksum == projection_checksum, f"{role}_source_checksum_mismatch")
        _require(record == expected, f"{role}_content_mismatch")
        records[role] = record
        projections[role] = tuple(events)
    for field in (
        "high_watermark",
        "event_count",
        "ordered_sequence_checksum",
        "projection_checksum",
    ):
        _require(
            records["candidate_projection"].get(field)
            == records["rollback_projection"].get(field),
            f"projection_{field}_mismatch",
        )
    expected_bytes = tuple(
        canonical_json_bytes(event.to_dict()) for event in expected_events
    )
    for role, events in projections.items():
        _require(
            tuple(canonical_json_bytes(event.to_dict()) for event in events)
            == expected_bytes,
            f"{role}_snapshot_mismatch",
        )


def _verify_negative_test_artifact(
    evidence: Mapping[str, Any],
    path: Path,
) -> None:
    record = _read_json_object(path, "schema_security_negative_tests")
    source_ref, source_checksum = _normalized_source_proof(
        record,
        "schema_security_negative_tests",
    )
    postgresql = _required_mapping(evidence.get("postgresql"), "postgresql")
    cases_value = record.get("cases")
    _require(isinstance(cases_value, list), "negative_test_cases_missing")
    cases: set[str] = set()
    for item in cases_value:
        _require(isinstance(item, Mapping), "negative_test_case_invalid")
        _require(
            set(item) == {"case", "outcome", "reason_class"},
            "negative_test_case_fields_invalid",
        )
        case_name = _required_text(item.get("case"), "negative_test.case")
        _require(case_name not in cases, "negative_test_case_duplicate")
        cases.add(case_name)
        _require(item.get("outcome") == "rejected", "negative_test_case_accepted")
        _required_text(item.get("reason_class"), "negative_test.reason_class")
    _require(cases == _EXTERNAL_NEGATIVE_CASES, "negative_test_case_set_invalid")
    expected = {
        "schema": NEGATIVE_TESTS_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "source_ref": source_ref,
        "source_checksum": source_checksum,
        "watermark_before": postgresql.get("watermark_before"),
        "watermark_after": postgresql.get("watermark_after_rejections"),
        "cases": cases_value,
    }
    _require(record == expected, "negative_test_artifact_content_mismatch")


def _normalized_source_proof(
    record: Mapping[str, Any],
    label: str,
) -> tuple[str, str]:
    source_ref = _require_reference(record.get("source_ref"), f"{label}.source_ref")
    _require(
        not source_ref.startswith("artifact://rollback/"),
        f"{label}_source_ref_is_self_reference",
    )
    source_checksum = _required_text(
        record.get("source_checksum"),
        f"{label}.source_checksum",
    )
    _require(
        _SHA256.fullmatch(source_checksum) is not None,
        f"{label}_source_checksum_invalid",
    )
    return source_ref, source_checksum


def _verify_approval_artifact(
    evidence: Mapping[str, Any],
    path: Path,
    *,
    trusted_public_key: Ed25519PublicKey,
) -> None:
    record = _read_json_object(path, "approval_record")
    approval = _required_mapping(evidence.get("approval"), "approval")
    artifact_checksums = {
        _required_text(item.get("role"), "artifact.role"): _required_text(
            item.get("checksum"),
            "artifact.checksum",
        )
        for item in evidence.get("artifacts", ())
        if isinstance(item, Mapping) and item.get("role") != "approval_record"
    }
    expected = {
        "schema": APPROVAL_RECORD_SCHEMA,
        "drill_id": evidence.get("drill_id"),
        "candidate_release_digest": evidence.get("candidate_release_digest"),
        "rollback_release_digest": evidence.get("rollback_release_digest"),
        "drill_completed_at": evidence.get("drill_completed_at"),
        "operator_id": approval.get("operator_id"),
        "approver_id": approval.get("approver_id"),
        "approved_at": approval.get("approved_at"),
        "decision": "approved",
        "evidence_summary_checksum": checksum_for(_approval_summary(evidence)),
        "artifact_checksums": artifact_checksums,
    }
    _require(record == expected, "approval_record_content_mismatch")
    _require(
        approval.get("record_checksum") == _sha256_file(path),
        "approval_record_checksum_mismatch",
    )
    _require(
        approval.get("public_key_fingerprint")
        == _public_key_fingerprint(trusted_public_key),
        "trusted_approval_public_key_mismatch",
    )
    try:
        signature = base64.b64decode(
            _required_text(approval.get("signature"), "approval.signature"),
            validate=True,
        )
        trusted_public_key.verify(signature, path.read_bytes())
    except (ValueError, InvalidSignature) as error:
        raise RollbackDrillInvariantError("approval_signature_invalid") from error


def _approval_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = [
        dict(item)
        for item in evidence.get("artifacts", ())
        if isinstance(item, Mapping) and item.get("role") != "approval_record"
    ]
    artifacts.sort(key=lambda item: str(item.get("role")))
    return {
        "schema": evidence.get("schema"),
        "drill_id": evidence.get("drill_id"),
        "drill_completed_at": evidence.get("drill_completed_at"),
        "candidate_release_digest": evidence.get("candidate_release_digest"),
        "rollback_release_digest": evidence.get("rollback_release_digest"),
        "postgresql": evidence.get("postgresql"),
        "external_effect": evidence.get("external_effect"),
        "orchestrator": evidence.get("orchestrator"),
        "external_gates": evidence.get("external_gates"),
        "artifacts": artifacts,
    }


def _verify_postgresql_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "backend",
        "database_name",
        "server_version",
        "migration_version",
        "before_snapshot_ref",
        "after_snapshot_ref",
        "stream_id",
        "preserved_event_count",
        "preserved_prefix_checksum_before",
        "preserved_prefix_checksum_after",
        "watermark_before",
        "watermark_after_rejections",
        "next_accepted_sequence",
        "watermark_after",
        "duplicate_sequences",
        "checksum_failures",
        "concurrent_writer_continuity",
        "crash_recovery_passed",
    }
    for ledger_name in _PRESERVED_LEDGER_NAMES:
        required.update(
            {
                f"{ledger_name}_count_before",
                f"{ledger_name}_count_after",
                f"{ledger_name}_checksum_before",
                f"{ledger_name}_checksum_after",
            }
        )
    _require(set(value) == required, "postgres_evidence_fields_invalid")
    _require(value.get("backend") == "postgresql", "postgres_backend_invalid")
    database_name = _required_text(value.get("database_name"), "database_name")
    _require(
        any(token in database_name.lower() for token in ("test", "staging", "rollback")),
        "postgres_database_not_isolated",
    )
    for field in ("server_version", "migration_version", "stream_id"):
        _required_text(value.get(field), field)
    _require_reference(value.get("before_snapshot_ref"), "before_snapshot_ref")
    _require_reference(value.get("after_snapshot_ref"), "after_snapshot_ref")
    for field in (
        "preserved_prefix_checksum_before",
        "preserved_prefix_checksum_after",
    ):
        checksum = _required_text(value.get(field), field)
        _require(_SHA256.fullmatch(checksum) is not None, f"{field}_invalid")
    _require(
        value["preserved_prefix_checksum_before"]
        == value["preserved_prefix_checksum_after"],
        "accepted_event_prefix_changed",
    )
    count = _positive_int(value.get("preserved_event_count"), "preserved_event_count")
    before = _positive_int(value.get("watermark_before"), "watermark_before")
    after_rejections = _nonnegative_int(
        value.get("watermark_after_rejections"),
        "watermark_after_rejections",
    )
    next_sequence = _positive_int(
        value.get("next_accepted_sequence"),
        "next_accepted_sequence",
    )
    after = _positive_int(value.get("watermark_after"), "watermark_after")
    _require(count == before, "preserved_event_count_watermark_mismatch")
    _require(after_rejections == before, "rejected_event_allocated_sequence")
    _require(next_sequence == before + 1, "rollback_sequence_not_contiguous")
    _require(after == next_sequence, "rollback_watermark_invalid")
    _require(
        _nonnegative_int(value.get("duplicate_sequences"), "duplicate_sequences") == 0,
        "postgres_duplicate_sequence",
    )
    _require(
        _nonnegative_int(value.get("checksum_failures"), "checksum_failures") == 0,
        "postgres_checksum_failure",
    )
    for ledger_name in _PRESERVED_LEDGER_NAMES:
        before_count = _positive_int(
            value.get(f"{ledger_name}_count_before"),
            f"{ledger_name}_count_before",
        )
        after_count = _positive_int(
            value.get(f"{ledger_name}_count_after"),
            f"{ledger_name}_count_after",
        )
        _require(
            before_count == after_count,
            f"postgres_{ledger_name}_count_changed",
        )
        before_checksum = _required_text(
            value.get(f"{ledger_name}_checksum_before"),
            f"{ledger_name}_checksum_before",
        )
        after_checksum = _required_text(
            value.get(f"{ledger_name}_checksum_after"),
            f"{ledger_name}_checksum_after",
        )
        _require(
            _SHA256.fullmatch(before_checksum) is not None,
            f"{ledger_name}_checksum_before_invalid",
        )
        _require(
            _SHA256.fullmatch(after_checksum) is not None,
            f"{ledger_name}_checksum_after_invalid",
        )
        _require(
            before_checksum == after_checksum,
            f"postgres_{ledger_name}_checksum_changed",
        )
    for field in ("concurrent_writer_continuity", "crash_recovery_passed"):
        _require(value.get(field) is True, f"postgres_{field}_failed")


def _verify_external_effect_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "provider",
        "provider_kind",
        "idempotency_contract_ref",
        "idempotency_key_hash",
        "invocation_count",
        "applied_effect_count",
        "result_checksum_before",
        "result_checksum_after",
        "audited",
    }
    _require(set(value) == required, "external_effect_fields_invalid")
    _required_text(value.get("provider"), "provider")
    _require(
        value.get("provider_kind")
        in {"staging_provider", "staging_database", "production_provider"},
        "external_effect_provider_kind_invalid",
    )
    _require_reference(value.get("idempotency_contract_ref"), "idempotency_contract_ref")
    for field in (
        "idempotency_key_hash",
        "result_checksum_before",
        "result_checksum_after",
    ):
        checksum = _required_text(value.get(field), field)
        _require(_SHA256.fullmatch(checksum) is not None, f"{field}_invalid")
    _require(
        _positive_int(value.get("invocation_count"), "invocation_count") >= 2,
        "external_effect_retry_not_observed",
    )
    _require(
        _positive_int(value.get("applied_effect_count"), "applied_effect_count") == 1,
        "external_effect_repeated",
    )
    _require(
        value["result_checksum_before"] == value["result_checksum_after"],
        "external_effect_result_changed",
    )
    _require(value.get("audited") is True, "external_effect_not_audited")


def _verify_orchestrator_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "run_ref",
        "traffic_freeze_ref",
        "dispatcher_pause_ref",
        "candidate_deployment_ref",
        "rollback_deployment_ref",
        "binary_switch_observed",
        "claims_frozen_during_switch",
        "concurrent_dispatchers_observed",
    }
    _require(set(value) == required, "orchestrator_fields_invalid")
    for field in (
        "run_ref",
        "traffic_freeze_ref",
        "dispatcher_pause_ref",
        "candidate_deployment_ref",
        "rollback_deployment_ref",
    ):
        _require_reference(value.get(field), field)
    _require(value.get("binary_switch_observed") is True, "binary_switch_not_observed")
    _require(
        value.get("claims_frozen_during_switch") is True,
        "dispatcher_claims_not_frozen",
    )
    _require(
        _nonnegative_int(
            value.get("concurrent_dispatchers_observed"),
            "concurrent_dispatchers_observed",
        )
        == 0,
        "concurrent_dispatchers_observed",
    )


def _verify_approval(
    value: Mapping[str, Any],
    *,
    drill_completed_at: datetime,
) -> None:
    required = {
        "operator_id",
        "approver_id",
        "approved_at",
        "decision",
        "record_ref",
        "record_checksum",
        "public_key_fingerprint",
        "signature",
    }
    _require(set(value) == required, "approval_fields_invalid")
    operator_id = _required_text(value.get("operator_id"), "operator_id")
    approver_id = _required_text(value.get("approver_id"), "approver_id")
    _require(operator_id != approver_id, "approval_separation_missing")
    approved_at = _parse_utc_text(value.get("approved_at"), "approved_at")
    _require(
        approved_at >= drill_completed_at,
        "approval_predates_drill_completion",
    )
    _require_not_future(approved_at, "approved_at")
    _require(value.get("decision") == "approved", "rollback_not_approved")
    _require_reference(value.get("record_ref"), "approval.record_ref")
    for field in ("record_checksum", "public_key_fingerprint"):
        _require(
            _SHA256.fullmatch(_required_text(value.get(field), f"approval.{field}"))
            is not None,
            f"approval_{field}_invalid",
        )
    try:
        base64.b64decode(
            _required_text(value.get("signature"), "approval.signature"),
            validate=True,
        )
    except ValueError as error:
        raise RollbackDrillInvariantError("approval_signature_invalid") from error


def _validate_qualification_target(
    target: Path,
    *,
    local_path: Path,
    external_path: Path,
    private_key_path: Path,
    external_public_key_path: Path,
    approval_public_key_path: Path,
) -> None:
    bundle_root = target.parent
    _require(
        target
        not in {
            local_path,
            external_path,
            private_key_path,
            external_public_key_path,
            approval_public_key_path,
        },
        "qualification_output_alias",
    )
    _require(not target.exists(), "qualification_output_exists")
    _require(not bundle_root.exists(), "qualification_bundle_root_exists")
    for source_root in {local_path.parent, external_path.parent}:
        _require(
            not bundle_root.is_relative_to(source_root),
            "qualification_output_inside_input_bundle",
        )


def _materialize_qualification_bundle(
    target: Path,
    *,
    local_path: Path,
    external_path: Path,
    external: Mapping[str, Any],
    evidence: Mapping[str, Any],
    trusted_public_key: Ed25519PublicKey,
    trusted_external_public_key: Ed25519PublicKey,
    trusted_approval_public_key: Ed25519PublicKey,
) -> None:
    root = target.parent
    root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = root.with_name(f".{root.name}.{uuid4().hex}.tmp")
    _require(not temporary_root.exists(), "qualification_temporary_bundle_exists")
    temporary_root.mkdir()
    try:
        local = _read_json_object(local_path, "local_evidence")
        _copy_evidence_bundle(
            local_path,
            local,
            target_root=temporary_root / "local",
            evidence_name="rollback-evidence.json",
        )
        _copy_evidence_bundle(
            external_path,
            external,
            target_root=temporary_root / "external",
            evidence_name="external-evidence.json",
        )
        temporary_target = temporary_root / target.name
        _write_bytes_atomic(
            temporary_target,
            (stable_json_dumps(evidence) + "\n").encode("utf-8"),
        )
        _require(
            _read_json_object(temporary_target, "qualification_evidence")
            == dict(evidence),
            "qualification_materialization_mismatch",
        )
        _verify_qualification_evidence(
            temporary_target,
            _read_json_object(temporary_target, "qualification_evidence"),
            trusted_public_key=trusted_public_key,
            trusted_external_public_key=trusted_external_public_key,
            trusted_approval_public_key=trusted_approval_public_key,
        )
        _publish_new_directory(
            temporary_root,
            root,
            marker_name=target.name,
            exists_reason="qualification_bundle_root_exists",
        )
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def _copy_evidence_bundle(
    source_path: Path,
    evidence: Mapping[str, Any],
    *,
    target_root: Path,
    evidence_name: str,
) -> None:
    source_root = _bundle_root(source_path, evidence)
    target_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, target_root / evidence_name)
    artifacts = evidence.get("artifacts")
    _require(isinstance(artifacts, list), "evidence_artifacts_missing")
    for item in artifacts:
        _require(isinstance(item, Mapping), "evidence_artifact_invalid")
        relative = _portable_relative_path(
            item.get("path"),
            "artifact.path",
            absolute_reason="evidence_artifact_path_absolute",
        )
        source = (source_root / relative).resolve(strict=True)
        _require(source.is_relative_to(source_root), "evidence_artifact_escaped_bundle")
        target = (target_root / relative).resolve(strict=False)
        _require(target.is_relative_to(target_root), "target_artifact_escaped_bundle")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _bundle_root(path: Path, evidence: Mapping[str, Any]) -> Path:
    configured = evidence.get("artifact_root", ".")
    relative = _portable_relative_path(
        configured,
        "artifact_root",
        absolute_reason="artifact_root_absolute",
    )
    root = (path.parent / relative).resolve(strict=True)
    _require(root.is_relative_to(path.parent), "artifact_root_escaped_bundle")
    return root


def _bundle_reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    relative = _portable_relative_path(
        value.get("bundle_path"),
        f"{label}.bundle_path",
        absolute_reason=f"{label}_path_absolute",
    )
    resolved_root = root.resolve(strict=True)
    path = (resolved_root / relative).resolve(strict=True)
    _require(path.is_relative_to(resolved_root), f"{label}_path_escaped")
    checksum = _required_text(value.get("checksum"), f"{label}.checksum")
    _require(_SHA256.fullmatch(checksum) is not None, f"{label}_checksum_invalid")
    return path


def _portable_relative_path(
    value: Any,
    field_name: str,
    *,
    absolute_reason: str,
) -> Path:
    text = _required_text(value, field_name)
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    _require(
        not posix.is_absolute()
        and not windows.is_absolute()
        and not windows.drive,
        absolute_reason,
    )
    _require(
        ".." not in posix.parts and ".." not in windows.parts,
        f"{field_name}_traversal",
    )
    _require(":" not in text, f"{field_name}_alternate_data_stream")
    parts = tuple(
        part
        for part in {*posix.parts, *windows.parts}
        if part not in {"", ".", "\\", "/"}
    )
    for part in parts:
        _require(
            not part.endswith((" ", ".")),
            f"{field_name}_windows_trailing_character",
        )
        basename = part.rstrip(" .").split(".", 1)[0].upper()
        _require(
            basename not in _WINDOWS_RESERVED_NAMES,
            f"{field_name}_windows_reserved_name",
        )
    if field_name.endswith("artifact.path"):
        _require(text not in {".", "./", ".\\"}, f"{field_name}_invalid")
    return Path(text)


def _require_not_reparse_point(path: Path, reason: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RollbackDrillInvariantError(reason) from error
    is_reparse = path.is_symlink()
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_flag:
        is_reparse = is_reparse or bool(attributes & reparse_flag)
    _require(not is_reparse, reason)


def _require_path_components_not_reparse(
    root: Path,
    path: Path,
    reason: str,
) -> None:
    current = root
    _require_not_reparse_point(current, reason)
    for part in path.relative_to(root).parts:
        current = current / part
        _require_not_reparse_point(current, reason)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require_not_reparse_point(path, f"{label}_reparse_point")
    _require(path.is_file(), f"{label}_not_regular_file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RollbackDrillInvariantError(f"{label}_not_readable") from error
    _require(isinstance(payload, Mapping), f"{label}_root_not_object")
    return dict(payload)


def _required_mapping(value: Any, field_name: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{field_name}_not_object")
    return dict(value)


def _require_reference(value: Any, field_name: str) -> str:
    reference = _required_text(value, field_name)
    _require(_REFERENCE.fullmatch(reference) is not None, f"{field_name}_invalid")
    return reference


def _nonnegative_int(value: Any, field_name: str) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{field_name}_invalid",
    )
    return int(value)


def _positive_int(value: Any, field_name: str) -> int:
    result = _nonnegative_int(value, field_name)
    _require(result > 0, f"{field_name}_invalid")
    return result


def _parse_utc_text(value: Any, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise RollbackDrillInvariantError(f"{field_name}_invalid") from error
    _require(parsed.tzinfo is not None, f"{field_name}_invalid")
    return parsed.astimezone(UTC)


def _require_not_future(value: datetime, field_name: str) -> None:
    _require(
        value <= datetime.now(UTC) + _MAX_EVIDENCE_CLOCK_SKEW,
        f"{field_name}_in_future",
    )


def _qualification_signature_payload(evidence: Mapping[str, Any]) -> bytes:
    payload = dict(evidence)
    payload.pop("signature", None)
    return stable_json_dumps(payload).encode("utf-8")


def _external_attestation_payload(
    evidence: Mapping[str, Any],
    attestation: Mapping[str, Any],
) -> bytes:
    return stable_json_dumps(
        {
            "evidence": dict(evidence),
            "attestation": dict(attestation),
        }
    ).encode("utf-8")


def _verify_external_attestation(
    evidence: Mapping[str, Any],
    value: Any,
    *,
    trusted_public_key: Ed25519PublicKey,
) -> None:
    attestation = _required_mapping(value, "attestation")
    signature_text = attestation.pop("signature", None)
    _require(
        set(attestation)
        == {"algorithm", "public_key_fingerprint", "attested_at"},
        "external_attestation_fields_invalid",
    )
    _require(
        attestation.get("algorithm") == EXTERNAL_ATTESTATION_ALGORITHM,
        "external_attestation_algorithm_invalid",
    )
    _require(
        attestation.get("public_key_fingerprint")
        == _public_key_fingerprint(trusted_public_key),
        "trusted_external_public_key_mismatch",
    )
    attested_at = _parse_utc_text(attestation.get("attested_at"), "attested_at")
    _require_not_future(attested_at, "attested_at")
    approval = _required_mapping(evidence.get("approval"), "approval")
    approved_at = _parse_utc_text(approval.get("approved_at"), "approved_at")
    _require(attested_at >= approved_at, "attestation_predates_approval")
    try:
        signature = base64.b64decode(
            _required_text(signature_text, "attestation.signature"),
            validate=True,
        )
        trusted_public_key.verify(
            signature,
            _external_attestation_payload(evidence, attestation),
        )
    except (ValueError, InvalidSignature) as error:
        raise RollbackDrillInvariantError(
            "external_attestation_signature_invalid"
        ) from error


def _load_private_key(path: str | Path) -> Ed25519PrivateKey:
    resolved = Path(path).resolve(strict=True)
    _verify_private_key_permissions(resolved)
    try:
        value = serialization.load_pem_private_key(
            resolved.read_bytes(),
            password=None,
        )
    except (OSError, ValueError, TypeError) as error:
        raise RollbackDrillInvariantError("private_key_invalid") from error
    _require(isinstance(value, Ed25519PrivateKey), "private_key_not_ed25519")
    return value


def _load_public_key(path: str | Path) -> Ed25519PublicKey:
    try:
        payload = Path(path).resolve(strict=True).read_bytes()
        value = serialization.load_pem_public_key(payload)
    except (OSError, ValueError, TypeError) as error:
        raise RollbackDrillInvariantError("trusted_public_key_invalid") from error
    _require(isinstance(value, Ed25519PublicKey), "trusted_key_not_ed25519")
    return value


def _coerce_public_key(
    value: str | Path | Ed25519PublicKey,
) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    return _load_public_key(value)


def _require_distinct_authorities(*keys: Ed25519PublicKey) -> None:
    fingerprints = {_public_key_fingerprint(key) for key in keys}
    _require(
        len(fingerprints) == len(keys),
        "signing_authority_separation_missing",
    )


def _public_key_fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def generate_signing_keypair(
    *,
    private_key_path: str | Path,
    public_key_path: str | Path,
) -> dict[str, str]:
    private_target = Path(private_key_path).resolve(strict=False)
    public_target = Path(public_key_path).resolve(strict=False)
    _require(private_target != public_target, "signing_key_paths_alias")
    _require(not private_target.exists(), "private_key_already_exists")
    _require(not public_target.exists(), "public_key_already_exists")
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write_bytes_new_atomic(
        public_target,
        public_bytes,
        exists_reason="public_key_already_exists",
    )
    try:
        _write_private_key_atomic(private_target, private_bytes)
    except Exception:
        public_target.unlink(missing_ok=True)
        raise
    return {
        "private_key": str(private_target),
        "public_key": str(public_target),
        "public_key_fingerprint": _public_key_fingerprint(key.public_key()),
    }


def _drill_catalog():
    catalog = default_event_schema_catalog()
    catalog.register(
        EventSchemaRegistration(
            event_type=DRILL_EVENT_TYPE,
            data_schema=DRILL_DATA_SCHEMA,
            json_schema={
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "message": {"type": "string", "minLength": 1},
                    "private_note": {"type": "string"},
                    "blocked_value": {"type": "string"},
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            sensitivity_policy=SensitivityPolicy(
                field_rules={
                    "/private_note": FieldDisposition.SENSITIVE,
                    "/blocked_value": FieldDisposition.FORBIDDEN,
                },
                redact_sensitive=True,
            ),
            current=True,
            authoritative_context_fields=("run_id",),
        )
    )
    return catalog


def _subscription() -> DurableSubscription:
    return DurableSubscription(
        subscription_id=DRILL_SUBSCRIPTION_ID,
        subscription_version=1,
        consumer_id=DRILL_CONSUMER_ID,
        event_filter=SubscriptionFilter(
            event_types=frozenset({DRILL_EVENT_TYPE}),
            data_schemas=frozenset({DRILL_DATA_SCHEMA}),
        ),
        effect=ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id=DRILL_EFFECT_ID,
            idempotency_strategy=EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY,
        ),
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=1,
            multiplier=1,
            max_delay_seconds=1,
            jitter_ratio=0,
        ),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=10,
        ),
        tenant_id=DRILL_TENANT_ID,
    )


def _publish_request(
    *,
    event_id: str,
    message: str,
    occurred_at: datetime,
    data_schema: str = DRILL_DATA_SCHEMA,
    private_note: str | None = None,
    blocked_value: str | None = None,
) -> EventPublishRequest:
    payload: dict[str, Any] = {"message": message}
    if private_note is not None:
        payload["private_note"] = private_note
    if blocked_value is not None:
        payload["blocked_value"] = blocked_value
    return EventPublishRequest(
        event_id=event_id,
        event_type=DRILL_EVENT_TYPE,
        data_schema=data_schema,
        source="scripts.durable_event_rollback_drill",
        occurred_at=occurred_at,
        stream_id=DRILL_STREAM_ID,
        business_context=BusinessContext(run_id=DRILL_RUN_ID),
        producer=ProducerIdentity(
            component="durable-event-rollback-drill",
            version="1",
        ),
        tenant_id=DRILL_TENANT_ID,
        payload=payload,
    )


def _publish_rejected_as(
    runtime: EventRuntime,
    request: EventPublishRequest,
    expected_error: type[Exception],
) -> bool:
    try:
        runtime.publish(request)
    except expected_error:
        return True
    return False


def _passed_phase(
    name: str,
    *,
    assertions: Mapping[str, bool],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_assertions = dict(assertions)
    _require(
        normalized_assertions
        and all(value is True for value in normalized_assertions.values()),
        f"phase_failed:{name}",
    )
    return {
        "phase": _required_text(name, "phase"),
        "status": "passed",
        "assertions": normalized_assertions,
        "evidence": dict(evidence),
    }


def _artifact_manifest(
    workspace: Path,
    artifacts: Sequence[tuple[str, Path]],
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for role, path in artifacts:
        resolved = path.resolve(strict=True)
        _require(resolved.is_relative_to(workspace), "artifact_outside_workspace")
        manifest.append(
            {
                "role": _required_text(role, "artifact.role"),
                "path": resolved.relative_to(workspace).as_posix(),
                "size_bytes": resolved.stat().st_size,
                "checksum": _sha256_file(resolved),
            }
        )
    return manifest


def _prepare_workspace(value: str | Path) -> Path:
    path = Path(value).resolve(strict=False)
    if path.exists() and any(path.iterdir()):
        raise ValueError("rollback drill workspace must be empty")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_evidence_target(
    workspace: Path,
    value: str | Path | None,
) -> Path:
    target = (
        workspace / "rollback-evidence.json"
        if value is None
        else Path(value).resolve(strict=False)
    )
    _require(
        target.parent == workspace,
        "local_evidence_output_outside_workspace",
    )
    _require(target.suffix.lower() == ".json", "local_evidence_output_not_json")
    _require(not target.exists(), "local_evidence_output_exists")
    return target


def _require_secret_absent(root: Path, secret: str) -> None:
    needle = secret.encode("utf-8")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                if needle in chunk:
                    raise RollbackDrillInvariantError("raw_secret_persisted")


def _write_private_key_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        _restrict_private_key_permissions(temporary)
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _verify_private_key_permissions(temporary)
        _publish_new_file(
            temporary,
            path,
            exists_reason="private_key_already_exists",
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def _restrict_private_key_permissions(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return
    try:
        import ntsecuritycon
        import win32security
    except ImportError as error:
        raise RollbackDrillInvariantError(
            "private_key_acl_dependency_unavailable"
        ) from error
    owner = _current_windows_user_sid()
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAceEx(
        win32security.ACL_REVISION_DS,
        0,
        ntsecuritycon.FILE_ALL_ACCESS,
        owner,
    )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(owner, 0)
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(
        str(path),
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        descriptor,
    )


def _verify_private_key_permissions(path: Path) -> None:
    if os.name != "nt":
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        _require(mode & 0o077 == 0, "private_key_permissions_insecure")
        _require(
            metadata.st_uid == os.geteuid(),
            "private_key_owner_mismatch",
        )
        return
    try:
        import win32security
    except ImportError as error:
        raise RollbackDrillInvariantError(
            "private_key_acl_dependency_unavailable"
        ) from error
    descriptor = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    owner = descriptor.GetSecurityDescriptorOwner()
    current_user = _current_windows_user_sid()
    _require(
        win32security.ConvertSidToStringSid(owner)
        == win32security.ConvertSidToStringSid(current_user),
        "private_key_owner_mismatch",
    )
    control, _revision = descriptor.GetSecurityDescriptorControl()
    _require(
        bool(control & win32security.SE_DACL_PROTECTED),
        "private_key_permissions_insecure",
    )
    dacl = descriptor.GetSecurityDescriptorDacl()
    _require(dacl is not None, "private_key_permissions_insecure")
    _require(dacl.GetAceCount() == 1, "private_key_permissions_insecure")
    header, mask, sid = dacl.GetAce(0)
    ace_type, ace_flags = header
    _require(
        ace_type == win32security.ACCESS_ALLOWED_ACE_TYPE,
        "private_key_permissions_insecure",
    )
    _require(
        win32security.ConvertSidToStringSid(sid)
        == win32security.ConvertSidToStringSid(current_user),
        "private_key_permissions_insecure",
    )
    _require(
        not (ace_flags & win32security.INHERITED_ACE),
        "private_key_permissions_insecure",
    )
    _require(
        (mask & _WINDOWS_PRIVATE_KEY_WRITE_MASK)
        == _WINDOWS_PRIVATE_KEY_WRITE_MASK,
        "private_key_permissions_insecure",
    )


def _current_windows_user_sid():
    try:
        import win32api
        import win32con
        import win32security
    except ImportError as error:
        raise RollbackDrillInvariantError(
            "private_key_acl_dependency_unavailable"
        ) from error
    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_QUERY,
    )
    try:
        return win32security.GetTokenInformation(
            token,
            win32security.TokenUser,
        )[0]
    finally:
        token.Close()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_bytes_new_atomic(
    path: Path,
    payload: bytes,
    *,
    exists_reason: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_new_file(temporary, path, exists_reason=exists_reason)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _publish_new_file(
    source: Path,
    target: Path,
    *,
    exists_reason: str,
) -> None:
    try:
        os.link(source, target)
    except FileExistsError as error:
        raise RollbackDrillInvariantError(exists_reason) from error
    source.unlink()


def _publish_new_directory(
    source: Path,
    target: Path,
    *,
    marker_name: str,
    exists_reason: str,
) -> None:
    if os.name == "nt":
        try:
            os.rename(source, target)
        except OSError as error:
            if target.exists():
                raise RollbackDrillInvariantError(exists_reason) from error
            raise
        return

    if sys.platform.startswith("linux") and _linux_rename_noreplace(
        source,
        target,
        exists_reason=exists_reason,
    ):
        return
    _publish_directory_with_marker(
        source,
        target,
        marker_name=marker_name,
        exists_reason=exists_reason,
    )


def _linux_rename_noreplace(
    source: Path,
    target: Path,
    *,
    exists_reason: str,
) -> bool:
    import ctypes
    import errno

    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        return False
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(target),
        1,
    )
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise RollbackDrillInvariantError(exists_reason)
    if error_number in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        return False
    raise OSError(error_number, os.strerror(error_number), str(target))


def _publish_directory_with_marker(
    source: Path,
    target: Path,
    *,
    marker_name: str,
    exists_reason: str,
) -> None:
    try:
        target.mkdir()
    except FileExistsError as error:
        raise RollbackDrillInvariantError(exists_reason) from error
    try:
        marker = source / marker_name
        _require(marker.is_file(), "qualification_marker_missing")
        for child in source.iterdir():
            if child != marker:
                os.rename(child, target / child.name)
        _publish_new_file(
            marker,
            target / marker.name,
            exists_reason="qualification_output_exists",
        )
        source.rmdir()
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("time must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("time must be timezone-aware")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RollbackDrillInvariantError(reason)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.durable_event_rollback_drill",
        description="Execute and verify the durable-event phase rollback drill.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the isolated rollback drill")
    run.add_argument("--workspace", required=True)
    run.add_argument("--evidence")
    run.add_argument("--drill-id")
    run.add_argument(
        "--candidate-release",
        default="local-working-tree-candidate",
    )
    run.add_argument(
        "--rollback-release",
        default="local-working-tree-compatible",
    )
    keygen = commands.add_parser(
        "keygen",
        help="Generate an Ed25519 keypair for trusted release qualification",
    )
    keygen.add_argument("--private-key", required=True)
    keygen.add_argument("--public-key", required=True)
    attest = commands.add_parser(
        "attest-external",
        help="Sign validated deployment evidence with an independent authority",
    )
    attest.add_argument("--evidence", required=True)
    attest.add_argument("--private-key", required=True)
    attest.add_argument("--trusted-approval-public-key", required=True)
    attest.add_argument("--output", required=True)
    qualify = commands.add_parser(
        "qualify",
        help="Create signed release evidence from local and external bundles",
    )
    qualify.add_argument("--local-evidence", required=True)
    qualify.add_argument("--external-evidence", required=True)
    qualify.add_argument("--private-key", required=True)
    qualify.add_argument("--trusted-external-public-key", required=True)
    qualify.add_argument("--trusted-approval-public-key", required=True)
    qualify.add_argument("--output", required=True)
    verify = commands.add_parser(
        "verify",
        help="Verify evidence and all retained artifact checksums",
    )
    verify.add_argument("--evidence", required=True)
    verify.add_argument(
        "--allow-incomplete-local",
        action="store_true",
        help="verify local invariants without qualifying the release rollback gate",
    )
    verify.add_argument(
        "--trusted-public-key",
        help="required Ed25519 public key for release qualification evidence",
    )
    verify.add_argument(
        "--trusted-external-public-key",
        help="required independent deployment-attestation public key",
    )
    verify.add_argument(
        "--trusted-approval-public-key",
        help="required independent rollback-approval public key",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            evidence = run_rollback_drill(
                workspace=args.workspace,
                evidence_path=args.evidence,
                drill_id=args.drill_id,
                candidate_release=args.candidate_release,
                rollback_release=args.rollback_release,
            )
            evidence_path = (
                Path(args.evidence).resolve()
                if args.evidence
                else Path(args.workspace).resolve() / "rollback-evidence.json"
            )
        elif args.command == "keygen":
            result = generate_signing_keypair(
                private_key_path=args.private_key,
                public_key_path=args.public_key,
            )
            print(stable_json_dumps({"status": "generated", **result}))
            return 0
        elif args.command == "attest-external":
            evidence = attest_external_evidence(
                evidence_path=args.evidence,
                private_key_path=args.private_key,
                trusted_approval_public_key=args.trusted_approval_public_key,
                output_path=args.output,
            )
            evidence_path = Path(args.output).resolve()
            print(
                stable_json_dumps(
                    {
                        "status": "attested",
                        "evidence": str(evidence_path),
                        "evidence_checksum": evidence["evidence_checksum"],
                    }
                )
            )
            return 0
        elif args.command == "qualify":
            evidence = qualify_rollback_evidence(
                local_evidence_path=args.local_evidence,
                external_evidence_path=args.external_evidence,
                private_key_path=args.private_key,
                trusted_external_public_key=args.trusted_external_public_key,
                trusted_approval_public_key=args.trusted_approval_public_key,
                output_path=args.output,
            )
            evidence_path = Path(args.output).resolve()
        else:
            evidence = verify_rollback_evidence(
                args.evidence,
                allow_incomplete_local=args.allow_incomplete_local,
                trusted_public_key=args.trusted_public_key,
                trusted_external_public_key=args.trusted_external_public_key,
                trusted_approval_public_key=args.trusted_approval_public_key,
            )
            evidence_path = Path(args.evidence).resolve()
    except Exception as error:
        print(
            stable_json_dumps(
                {
                    "status": "failed",
                    "reason_class": type(error).__name__,
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
    if evidence["overall_status"] == "passed":
        return 0
    if args.command == "verify" and args.allow_incomplete_local:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
