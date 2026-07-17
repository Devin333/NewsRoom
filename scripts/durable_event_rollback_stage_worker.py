from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sqlite3
import subprocess
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


WORKER_SCHEMA = "newsroom.durable-event-rollback-stage-worker/v1"
CONFIG_SCHEMA = "newsroom.durable-event-rollback-staging-config/v1"
CRASH_EXIT_CODE = 86
STAGING_DSN_ENV = "NEWS_ROLLBACK_STAGING_DSN"

EFFECT_EVENT_TYPE = "io.newsroom.event.rollback.effect"
DLQ_EVENT_TYPE = "io.newsroom.event.rollback.dead-letter"
CONTINUITY_EVENT_TYPE = "io.newsroom.event.rollback.continuity"
DATA_SCHEMA = "io.newsroom.event.rollback.staging/v1"
EFFECT_SUBSCRIPTION_ID = "rollback-staging-effect"
EFFECT_CONSUMER_ID = "rollback-staging-effect-consumer"
EFFECT_ID = "rollback-staging-external-effect"
PRESERVED_SUBSCRIPTION_ID = "rollback-staging-preserved-ledger"
PRESERVED_CONSUMER_ID = "rollback-staging-preserved-ledger-consumer"
PRESERVED_EFFECT_ID = "rollback-staging-preserved-ledger-effect"
LEASE_SECONDS = 5.0


class StagingWorkerError(RuntimeError):
    """A release worker could not prove its assigned rollback invariant."""


class _ExternalEffectLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
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
                    content_checksum TEXT NOT NULL,
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
    ) -> None:
        invoked_at = _utc_text(datetime.now(UTC))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO effect_invocations "
                "(idempotency_key, event_id, content_checksum, invoked_at) "
                "VALUES (?, ?, ?, ?)",
                (idempotency_key, event_id, content_checksum, invoked_at),
            )
            connection.execute(
                "INSERT OR IGNORE INTO applied_effects "
                "(idempotency_key, event_id, content_checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (idempotency_key, event_id, content_checksum, invoked_at),
            )
            row = connection.execute(
                "SELECT event_id, content_checksum FROM applied_effects "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row != (event_id, content_checksum):
                connection.rollback()
                raise StagingWorkerError("external_effect_identity_collision")
            connection.commit()

    def snapshot(self) -> dict[str, Any]:
        with self._connection() as connection:
            applied = [
                dict(zip(("idempotency_key", "event_id", "content_checksum", "applied_at"), row))
                for row in connection.execute(
                    "SELECT idempotency_key, event_id, content_checksum, applied_at "
                    "FROM applied_effects ORDER BY idempotency_key"
                ).fetchall()
            ]
            invocations = [
                dict(
                    zip(
                        (
                            "invocation_id",
                            "idempotency_key",
                            "event_id",
                            "content_checksum",
                            "invoked_at",
                        ),
                        row,
                    )
                )
                for row in connection.execute(
                    "SELECT invocation_id, idempotency_key, event_id, "
                    "content_checksum, invoked_at FROM effect_invocations "
                    "ORDER BY invocation_id"
                ).fetchall()
            ]
        return {
            "applied_effects": applied,
            "invocations": invocations,
            "applied_effect_count": len(applied),
            "invocation_count": len(invocations),
            "result_checksum": _checksum(applied),
        }

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path)
        try:
            yield connection
        finally:
            connection.close()


def _load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve(strict=True)
    payload = json.loads(
        config_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise StagingWorkerError("config_root_invalid")
    config = dict(payload)
    required = {
        "schema",
        "drill_id",
        "workspace",
        "database_name",
        "stream_id",
        "run_id",
        "tenant_id",
        "occurred_at_base",
        "event_count",
        "effect_database",
        "candidate_projection_root",
        "rollback_projection_root",
    }
    if set(config) != required or config.get("schema") != CONFIG_SCHEMA:
        raise StagingWorkerError("config_fields_invalid")
    workspace = Path(_required_text(config.get("workspace"), "workspace"))
    _require_path_without_reparse(workspace, must_exist=True)
    workspace = workspace.resolve(strict=True)
    for field in (
        "effect_database",
        "candidate_projection_root",
        "rollback_projection_root",
    ):
        target = Path(_required_text(config.get(field), field)).resolve(strict=False)
        if not target.is_relative_to(workspace):
            raise StagingWorkerError(f"{field}_outside_workspace")
        _require_path_without_reparse(target.parent, must_exist=True)
        config[field] = str(target)
    event_count = config.get("event_count")
    if not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 6:
        raise StagingWorkerError("event_count_invalid")
    config["workspace"] = str(workspace)
    _parse_utc(config.get("occurred_at_base"), "occurred_at_base")
    for field in ("drill_id", "database_name", "stream_id", "run_id", "tenant_id"):
        config[field] = _required_text(config.get(field), field)
    return config


def _bootstrap_release(release_root: str | Path, expected_digest: str) -> Path:
    unresolved = Path(release_root)
    _require_path_without_reparse(unresolved, must_exist=True)
    root = unresolved.resolve(strict=True)
    if not root.is_dir():
        raise StagingWorkerError("release_root_not_directory")
    digest = _git(root, "rev-parse", "HEAD")
    if digest != expected_digest:
        raise StagingWorkerError("release_digest_mismatch")
    if _git(root, "status", "--porcelain"):
        raise StagingWorkerError("release_worktree_not_clean")
    if any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in sys.modules
        for prefix in ("framework", "infrastructure", "interfaces", "business")
    ):
        raise StagingWorkerError("release_modules_loaded_before_bootstrap")
    sys.path.insert(0, str(root))
    _release_observation(root)
    return root


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise StagingWorkerError("release_git_command_failed")
    return completed.stdout.strip()


def _release_observation(root: Path) -> dict[str, Any]:
    import importlib

    module_names = (
        "framework.events.canonical",
        "framework.events.runtime.publisher",
        "infrastructure.storage.events.postgres",
        "interfaces.services.event_projection_service",
    )
    modules: dict[str, dict[str, str]] = {}
    for name in module_names:
        module = importlib.import_module(name)
        module_file = Path(module.__file__).resolve(strict=True)
        if not module_file.is_relative_to(root):
            raise StagingWorkerError("release_import_escaped_root")
        modules[name] = {
            "path": module_file.relative_to(root).as_posix(),
            "checksum": _sha256_file(module_file),
        }
    return {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "modules": modules,
    }


def _database_observation(config: Mapping[str, Any]) -> dict[str, str]:
    import psycopg

    dsn = _staging_dsn()
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, "
                "current_setting('server_version')"
            )
            row = cursor.fetchone()
    if row is None:
        raise StagingWorkerError("database_observation_missing")
    database_name = str(row[0])
    if database_name != config["database_name"]:
        raise StagingWorkerError("database_name_mismatch")
    if not database_name.startswith("newsroom_rollback_staging_"):
        raise StagingWorkerError("database_name_not_isolated")
    return {
        "database_name": database_name,
        "database_user": str(row[1]),
        "server_version": str(row[2]),
    }


def _store():
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    return PostgresDurableEventStore(_staging_dsn())


def _catalog():
    from framework.events.schema import (
        EventSchemaRegistration,
        FieldDisposition,
        SensitivityPolicy,
        default_event_schema_catalog,
    )

    catalog = default_event_schema_catalog()
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1},
            "ordinal": {"type": "integer", "minimum": 1},
            "private_note": {"type": "string"},
            "blocked_value": {"type": "string"},
        },
        "required": ["message", "ordinal"],
        "additionalProperties": False,
    }
    policy = SensitivityPolicy(
        field_rules={
            "/private_note": FieldDisposition.SENSITIVE,
            "/blocked_value": FieldDisposition.FORBIDDEN,
        },
        redact_sensitive=True,
    )
    for event_type in (EFFECT_EVENT_TYPE, DLQ_EVENT_TYPE, CONTINUITY_EVENT_TYPE):
        catalog.register(
            EventSchemaRegistration(
                event_type=event_type,
                data_schema=DATA_SCHEMA,
                json_schema=schema,
                sensitivity_policy=policy,
                current=True,
                authoritative_context_fields=("run_id",),
            )
        )
    return catalog


def _preserved_subscription(config: Mapping[str, Any]):
    from framework.events.runtime import (
        ConsumerEffectContract,
        DeliveryLimits,
        DurableSubscription,
        EffectIdempotencyStrategy,
        LeasePolicy,
        SubscriptionFilter,
    )

    return DurableSubscription(
        subscription_id=PRESERVED_SUBSCRIPTION_ID,
        subscription_version=1,
        consumer_id=PRESERVED_CONSUMER_ID,
        event_filter=SubscriptionFilter(event_types=frozenset({DLQ_EVENT_TYPE})),
        effect=ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id=PRESERVED_EFFECT_ID,
            idempotency_strategy=EffectIdempotencyStrategy.INBOX_TRANSACTION,
        ),
        lease_policy=LeasePolicy(duration_seconds=LEASE_SECONDS),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=max(10, int(config["event_count"]) + 2),
        ),
        tenant_id=str(config["tenant_id"]),
    )


def _effect_subscription(config: Mapping[str, Any]):
    from framework.events.runtime import (
        ConsumerEffectContract,
        DeliveryLimits,
        DurableSubscription,
        EffectIdempotencyStrategy,
        LeasePolicy,
        RetryPolicy,
        SubscriptionFilter,
    )

    return DurableSubscription(
        subscription_id=EFFECT_SUBSCRIPTION_ID,
        subscription_version=1,
        consumer_id=EFFECT_CONSUMER_ID,
        event_filter=SubscriptionFilter(event_types=frozenset({EFFECT_EVENT_TYPE})),
        effect=ConsumerEffectContract(
            performs_external_effects=True,
            consumer_effect_id=EFFECT_ID,
            idempotency_strategy=EffectIdempotencyStrategy.TARGET_IDEMPOTENCY_KEY,
        ),
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=1,
            multiplier=1,
            max_delay_seconds=1,
            jitter_ratio=0,
        ),
        lease_policy=LeasePolicy(duration_seconds=LEASE_SECONDS),
        limits=DeliveryLimits(
            batch_size=1,
            max_in_flight=1,
            max_concurrency=1,
            pending_warning_threshold=2,
            pending_hard_limit=10,
        ),
        tenant_id=str(config["tenant_id"]),
    )


def _publish_request(
    config: Mapping[str, Any],
    *,
    event_id: str,
    event_type: str,
    ordinal: int,
    stream_id: str | None = None,
    message: str | None = None,
    data_schema: str = DATA_SCHEMA,
    blocked_value: str | None = None,
):
    from framework.events.canonical import BusinessContext, ProducerIdentity
    from framework.events.runtime.publisher import EventPublishRequest

    payload: dict[str, Any] = {
        "message": message or f"rollback-staging-event-{ordinal}",
        "ordinal": ordinal,
    }
    if ordinal == 1:
        payload["private_note"] = f"rollback-private-{config['drill_id']}"
    if blocked_value is not None:
        payload["blocked_value"] = blocked_value
    return EventPublishRequest(
        event_id=event_id,
        event_type=event_type,
        data_schema=data_schema,
        source="scripts.durable_event_rollback_stage_worker",
        occurred_at=_parse_utc(config["occurred_at_base"], "occurred_at_base")
        + timedelta(seconds=ordinal),
        stream_id=stream_id or str(config["stream_id"]),
        business_context=BusinessContext(run_id=str(config["run_id"])),
        producer=ProducerIdentity(
            component="durable-event-rollback-stage-worker",
            version="1",
        ),
        tenant_id=str(config["tenant_id"]),
        payload=payload,
    )


def _main_event_id(config: Mapping[str, Any], ordinal: int) -> str:
    return f"{config['drill_id']}:main:{ordinal:04d}"


def _effect_event_id(config: Mapping[str, Any]) -> str:
    return f"{config['drill_id']}:effect:0001"


def _effect_stream_id(config: Mapping[str, Any]) -> str:
    return f"{config['stream_id']}:effect"


def _initialize(config: Mapping[str, Any]) -> dict[str, Any]:
    from framework.events.runtime import (
        CheckpointKey,
        DeliveryClaimRequest,
        DeliverySettlement,
        DeliveryState,
        InboxEntry,
    )
    from framework.events.runtime.publisher import EventRuntime
    from infrastructure.storage.postgres.repository import PostgresRepository

    PostgresRepository(_staging_dsn()).migrate()
    database = _database_observation(config)
    store = _store()
    try:
        preserved = store.register_subscription(_preserved_subscription(config))
        effect = store.register_subscription(_effect_subscription(config))
        runtime = EventRuntime(store=store, schema_catalog=_catalog())
        first = runtime.publish(
            _publish_request(
                config,
                event_id=_main_event_id(config, 1),
                event_type=DLQ_EVENT_TYPE,
                ordinal=1,
            )
        )
        second = runtime.publish(
            _publish_request(
                config,
                event_id=_main_event_id(config, 2),
                event_type=DLQ_EVENT_TYPE,
                ordinal=2,
            )
        )
        claimed_first = store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=preserved.subscription_id,
                subscription_version=preserved.subscription_version,
                lease_owner="candidate-preserved-ack",
                requested_at=datetime.now(UTC),
                limit=1,
            )
        )
        if len(claimed_first) != 1:
            raise StagingWorkerError("preserved_first_claim_missing")
        first_claim = claimed_first[0]
        first_result = store.settle_delivery(
            DeliverySettlement(
                lease=first_claim.lease,
                target_state=DeliveryState.ACKED,
                settled_at=datetime.now(UTC),
                inbox_entry=InboxEntry(
                    event_id=first.event_id,
                    consumer_effect_id=PRESERVED_EFFECT_ID,
                    completed_at=datetime.now(UTC),
                    delivery_id=first_claim.delivery.delivery_id,
                    result_checksum=_checksum(
                        {"event_id": first.event_id, "result": "preserved"}
                    ),
                ),
            )
        )
        claimed_second = store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=preserved.subscription_id,
                subscription_version=preserved.subscription_version,
                lease_owner="candidate-preserved-dead-letter",
                requested_at=datetime.now(UTC),
                limit=1,
            )
        )
        if len(claimed_second) != 1:
            raise StagingWorkerError("preserved_second_claim_missing")
        second_result = store.settle_delivery(
            DeliverySettlement(
                lease=claimed_second[0].lease,
                target_state=DeliveryState.DEAD_LETTER,
                settled_at=datetime.now(UTC),
                reason_class="rollback_staging_permanent",
                redacted_diagnostic="bounded staging dead-letter seed",
            )
        )

        def append(ordinal: int) -> int:
            event = runtime.publish(
                _publish_request(
                    config,
                    event_id=_main_event_id(config, ordinal),
                    event_type=CONTINUITY_EVENT_TYPE,
                    ordinal=ordinal,
                )
            )
            return event.stream_sequence

        ordinals = range(3, int(config["event_count"]) + 1)
        with ThreadPoolExecutor(max_workers=min(8, int(config["event_count"]))) as pool:
            concurrent_sequences = list(pool.map(append, ordinals))
        effect_event = runtime.publish(
            _publish_request(
                config,
                event_id=_effect_event_id(config),
                event_type=EFFECT_EVENT_TYPE,
                ordinal=1,
                stream_id=_effect_stream_id(config),
                message="external-effect-crash-probe",
            )
        )
        checkpoint = store.get_checkpoint(
            CheckpointKey(
                subscription_id=preserved.subscription_id,
                subscription_version=preserved.subscription_version,
                stream_id=str(config["stream_id"]),
                tenant_id=str(config["tenant_id"]),
            )
        )
        if checkpoint is None:
            raise StagingWorkerError("preserved_checkpoint_missing")
        return {
            "database": database,
            "main_sequences": [
                first.stream_sequence,
                second.stream_sequence,
                *sorted(concurrent_sequences),
            ],
            "concurrent_sequences": sorted(concurrent_sequences),
            "preserved_checkpoint_sequence": (
                checkpoint.highest_contiguous_terminal_sequence
            ),
            "preserved_dead_letter_id": second_result.dead_letter_id,
            "preserved_inbox_recorded_count": int(first_result.inbox_recorded),
            "effect_event_id": effect_event.event_id,
            "effect_content_checksum": effect_event.content_checksum,
            "effect_sequence": effect_event.stream_sequence,
            "effect_subscription_status": effect.status.value,
        }
    finally:
        _close_store(store)


class _AllowProjectionAuthorizer:
    def authorize(self, request):
        from interfaces.services.event_reader_service import (
            EventAuthorizationDecision,
        )

        return EventAuthorizationDecision(
            request=request,
            authorized=True,
            authorization_evidence_ref="authz://rollback-staging/projection",
        )


def _project(config: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    from interfaces.services.event_projection_service import EventProjectionService
    from interfaces.services.event_reader_service import EventAuthorizationContext

    root = Path(str(config[f"{role}_projection_root"]))
    if root.exists():
        raise StagingWorkerError("projection_root_exists")
    store = _store()
    try:
        result = EventProjectionService(
            reader=store,
            authorizer=_AllowProjectionAuthorizer(),
            artifact_root=root,
            schema_catalog=_catalog(),
        ).rebuild_run_projection(
            str(config["run_id"]),
            requested_high_watermark=int(config["event_count"]),
            authorization=EventAuthorizationContext(
                principal_id=f"rollback-staging-{role}",
                tenant_id=str(config["tenant_id"]),
                authentication_evidence_ref=(
                    f"authn://rollback-staging/{role}"
                ),
            ),
        )
        if result.projection is None:
            raise StagingWorkerError("projection_rebuild_unavailable")
        workspace = Path(str(config["workspace"]))
        path = result.path.resolve(strict=True)
        if not path.is_relative_to(workspace):
            raise StagingWorkerError("projection_path_outside_workspace")
        return {
            "role": role,
            "path": path.relative_to(workspace).as_posix(),
            "projection_checksum": result.projection.checksum,
            "event_count": result.projection.event_count,
            "high_watermark": result.projection.high_watermark,
        }
    finally:
        _close_store(store)


class _TargetIdempotencyValidator:
    def validate(self, subscription):
        from framework.events.runtime import (
            AutomaticDeliveryOperation,
            EffectIdempotencyCapability,
            EffectIdempotencyStrategy,
            subscription_definition_fingerprint,
        )

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
            validator_id="rollback-staging-effect-ledger/v1",
            validated_at=datetime.now(UTC),
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


class _EffectConsumer:
    consumer_id = EFFECT_CONSUMER_ID

    def __init__(self, ledger: _ExternalEffectLedger, *, crash: bool) -> None:
        self._ledger = ledger
        self._crash = crash

    def consume(self, event, context):
        from framework.events.runtime import effect_idempotency_key
        from framework.events.subscriber import ConsumerOutcome

        expected_key = effect_idempotency_key(event.event_id, EFFECT_ID)
        if context.consumer_effect_id != EFFECT_ID:
            raise StagingWorkerError("effect_consumer_identity_changed")
        if context.idempotency_key != expected_key:
            raise StagingWorkerError("effect_idempotency_key_changed")
        self._ledger.apply(
            event_id=event.event_id,
            content_checksum=event.content_checksum,
            idempotency_key=expected_key,
        )
        if self._crash:
            os._exit(CRASH_EXIT_CODE)
        return ConsumerOutcome.ack("effect_idempotently_applied")


def _delivery_runtime(config: Mapping[str, Any], store: Any, *, crash: bool):
    from framework.events.runtime import (
        DurableDeliveryRuntime,
        IdempotencyCapabilityRegistry,
    )

    runtime = DurableDeliveryRuntime(
        store,
        idempotency_capabilities=IdempotencyCapabilityRegistry(
            _TargetIdempotencyValidator()
        ),
    )
    subscription = _effect_subscription(config)
    runtime.consumers.attach(
        subscription.key,
        _EffectConsumer(
            _ExternalEffectLedger(Path(str(config["effect_database"]))),
            crash=crash,
        ),
    )
    return runtime, subscription


def _crash_effect(config: Mapping[str, Any]) -> dict[str, Any]:
    store = _store()
    runtime, subscription = _delivery_runtime(config, store, crash=True)
    runtime.dispatch_batch(
        subscription.key,
        lease_owner=f"candidate-crash-{os.getpid()}",
        limit=1,
        stream_id=_effect_stream_id(config),
    )
    raise StagingWorkerError("effect_consumer_did_not_crash")


def _pause_effect(config: Mapping[str, Any]) -> dict[str, Any]:
    from framework.events.runtime import (
        DeliveryClaimRequest,
        DeliveryQuery,
        SubscriptionStatus,
    )

    store = _store()
    subscription = _effect_subscription(config)
    try:
        before = store.get_subscription(subscription.key)
        if before is None:
            raise StagingWorkerError("effect_subscription_missing")
        paused = store.set_subscription_status(
            subscription.key,
            SubscriptionStatus.PAUSED,
            changed_at=datetime.now(UTC),
            reason="rollback staging traffic freeze",
        )
        claimed = store.claim_deliveries(
            DeliveryClaimRequest(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                lease_owner=f"pause-probe-{os.getpid()}",
                requested_at=datetime.now(UTC) + timedelta(days=1),
                limit=1,
            )
        )
        deliveries = store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                stream_id=_effect_stream_id(config),
                tenant_id=str(config["tenant_id"]),
                limit=10,
            )
        ).records
        return {
            "status_before": before.status.value,
            "status_after": paused.status.value,
            "pause_probe_claimed_count": len(claimed),
            "delivery_states": [item.state.value for item in deliveries],
            "lease_generations": [item.lease_generation for item in deliveries],
        }
    finally:
        _close_store(store)


def _recover_effect(config: Mapping[str, Any]) -> dict[str, Any]:
    from framework.events.runtime import CheckpointKey, DeliveryQuery, SubscriptionStatus
    from framework.events.runtime.publisher import EventRuntime

    store = _store()
    runtime, subscription = _delivery_runtime(config, store, crash=False)
    try:
        observed = store.get_subscription(subscription.key)
        if observed is None:
            raise StagingWorkerError("effect_subscription_missing")
        store.set_subscription_status(
            subscription.key,
            SubscriptionStatus.ACTIVE,
            changed_at=datetime.now(UTC),
            reason="compatible rollback dispatcher attached",
        )
        recovered = runtime.dispatch_batch(
            subscription.key,
            lease_owner=f"rollback-recovery-{os.getpid()}",
            limit=1,
            stream_id=_effect_stream_id(config),
        )
        duplicate = EventRuntime(store=store, schema_catalog=_catalog()).publish(
            _publish_request(
                config,
                event_id=_effect_event_id(config),
                event_type=EFFECT_EVENT_TYPE,
                ordinal=1,
                stream_id=_effect_stream_id(config),
                message="external-effect-crash-probe",
            )
        )
        no_rebroadcast = runtime.dispatch_batch(
            subscription.key,
            lease_owner=f"rollback-duplicate-{os.getpid()}",
            limit=1,
            stream_id=_effect_stream_id(config),
        )
        deliveries = store.list_deliveries(
            DeliveryQuery(
                subscription_id=subscription.subscription_id,
                stream_id=_effect_stream_id(config),
                tenant_id=str(config["tenant_id"]),
                limit=10,
            )
        ).records
        checkpoint = store.get_checkpoint(
            CheckpointKey(
                subscription_id=subscription.subscription_id,
                subscription_version=subscription.subscription_version,
                stream_id=_effect_stream_id(config),
                tenant_id=str(config["tenant_id"]),
            )
        )
        return {
            "observed_status": observed.status.value,
            "recovered_claimed_count": recovered.claimed_count,
            "recovered_acknowledged_count": recovered.acknowledged_count,
            "duplicate_claimed_count": no_rebroadcast.claimed_count,
            "duplicate_event_sequence": duplicate.stream_sequence,
            "delivery_states": [item.state.value for item in deliveries],
            "attempt_counts": [item.attempt_count for item in deliveries],
            "checkpoint_sequence": (
                None
                if checkpoint is None
                else checkpoint.highest_contiguous_terminal_sequence
            ),
            "effect_ledger": _ExternalEffectLedger(
                Path(str(config["effect_database"]))
            ).snapshot(),
        }
    finally:
        _close_store(store)


def _negative_gates(config: Mapping[str, Any]) -> dict[str, Any]:
    import psycopg

    from framework.events.errors import (
        EventIdentityCollisionError,
        EventSecurityError,
        EventStoreCorruptionError,
        EventUnknownSchemaError,
    )
    from framework.events.runtime.publisher import EventRuntime

    store = _store()
    runtime = EventRuntime(store=store, schema_catalog=_catalog())
    before = store.get_stream_high_watermark(
        str(config["stream_id"]),
        tenant_id=str(config["tenant_id"]),
    )
    if before != int(config["event_count"]):
        raise StagingWorkerError("negative_gate_initial_watermark_invalid")
    errors: dict[str, str] = {}
    cases = (
        (
            "unknown_schema",
            _publish_request(
                config,
                event_id=f"{config['drill_id']}:negative:unknown",
                event_type=CONTINUITY_EVENT_TYPE,
                ordinal=int(config["event_count"]) + 1,
                data_schema="io.newsroom.event.rollback.staging/v999",
            ),
            EventUnknownSchemaError,
        ),
        (
            "forbidden_payload",
            _publish_request(
                config,
                event_id=f"{config['drill_id']}:negative:forbidden",
                event_type=CONTINUITY_EVENT_TYPE,
                ordinal=int(config["event_count"]) + 1,
                blocked_value="must-never-persist",
            ),
            EventSecurityError,
        ),
        (
            "identity_collision",
            _publish_request(
                config,
                event_id=_main_event_id(config, 1),
                event_type=DLQ_EVENT_TYPE,
                ordinal=1,
                message="identity-collision-after-rollback",
            ),
            EventIdentityCollisionError,
        ),
    )
    try:
        for name, request, expected in cases:
            try:
                runtime.publish(request)
            except expected as error:
                errors[name] = type(error).__name__
            else:
                raise StagingWorkerError(f"negative_case_accepted:{name}")

        original_checksum: str | None = None
        event_id = _main_event_id(config, 1)
        try:
            with psycopg.connect(_staging_dsn()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT record_checksum FROM durable_events "
                        "WHERE event_id = %s AND tenant_scope = %s",
                        (event_id, str(config["tenant_id"])),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise StagingWorkerError("tamper_target_missing")
                    original_checksum = str(row[0])
                    cursor.execute(
                        "UPDATE durable_events SET record_checksum = %s "
                        "WHERE event_id = %s AND tenant_scope = %s",
                        ("sha256:" + "0" * 64, event_id, str(config["tenant_id"])),
                    )
                connection.commit()
            try:
                store.get_event(event_id, tenant_id=str(config["tenant_id"]))
            except EventStoreCorruptionError as error:
                errors["record_checksum_tamper"] = type(error).__name__
            else:
                raise StagingWorkerError("negative_case_accepted:record_checksum_tamper")
        finally:
            if original_checksum is not None:
                with psycopg.connect(_staging_dsn()) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE durable_events SET record_checksum = %s "
                            "WHERE event_id = %s AND tenant_scope = %s",
                            (
                                original_checksum,
                                event_id,
                                str(config["tenant_id"]),
                            ),
                        )
                    connection.commit()
        restored = store.get_event(event_id, tenant_id=str(config["tenant_id"]))
        if restored is None or restored.record_checksum != original_checksum:
            raise StagingWorkerError("tamper_target_not_restored")
        after_rejections = store.get_stream_high_watermark(
            str(config["stream_id"]),
            tenant_id=str(config["tenant_id"]),
        )
        next_event = runtime.publish(
            _publish_request(
                config,
                event_id=_main_event_id(config, int(config["event_count"]) + 1),
                event_type=CONTINUITY_EVENT_TYPE,
                ordinal=int(config["event_count"]) + 1,
                message="accepted-after-compatible-rollback",
            ),
            expected_last_sequence=int(config["event_count"]),
        )
        return {
            "watermark_before": before,
            "watermark_after_rejections": after_rejections,
            "next_event_id": next_event.event_id,
            "next_event_sequence": next_event.stream_sequence,
            "errors": errors,
        }
    finally:
        _close_store(store)


def _close_store(store: Any) -> None:
    close = getattr(store, "close", None)
    if callable(close):
        close()


def _staging_dsn() -> str:
    value = os.environ.get(STAGING_DSN_ENV)
    if not isinstance(value, str) or not value.strip():
        raise StagingWorkerError("staging_dsn_missing")
    return value.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _checksum(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StagingWorkerError(f"{field_name}_invalid")
    return value.strip()


def _parse_utc(value: Any, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StagingWorkerError(f"{field_name}_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StagingWorkerError(f"{field_name}_invalid")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StagingWorkerError("config_duplicate_field")
        result[key] = value
    return result


def _require_path_without_reparse(path: Path, *, must_exist: bool) -> None:
    absolute = path.absolute()
    if must_exist and not absolute.exists():
        raise StagingWorkerError("path_missing")
    current = absolute if absolute.exists() else absolute.parent
    while True:
        if current.is_symlink():
            raise StagingWorkerError("path_reparse_point")
        try:
            attributes = current.stat().st_file_attributes
        except AttributeError:
            attributes = 0
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise StagingWorkerError("path_reparse_point")
        if current.parent == current:
            break
        current = current.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/durable_event_rollback_stage_worker.py"
    )
    parser.add_argument(
        "command",
        choices=(
            "initialize",
            "project-candidate",
            "crash-effect",
            "pause-effect",
            "recover-effect",
            "project-rollback",
            "negative-gates",
        ),
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--release-root", required=True)
    parser.add_argument("--expected-release", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    started_at = datetime.now(UTC)
    try:
        root = _bootstrap_release(args.release_root, args.expected_release)
        config = _load_config(args.config)
        commands = {
            "initialize": _initialize,
            "project-candidate": lambda value: _project(value, role="candidate"),
            "crash-effect": _crash_effect,
            "pause-effect": _pause_effect,
            "recover-effect": _recover_effect,
            "project-rollback": lambda value: _project(value, role="rollback"),
            "negative-gates": _negative_gates,
        }
        facts = commands[args.command](config)
        result = {
            "schema": WORKER_SCHEMA,
            "command": args.command,
            "release_digest": args.expected_release,
            "process_id": os.getpid(),
            "started_at": _utc_text(started_at),
            "completed_at": _utc_text(datetime.now(UTC)),
            "release": _release_observation(root),
            "facts": facts,
        }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as error:
        reason = (
            str(error)
            if isinstance(error, StagingWorkerError)
            else "worker_command_failed"
        )
        print(
            json.dumps(
                {
                    "schema": WORKER_SCHEMA,
                    "command": args.command,
                    "error_type": type(error).__name__,
                    "reason_class": reason,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
