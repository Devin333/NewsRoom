from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, Self, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
    ArtifactCatalogGcAction,
    ArtifactCatalogGcDecision,
    ArtifactCatalogGcDetachReceipt,
    ArtifactCatalogGcPlan,
    ArtifactLogicalReference,
)
from framework.harness.runtime.result_canonical import (
    aware_datetime,
    boolean,
    checksum,
    datetime_from_json,
    datetime_to_json,
    enum_value,
    exact_keys,
    exact_reference,
    identifier,
    non_negative_int,
    optional_text,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    ArtifactRecord,
    RetentionClass,
)


class GraphArtifactUsageKind(StrEnum):
    MATERIALIZATION = "materialization"
    CACHE_LOOKUP = "cache_lookup"
    CACHE_WRITE = "cache_write"
    CACHE_READBACK = "cache_readback"
    CONTEXT_LOAD = "context_load"
    ARTIFACT_READBACK = "artifact_readback"
    CATALOG_DRIFT = "catalog_drift"
    GC_TRANSITION = "gc_transition"


class GraphArtifactUsageOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    OMITTED = "omitted"
    HIT = "hit"
    MISS = "miss"
    PROTECTED = "protected"
    STALE = "stale"


class GraphArtifactUsageReason(StrEnum):
    INLINE_RESULT = "inline_result"
    MATERIALIZED_RESULT = "materialized_result"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    CACHE_WRITE = "cache_write"
    CACHE_READBACK = "cache_readback"
    CONTEXT_LOADED = "context_loaded"
    RESULT_OMITTED = "result_omitted"
    RECOVERED = "recovered"
    CATALOG_DRIFT = "catalog_drift"
    GC_PREPARED = "gc_prepared"
    GC_CATALOG_DETACHED = "gc_catalog_detached"
    GC_QUARANTINED = "gc_quarantined"
    GC_PURGED = "gc_purged"
    GC_COMPLETED = "gc_completed"
    GC_STALE = "gc_stale"


class GraphArtifactQuotaScope(StrEnum):
    TENANT = "tenant"
    RUN = "run"
    ARTIFACT_CLASS = "artifact_class"


class GraphArtifactGcOperationState(StrEnum):
    PREPARED = "prepared"
    CATALOG_DETACHED = "catalog_detached"
    QUARANTINED = "quarantined"
    PURGED = "purged"
    COMPLETED = "completed"
    STALE = "stale"
    RETRYABLE_FAILURE = "retryable_failure"


class GraphArtifactAlertKind(StrEnum):
    RUN_QUOTA_PRESSURE = "run_quota_pressure"
    TENANT_QUOTA_PRESSURE = "tenant_quota_pressure"
    GC_BACKLOG = "gc_backlog"
    READBACK_FAILURE = "readback_failure"
    CATALOG_DRIFT = "catalog_drift"
    CACHE_STAMPEDE = "cache_stampede"


class GraphArtifactAlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"


class GraphArtifactAlertReason(StrEnum):
    QUOTA_WARNING_THRESHOLD = "quota_warning_threshold"
    GC_BACKLOG_THRESHOLD = "gc_backlog_threshold"
    READBACK_FAILURE = "readback_failure"
    CATALOG_DRIFT = "catalog_drift"
    CACHE_STAMPEDE = "cache_stampede"


@dataclass(frozen=True, slots=True)
class GraphArtifactUsageFact:
    fact_id: str
    kind: GraphArtifactUsageKind
    outcome: GraphArtifactUsageOutcome
    tenant_id: str
    run_id: str | None
    graph_id: str | None
    node_id: str | None
    artifact_class: ArtifactClass | None
    retention_class: RetentionClass | None
    policy_version: str
    operation_id: str
    logical_bytes: int
    physical_bytes: int
    loaded_bytes: int
    loaded_tokens: int
    object_count: int
    reason_code: str | None
    occurred_at: datetime
    fact_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", enum_value(GraphArtifactUsageKind, self.kind, "usage.kind"))
        object.__setattr__(
            self,
            "outcome",
            enum_value(GraphArtifactUsageOutcome, self.outcome, "usage.outcome"),
        )
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "usage.tenant_id"))
        for name in ("run_id", "graph_id", "node_id"):
            object.__setattr__(
                self,
                name,
                _optional_identifier(getattr(self, name), f"usage.{name}"),
            )
        object.__setattr__(
            self,
            "artifact_class",
            _optional_enum(ArtifactClass, self.artifact_class, "usage.artifact_class"),
        )
        object.__setattr__(
            self,
            "retention_class",
            _optional_enum(RetentionClass, self.retention_class, "usage.retention_class"),
        )
        object.__setattr__(
            self,
            "policy_version",
            exact_reference(self.policy_version, "usage.policy_version"),
        )
        object.__setattr__(
            self,
            "operation_id",
            reference(self.operation_id, "usage.operation_id"),
        )
        for name in (
            "logical_bytes",
            "physical_bytes",
            "loaded_bytes",
            "loaded_tokens",
            "object_count",
        ):
            object.__setattr__(
                self,
                name,
                non_negative_int(getattr(self, name), f"usage.{name}"),
            )
        object.__setattr__(self, "reason_code", _controlled_reason_code(self.reason_code))
        object.__setattr__(self, "occurred_at", aware_datetime(self.occurred_at, "usage.occurred_at"))
        expected_id = _derived_ref("graph-artifact-usage", self.identity_projection())
        if reference(self.fact_id, "usage.fact_id") != expected_id:
            raise _identity_error("usage.fact_id")
        expected_checksum = checksum_for(self.checksum_projection())
        if checksum(self.fact_checksum, "usage.fact_checksum") != expected_checksum:
            raise _identity_error("usage.fact_checksum")
        object.__setattr__(self, "fact_id", expected_id)
        object.__setattr__(self, "fact_checksum", expected_checksum)

    @classmethod
    def create(
        cls,
        *,
        kind: GraphArtifactUsageKind,
        outcome: GraphArtifactUsageOutcome,
        tenant_id: str,
        policy_version: str,
        operation_id: str,
        occurred_at: datetime,
        run_id: str | None = None,
        graph_id: str | None = None,
        node_id: str | None = None,
        artifact_class: ArtifactClass | None = None,
        retention_class: RetentionClass | None = None,
        logical_bytes: int = 0,
        physical_bytes: int = 0,
        loaded_bytes: int = 0,
        loaded_tokens: int = 0,
        object_count: int = 0,
        reason_code: str | None = None,
    ) -> Self:
        normalized_kind = enum_value(GraphArtifactUsageKind, kind, "usage.kind")
        normalized_outcome = enum_value(GraphArtifactUsageOutcome, outcome, "usage.outcome")
        normalized_tenant = identifier(tenant_id, "usage.tenant_id")
        normalized_operation = reference(operation_id, "usage.operation_id")
        identity = {
            "kind": normalized_kind.value,
            "tenant_id": normalized_tenant,
            "operation_id": normalized_operation,
        }
        fact_id = _derived_ref("graph-artifact-usage", identity)
        values = {
            "fact_id": fact_id,
            "kind": normalized_kind,
            "outcome": normalized_outcome,
            "tenant_id": normalized_tenant,
            "run_id": run_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "artifact_class": artifact_class,
            "retention_class": retention_class,
            "policy_version": policy_version,
            "operation_id": normalized_operation,
            "logical_bytes": logical_bytes,
            "physical_bytes": physical_bytes,
            "loaded_bytes": loaded_bytes,
            "loaded_tokens": loaded_tokens,
            "object_count": object_count,
            "reason_code": reason_code,
            "occurred_at": occurred_at,
        }
        return cls(
            **values,
            fact_checksum=checksum_for(_usage_projection(values)),
        )

    def identity_projection(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "tenant_id": self.tenant_id,
            "operation_id": self.operation_id,
        }

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "kind": _enum_text(self.kind),
            "outcome": _enum_text(self.outcome),
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "artifact_class": _optional_enum_text(self.artifact_class),
            "retention_class": _optional_enum_text(self.retention_class),
            "policy_version": self.policy_version,
            "operation_id": self.operation_id,
            "logical_bytes": self.logical_bytes,
            "physical_bytes": self.physical_bytes,
            "loaded_bytes": self.loaded_bytes,
            "loaded_tokens": self.loaded_tokens,
            "object_count": self.object_count,
            "reason_code": self.reason_code,
            "occurred_at": datetime_to_json(self.occurred_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "fact_checksum": self.fact_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "fact_id",
                        "kind",
                        "outcome",
                        "tenant_id",
                        "run_id",
                        "graph_id",
                        "node_id",
                        "artifact_class",
                        "retention_class",
                        "policy_version",
                        "operation_id",
                        "logical_bytes",
                        "physical_bytes",
                        "loaded_bytes",
                        "loaded_tokens",
                        "object_count",
                        "reason_code",
                        "occurred_at",
                        "fact_checksum",
                    }
                ),
                model=cls.__name__,
            )
            | {
                "occurred_at": datetime_from_json(value["occurred_at"], "usage.occurred_at")
            }
        )


@dataclass(frozen=True, slots=True)
class GraphArtifactQuotaSnapshot:
    scope: GraphArtifactQuotaScope
    tenant_id: str
    run_id: str | None
    artifact_class: ArtifactClass | None
    charged_bytes: int
    charged_objects: int
    pending_bytes: int
    pending_objects: int
    limit_bytes: int
    limit_objects: int
    captured_at: datetime
    snapshot_checksum: str

    def __post_init__(self) -> None:
        scope = enum_value(GraphArtifactQuotaScope, self.scope, "quota_snapshot.scope")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "quota_snapshot.tenant_id"))
        object.__setattr__(
            self,
            "run_id",
            _optional_identifier(self.run_id, "quota_snapshot.run_id"),
        )
        object.__setattr__(
            self,
            "artifact_class",
            _optional_enum(ArtifactClass, self.artifact_class, "quota_snapshot.artifact_class"),
        )
        if (
            (scope is GraphArtifactQuotaScope.TENANT and (self.run_id is not None or self.artifact_class is not None))
            or (scope is GraphArtifactQuotaScope.RUN and (self.run_id is None or self.artifact_class is not None))
            or (scope is GraphArtifactQuotaScope.ARTIFACT_CLASS and (self.run_id is not None or self.artifact_class is None))
        ):
            raise _schema_error("quota_snapshot.dimension")
        for name in (
            "charged_bytes",
            "charged_objects",
            "pending_bytes",
            "pending_objects",
            "limit_bytes",
            "limit_objects",
        ):
            object.__setattr__(
                self,
                name,
                non_negative_int(getattr(self, name), f"quota_snapshot.{name}"),
            )
        if self.limit_bytes == 0 or self.limit_objects == 0:
            raise _schema_error("quota_snapshot.limit")
        object.__setattr__(self, "captured_at", aware_datetime(self.captured_at, "quota_snapshot.captured_at"))
        expected = checksum_for(self.checksum_projection())
        if checksum(self.snapshot_checksum, "quota_snapshot.snapshot_checksum") != expected:
            raise _identity_error("quota_snapshot.snapshot_checksum")
        object.__setattr__(self, "snapshot_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, snapshot_checksum=checksum_for(_quota_projection(values)))

    def checksum_projection(self) -> dict[str, Any]:
        return _quota_projection(
            {
                "scope": self.scope,
                "tenant_id": self.tenant_id,
                "run_id": self.run_id,
                "artifact_class": self.artifact_class,
                "charged_bytes": self.charged_bytes,
                "charged_objects": self.charged_objects,
                "pending_bytes": self.pending_bytes,
                "pending_objects": self.pending_objects,
                "limit_bytes": self.limit_bytes,
                "limit_objects": self.limit_objects,
                "captured_at": self.captured_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "snapshot_checksum": self.snapshot_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "scope",
                    "tenant_id",
                    "run_id",
                    "artifact_class",
                    "charged_bytes",
                    "charged_objects",
                    "pending_bytes",
                    "pending_objects",
                    "limit_bytes",
                    "limit_objects",
                    "captured_at",
                    "snapshot_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["captured_at"] = datetime_from_json(payload["captured_at"], "quota_snapshot.captured_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactGcOperationIntent:
    operation_id: str
    tenant_id: str
    plan_checksum: str
    catalog_snapshot_checksum: str
    policy_version: str
    decision: ArtifactCatalogGcDecision
    entry: ArtifactCatalogEntry
    claims: tuple[ArtifactCatalogClaim, ...]
    references: tuple[ArtifactLogicalReference, ...]
    prepared_at: datetime
    intent_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_id",
            identifier(self.tenant_id, "gc_intent.tenant_id"),
        )
        object.__setattr__(
            self,
            "plan_checksum",
            checksum(self.plan_checksum, "gc_intent.plan_checksum"),
        )
        object.__setattr__(
            self,
            "catalog_snapshot_checksum",
            checksum(
                self.catalog_snapshot_checksum,
                "gc_intent.catalog_snapshot_checksum",
            ),
        )
        object.__setattr__(
            self,
            "policy_version",
            exact_reference(self.policy_version, "gc_intent.policy_version"),
        )
        if (
            not isinstance(self.decision, ArtifactCatalogGcDecision)
            or self.decision.action is not ArtifactCatalogGcAction.DELETE_CANDIDATE
            or self.decision.tenant_id != self.tenant_id
        ):
            raise _schema_error("gc_intent.decision")
        if (
            not isinstance(self.entry, ArtifactCatalogEntry)
            or self.entry.entry_id != self.decision.entry_id
            or self.entry.identity.tenant_id != self.tenant_id
            or self.entry.record.ref != self.decision.ref
            or self.entry.record.byte_size != self.decision.byte_size
        ):
            raise _schema_error("gc_intent.entry")
        claims = tuple(
            sorted(
                _typed_tuple(
                    self.claims,
                    ArtifactCatalogClaim,
                    "gc_intent.claims",
                ),
                key=lambda item: item.claim_id,
            )
        )
        references = tuple(
            sorted(
                _typed_tuple(
                    self.references,
                    ArtifactLogicalReference,
                    "gc_intent.references",
                ),
                key=lambda item: item.reference_id,
            )
        )
        if (
            tuple(item.claim_id for item in claims) != self.decision.claim_ids
            or tuple(item.reference_id for item in references)
            != self.decision.reference_ids
            or any(
                item.entry_id != self.entry.entry_id
                or item.tenant_id != self.tenant_id
                for item in (*claims, *references)
            )
        ):
            raise _schema_error("gc_intent.evidence")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "references", references)
        object.__setattr__(
            self,
            "prepared_at",
            aware_datetime(self.prepared_at, "gc_intent.prepared_at"),
        )
        expected_id = _derived_ref(
            "graph-artifact-gc",
            self.identity_projection(),
        )
        if reference(self.operation_id, "gc_intent.operation_id") != expected_id:
            raise _identity_error("gc_intent.operation_id")
        expected_checksum = checksum_for(self.checksum_projection())
        if (
            checksum(self.intent_checksum, "gc_intent.intent_checksum")
            != expected_checksum
        ):
            raise _identity_error("gc_intent.intent_checksum")
        object.__setattr__(self, "operation_id", expected_id)
        object.__setattr__(self, "intent_checksum", expected_checksum)

    @classmethod
    def create(cls, **values: Any) -> Self:
        operation_id = _derived_ref(
            "graph-artifact-gc",
            _gc_intent_identity(values),
        )
        projection = _gc_intent_projection(
            {**values, "operation_id": operation_id}
        )
        return cls(
            **values,
            operation_id=operation_id,
            intent_checksum=checksum_for(projection),
        )

    def identity_projection(self) -> dict[str, Any]:
        return _gc_intent_identity(_dataclass_values(self))

    def checksum_projection(self) -> dict[str, Any]:
        return _gc_intent_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "intent_checksum": self.intent_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "operation_id",
                    "tenant_id",
                    "plan_checksum",
                    "catalog_snapshot_checksum",
                    "policy_version",
                    "decision",
                    "entry",
                    "claims",
                    "references",
                    "prepared_at",
                    "intent_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["decision"] = ArtifactCatalogGcDecision.from_dict(
            payload["decision"]
        )
        payload["entry"] = ArtifactCatalogEntry.from_dict(payload["entry"])
        payload["claims"] = tuple(
            ArtifactCatalogClaim.from_dict(item) for item in payload["claims"]
        )
        payload["references"] = tuple(
            ArtifactLogicalReference.from_dict(item)
            for item in payload["references"]
        )
        payload["prepared_at"] = datetime_from_json(
            payload["prepared_at"],
            "gc_intent.prepared_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactPhysicalDeleteRequest:
    operation_id: str
    plan_checksum: str
    decision_checksum: str
    intent_checksum: str
    record: ArtifactRecord
    detach_receipt: ArtifactCatalogGcDetachReceipt
    requested_at: datetime
    request_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", reference(self.operation_id, "gc_delete.operation_id"))
        object.__setattr__(self, "plan_checksum", checksum(self.plan_checksum, "gc_delete.plan_checksum"))
        object.__setattr__(self, "decision_checksum", checksum(self.decision_checksum, "gc_delete.decision_checksum"))
        object.__setattr__(
            self,
            "intent_checksum",
            checksum(self.intent_checksum, "gc_delete.intent_checksum"),
        )
        if not isinstance(self.record, ArtifactRecord):
            raise _schema_error("gc_delete.record")
        if (
            not isinstance(self.detach_receipt, ArtifactCatalogGcDetachReceipt)
            or self.detach_receipt.entry.record != self.record
        ):
            raise _schema_error("gc_delete.detach_receipt")
        object.__setattr__(self, "requested_at", aware_datetime(self.requested_at, "gc_delete.requested_at"))
        expected = checksum_for(self.checksum_projection())
        if checksum(self.request_checksum, "gc_delete.request_checksum") != expected:
            raise _identity_error("gc_delete.request_checksum")
        object.__setattr__(self, "request_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, request_checksum=checksum_for(_delete_request_projection(values)))

    def checksum_projection(self) -> dict[str, Any]:
        return _delete_request_projection(
            {
                "operation_id": self.operation_id,
                "plan_checksum": self.plan_checksum,
                "decision_checksum": self.decision_checksum,
                "intent_checksum": self.intent_checksum,
                "record": self.record,
                "detach_receipt": self.detach_receipt,
                "requested_at": self.requested_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "request_checksum": self.request_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "operation_id",
                    "plan_checksum",
                    "decision_checksum",
                    "intent_checksum",
                    "record",
                    "detach_receipt",
                    "requested_at",
                    "request_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["record"] = ArtifactRecord.from_dict(payload["record"])
        payload["detach_receipt"] = ArtifactCatalogGcDetachReceipt.from_dict(
            payload["detach_receipt"]
        )
        payload["requested_at"] = datetime_from_json(payload["requested_at"], "gc_delete.requested_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactQuarantineReceipt:
    operation_id: str
    ref: str
    content_checksum: str
    byte_size: int
    quarantined_at: datetime
    receipt_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", reference(self.operation_id, "quarantine.operation_id"))
        object.__setattr__(self, "ref", reference(self.ref, "quarantine.ref"))
        object.__setattr__(self, "content_checksum", checksum(self.content_checksum, "quarantine.content_checksum"))
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "quarantine.byte_size"))
        object.__setattr__(self, "quarantined_at", aware_datetime(self.quarantined_at, "quarantine.quarantined_at"))
        expected = checksum_for(self.checksum_projection())
        if checksum(self.receipt_checksum, "quarantine.receipt_checksum") != expected:
            raise _identity_error("quarantine.receipt_checksum")
        object.__setattr__(self, "receipt_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, receipt_checksum=checksum_for(_quarantine_projection(values)))

    def checksum_projection(self) -> dict[str, Any]:
        return _quarantine_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {"operation_id", "ref", "content_checksum", "byte_size", "quarantined_at", "receipt_checksum"}
            ),
            model=cls.__name__,
        )
        payload["quarantined_at"] = datetime_from_json(payload["quarantined_at"], "quarantine.quarantined_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactDeletionReceipt:
    operation_id: str
    quarantine_receipt_checksum: str
    ref: str
    content_checksum: str
    byte_size: int
    deleted_at: datetime
    receipt_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", reference(self.operation_id, "deletion.operation_id"))
        object.__setattr__(
            self,
            "quarantine_receipt_checksum",
            checksum(self.quarantine_receipt_checksum, "deletion.quarantine_receipt_checksum"),
        )
        object.__setattr__(self, "ref", reference(self.ref, "deletion.ref"))
        object.__setattr__(self, "content_checksum", checksum(self.content_checksum, "deletion.content_checksum"))
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "deletion.byte_size"))
        object.__setattr__(self, "deleted_at", aware_datetime(self.deleted_at, "deletion.deleted_at"))
        expected = checksum_for(self.checksum_projection())
        if checksum(self.receipt_checksum, "deletion.receipt_checksum") != expected:
            raise _identity_error("deletion.receipt_checksum")
        object.__setattr__(self, "receipt_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, receipt_checksum=checksum_for(_deletion_projection(values)))

    def checksum_projection(self) -> dict[str, Any]:
        return _deletion_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "operation_id",
                    "quarantine_receipt_checksum",
                    "ref",
                    "content_checksum",
                    "byte_size",
                    "deleted_at",
                    "receipt_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["deleted_at"] = datetime_from_json(payload["deleted_at"], "deletion.deleted_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactGcOperation:
    operation_id: str
    state: GraphArtifactGcOperationState
    intent: GraphArtifactGcOperationIntent
    request: GraphArtifactPhysicalDeleteRequest | None
    quarantine: GraphArtifactQuarantineReceipt | None
    deletion: GraphArtifactDeletionReceipt | None
    error_code: GraphArtifactResultErrorCode | None
    updated_at: datetime
    operation_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", reference(self.operation_id, "gc_operation.operation_id"))
        state = enum_value(GraphArtifactGcOperationState, self.state, "gc_operation.state")
        object.__setattr__(self, "state", state)
        if (
            not isinstance(self.intent, GraphArtifactGcOperationIntent)
            or self.intent.operation_id != self.operation_id
        ):
            raise _schema_error("gc_operation.intent")
        request = self.request
        if request is not None and (
            not isinstance(request, GraphArtifactPhysicalDeleteRequest)
            or request.operation_id != self.operation_id
            or request.plan_checksum != self.intent.plan_checksum
            or request.decision_checksum != self.intent.decision.decision_checksum
            or request.intent_checksum != self.intent.intent_checksum
            or request.record != self.intent.entry.record
        ):
            raise _schema_error("gc_operation.request")
        if self.quarantine is not None and (
            not isinstance(self.quarantine, GraphArtifactQuarantineReceipt)
            or self.quarantine.operation_id != self.operation_id
            or request is None
            or self.quarantine.ref != request.record.ref
            or self.quarantine.content_checksum != request.record.content_checksum
            or self.quarantine.byte_size != request.record.byte_size
            or self.quarantine.quarantined_at < request.requested_at
        ):
            raise _schema_error("gc_operation.quarantine")
        if self.deletion is not None and (
            not isinstance(self.deletion, GraphArtifactDeletionReceipt)
            or self.deletion.operation_id != self.operation_id
            or self.quarantine is None
            or self.deletion.quarantine_receipt_checksum
            != self.quarantine.receipt_checksum
            or self.deletion.ref != self.quarantine.ref
            or self.deletion.content_checksum != self.quarantine.content_checksum
            or self.deletion.byte_size != self.quarantine.byte_size
            or self.deletion.deleted_at < self.quarantine.quarantined_at
        ):
            raise _schema_error("gc_operation.deletion")
        if state in {
            GraphArtifactGcOperationState.CATALOG_DETACHED,
            GraphArtifactGcOperationState.QUARANTINED,
            GraphArtifactGcOperationState.PURGED,
            GraphArtifactGcOperationState.COMPLETED,
        } and request is None:
            raise _schema_error("gc_operation.request")
        if state in {
            GraphArtifactGcOperationState.PREPARED,
            GraphArtifactGcOperationState.STALE,
        } and any(
            item is not None for item in (request, self.quarantine, self.deletion)
        ):
            raise _schema_error("gc_operation.state")
        if state in {GraphArtifactGcOperationState.QUARANTINED, GraphArtifactGcOperationState.PURGED, GraphArtifactGcOperationState.COMPLETED} and self.quarantine is None:
            raise _schema_error("gc_operation.quarantine")
        if state in {GraphArtifactGcOperationState.PURGED, GraphArtifactGcOperationState.COMPLETED} and self.deletion is None:
            raise _schema_error("gc_operation.deletion")
        error_code = _optional_enum(GraphArtifactResultErrorCode, self.error_code, "gc_operation.error_code")
        if state is GraphArtifactGcOperationState.RETRYABLE_FAILURE and error_code is None:
            raise _schema_error("gc_operation.error_code")
        if state is not GraphArtifactGcOperationState.RETRYABLE_FAILURE and error_code is not None:
            raise _schema_error("gc_operation.error_code")
        object.__setattr__(self, "error_code", error_code)
        updated_at = aware_datetime(self.updated_at, "gc_operation.updated_at")
        latest = self.intent.prepared_at
        if request is not None:
            latest = max(latest, request.requested_at)
        if self.quarantine is not None:
            latest = max(latest, self.quarantine.quarantined_at)
        if self.deletion is not None:
            latest = max(latest, self.deletion.deleted_at)
        if updated_at < latest:
            raise _schema_error("gc_operation.updated_at")
        object.__setattr__(self, "updated_at", updated_at)
        expected = checksum_for(self.checksum_projection())
        if checksum(self.operation_checksum, "gc_operation.operation_checksum") != expected:
            raise _identity_error("gc_operation.operation_checksum")
        object.__setattr__(self, "operation_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        projection = _gc_operation_projection(values)
        return cls(**values, operation_checksum=checksum_for(projection))

    def checksum_projection(self) -> dict[str, Any]:
        return _gc_operation_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "operation_checksum": self.operation_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {"operation_id", "state", "intent", "request", "quarantine", "deletion", "error_code", "updated_at", "operation_checksum"}
            ),
            model=cls.__name__,
        )
        payload["intent"] = GraphArtifactGcOperationIntent.from_dict(payload["intent"])
        payload["request"] = (
            GraphArtifactPhysicalDeleteRequest.from_dict(payload["request"])
            if payload["request"] is not None
            else None
        )
        payload["quarantine"] = (
            GraphArtifactQuarantineReceipt.from_dict(payload["quarantine"])
            if payload["quarantine"] is not None
            else None
        )
        payload["deletion"] = (
            GraphArtifactDeletionReceipt.from_dict(payload["deletion"])
            if payload["deletion"] is not None
            else None
        )
        payload["updated_at"] = datetime_from_json(payload["updated_at"], "gc_operation.updated_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactDeletionTombstone:
    tombstone_id: str
    operation_id: str
    tenant_id: str
    entry_id: str
    ref: str
    content_checksum: str
    byte_size: int
    policy_version: str
    deletion_receipt_checksum: str
    completed_at: datetime
    tombstone_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_id",
            reference(self.operation_id, "gc_tombstone.operation_id"),
        )
        object.__setattr__(
            self,
            "tenant_id",
            identifier(self.tenant_id, "gc_tombstone.tenant_id"),
        )
        object.__setattr__(
            self,
            "entry_id",
            reference(self.entry_id, "gc_tombstone.entry_id"),
        )
        object.__setattr__(self, "ref", reference(self.ref, "gc_tombstone.ref"))
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "gc_tombstone.content_checksum"),
        )
        object.__setattr__(
            self,
            "byte_size",
            non_negative_int(self.byte_size, "gc_tombstone.byte_size"),
        )
        object.__setattr__(
            self,
            "policy_version",
            exact_reference(self.policy_version, "gc_tombstone.policy_version"),
        )
        object.__setattr__(
            self,
            "deletion_receipt_checksum",
            checksum(
                self.deletion_receipt_checksum,
                "gc_tombstone.deletion_receipt_checksum",
            ),
        )
        object.__setattr__(
            self,
            "completed_at",
            aware_datetime(self.completed_at, "gc_tombstone.completed_at"),
        )
        expected_id = _derived_ref(
            "graph-artifact-tombstone",
            {"operation_id": self.operation_id},
        )
        if reference(self.tombstone_id, "gc_tombstone.tombstone_id") != expected_id:
            raise _identity_error("gc_tombstone.tombstone_id")
        expected_checksum = checksum_for(self.checksum_projection())
        if (
            checksum(self.tombstone_checksum, "gc_tombstone.tombstone_checksum")
            != expected_checksum
        ):
            raise _identity_error("gc_tombstone.tombstone_checksum")
        object.__setattr__(self, "tombstone_id", expected_id)
        object.__setattr__(self, "tombstone_checksum", expected_checksum)

    @classmethod
    def from_completed_operation(cls, operation: GraphArtifactGcOperation) -> Self:
        if (
            not isinstance(operation, GraphArtifactGcOperation)
            or operation.state is not GraphArtifactGcOperationState.COMPLETED
            or operation.deletion is None
        ):
            raise _schema_error("gc_tombstone.operation")
        values = {
            "operation_id": operation.operation_id,
            "tenant_id": operation.intent.tenant_id,
            "entry_id": operation.intent.entry.entry_id,
            "ref": operation.intent.entry.record.ref,
            "content_checksum": operation.intent.entry.record.content_checksum,
            "byte_size": operation.intent.entry.record.byte_size,
            "policy_version": operation.intent.policy_version,
            "deletion_receipt_checksum": operation.deletion.receipt_checksum,
            "completed_at": operation.updated_at,
        }
        tombstone_id = _derived_ref(
            "graph-artifact-tombstone",
            {"operation_id": operation.operation_id},
        )
        return cls(
            **values,
            tombstone_id=tombstone_id,
            tombstone_checksum=checksum_for(
                _gc_tombstone_projection(
                    {**values, "tombstone_id": tombstone_id}
                )
            ),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return _gc_tombstone_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "tombstone_checksum": self.tombstone_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "tombstone_id",
                    "operation_id",
                    "tenant_id",
                    "entry_id",
                    "ref",
                    "content_checksum",
                    "byte_size",
                    "policy_version",
                    "deletion_receipt_checksum",
                    "completed_at",
                    "tombstone_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["completed_at"] = datetime_from_json(
            payload["completed_at"],
            "gc_tombstone.completed_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactCostDimension:
    tenant_id: str
    run_id: str | None
    graph_id: str | None
    node_id: str | None
    artifact_class: ArtifactClass | None
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "cost_dimension.tenant_id"))
        for name in ("run_id", "graph_id", "node_id"):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), f"cost_dimension.{name}"))
        if self.graph_id is not None and self.run_id is None:
            raise _schema_error("cost_dimension.graph_id")
        if self.node_id is not None and self.graph_id is None:
            raise _schema_error("cost_dimension.node_id")
        object.__setattr__(
            self,
            "artifact_class",
            _optional_enum(ArtifactClass, self.artifact_class, "cost_dimension.artifact_class"),
        )
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "cost_dimension.policy_version"))

    def sort_key(self) -> tuple[str, ...]:
        return (
            self.tenant_id,
            self.run_id or "",
            self.graph_id or "",
            self.node_id or "",
            _optional_enum_text(self.artifact_class) or "",
            self.policy_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "artifact_class": _optional_enum_text(self.artifact_class),
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset({"tenant_id", "run_id", "graph_id", "node_id", "artifact_class", "policy_version"}),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class GraphArtifactCostAggregate:
    dimension: GraphArtifactCostDimension
    logical_bytes: int
    logical_count: int
    unique_physical_bytes: int
    unique_physical_count: int
    dedup_savings_basis_points: int
    expired_bytes: int
    failed_writes: int
    context_loaded_bytes: int
    context_loaded_tokens: int
    cache_hits: int
    cache_misses: int
    cache_hit_ratio_basis_points: int | None
    gc_purged_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, GraphArtifactCostDimension):
            raise _schema_error("cost_aggregate.dimension")
        for name in (
            "logical_bytes",
            "logical_count",
            "unique_physical_bytes",
            "unique_physical_count",
            "dedup_savings_basis_points",
            "expired_bytes",
            "failed_writes",
            "context_loaded_bytes",
            "context_loaded_tokens",
            "cache_hits",
            "cache_misses",
            "gc_purged_bytes",
        ):
            object.__setattr__(self, name, non_negative_int(getattr(self, name), f"cost_aggregate.{name}"))
        if self.dedup_savings_basis_points > 10_000:
            raise _schema_error("cost_aggregate.dedup_savings_basis_points")
        expected_dedup = (
            0
            if self.logical_bytes == 0
            else max(0, (self.logical_bytes - self.unique_physical_bytes) * 10_000 // self.logical_bytes)
        )
        if self.unique_physical_bytes > self.logical_bytes or self.dedup_savings_basis_points != expected_dedup:
            raise _schema_error("cost_aggregate.dedup")
        cache_total = self.cache_hits + self.cache_misses
        expected_ratio = None if cache_total == 0 else self.cache_hits * 10_000 // cache_total
        if self.cache_hit_ratio_basis_points != expected_ratio:
            raise _schema_error("cost_aggregate.cache_hit_ratio_basis_points")

    @classmethod
    def create(cls, *, dimension: GraphArtifactCostDimension, **values: Any) -> Self:
        logical = int(values.get("logical_bytes", 0))
        unique = int(values.get("unique_physical_bytes", 0))
        hits = int(values.get("cache_hits", 0))
        misses = int(values.get("cache_misses", 0))
        return cls(
            dimension=dimension,
            dedup_savings_basis_points=(0 if logical == 0 else max(0, (logical - unique) * 10_000 // logical)),
            cache_hit_ratio_basis_points=(None if hits + misses == 0 else hits * 10_000 // (hits + misses)),
            **values,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.to_dict(),
            "logical_bytes": self.logical_bytes,
            "logical_count": self.logical_count,
            "unique_physical_bytes": self.unique_physical_bytes,
            "unique_physical_count": self.unique_physical_count,
            "dedup_savings_basis_points": self.dedup_savings_basis_points,
            "expired_bytes": self.expired_bytes,
            "failed_writes": self.failed_writes,
            "context_loaded_bytes": self.context_loaded_bytes,
            "context_loaded_tokens": self.context_loaded_tokens,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_ratio_basis_points": self.cache_hit_ratio_basis_points,
            "gc_purged_bytes": self.gc_purged_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "dimension",
                    "logical_bytes",
                    "logical_count",
                    "unique_physical_bytes",
                    "unique_physical_count",
                    "dedup_savings_basis_points",
                    "expired_bytes",
                    "failed_writes",
                    "context_loaded_bytes",
                    "context_loaded_tokens",
                    "cache_hits",
                    "cache_misses",
                    "cache_hit_ratio_basis_points",
                    "gc_purged_bytes",
                }
            ),
            model=cls.__name__,
        )
        payload["dimension"] = GraphArtifactCostDimension.from_dict(payload["dimension"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class DailyGraphArtifactCostReport:
    report_id: str
    tenant_id: str
    window_start: datetime
    window_end: datetime
    provisional: bool
    policy_version: str
    catalog_snapshot_checksum: str
    usage_watermark: int
    aggregates: tuple[GraphArtifactCostAggregate, ...]
    generated_at: datetime
    report_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "cost_report.tenant_id"))
        start = aware_datetime(self.window_start, "cost_report.window_start")
        end = aware_datetime(self.window_end, "cost_report.window_end")
        if (
            start.utcoffset() != timedelta(0)
            or end.utcoffset() != timedelta(0)
            or any((start.hour, start.minute, start.second, start.microsecond))
            or end - start != timedelta(days=1)
        ):
            raise _schema_error("cost_report.window")
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "provisional", boolean(self.provisional, "cost_report.provisional"))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "cost_report.policy_version"))
        object.__setattr__(
            self,
            "catalog_snapshot_checksum",
            checksum(self.catalog_snapshot_checksum, "cost_report.catalog_snapshot_checksum"),
        )
        object.__setattr__(self, "usage_watermark", non_negative_int(self.usage_watermark, "cost_report.usage_watermark"))
        aggregates = tuple(self.aggregates)
        if not all(isinstance(item, GraphArtifactCostAggregate) for item in aggregates):
            raise _schema_error("cost_report.aggregates")
        ordered = tuple(sorted(aggregates, key=lambda item: item.dimension.sort_key()))
        if aggregates != ordered or any(item.dimension.tenant_id != self.tenant_id for item in aggregates):
            raise _schema_error("cost_report.aggregates")
        object.__setattr__(self, "aggregates", aggregates)
        generated = aware_datetime(self.generated_at, "cost_report.generated_at")
        if generated < start:
            raise _schema_error("cost_report.generated_at")
        object.__setattr__(self, "generated_at", generated)
        expected_id = _derived_ref("graph-artifact-cost-report", self.identity_projection())
        if reference(self.report_id, "cost_report.report_id") != expected_id:
            raise _identity_error("cost_report.report_id")
        expected_checksum = checksum_for(self.checksum_projection())
        if checksum(self.report_checksum, "cost_report.report_checksum") != expected_checksum:
            raise _identity_error("cost_report.report_checksum")
        object.__setattr__(self, "report_id", expected_id)
        object.__setattr__(self, "report_checksum", expected_checksum)

    @classmethod
    def create(cls, **values: Any) -> Self:
        identity = _report_identity(values)
        report_id = _derived_ref("graph-artifact-cost-report", identity)
        projection = _report_projection({**values, "report_id": report_id})
        return cls(**values, report_id=report_id, report_checksum=checksum_for(projection))

    def identity_projection(self) -> dict[str, Any]:
        return _report_identity(_dataclass_values(self))

    def checksum_projection(self) -> dict[str, Any]:
        return _report_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "report_checksum": self.report_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "report_id",
                    "tenant_id",
                    "window_start",
                    "window_end",
                    "provisional",
                    "policy_version",
                    "catalog_snapshot_checksum",
                    "usage_watermark",
                    "aggregates",
                    "generated_at",
                    "report_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["window_start"] = datetime_from_json(payload["window_start"], "cost_report.window_start")
        payload["window_end"] = datetime_from_json(payload["window_end"], "cost_report.window_end")
        payload["generated_at"] = datetime_from_json(payload["generated_at"], "cost_report.generated_at")
        payload["aggregates"] = tuple(GraphArtifactCostAggregate.from_dict(item) for item in payload["aggregates"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class GraphArtifactAlert:
    alert_id: str
    kind: GraphArtifactAlertKind
    status: GraphArtifactAlertStatus
    tenant_id: str
    scope_ref: str
    policy_version: str
    window_start: datetime
    window_end: datetime
    observed_value: int
    limit_value: int
    reason_code: str
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    alert_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", enum_value(GraphArtifactAlertKind, self.kind, "alert.kind"))
        status = enum_value(GraphArtifactAlertStatus, self.status, "alert.status")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "alert.tenant_id"))
        object.__setattr__(self, "scope_ref", reference(self.scope_ref, "alert.scope_ref"))
        object.__setattr__(self, "policy_version", exact_reference(self.policy_version, "alert.policy_version"))
        start = aware_datetime(self.window_start, "alert.window_start")
        end = aware_datetime(self.window_end, "alert.window_end")
        if end <= start:
            raise _schema_error("alert.window")
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "observed_value", non_negative_int(self.observed_value, "alert.observed_value"))
        object.__setattr__(self, "limit_value", non_negative_int(self.limit_value, "alert.limit_value"))
        try:
            reason = GraphArtifactAlertReason(self.reason_code).value
        except (TypeError, ValueError) as exc:
            raise _schema_error("alert.reason_code") from exc
        object.__setattr__(self, "reason_code", reason)
        created = aware_datetime(self.created_at, "alert.created_at")
        object.__setattr__(self, "created_at", created)
        acknowledged_at = self.acknowledged_at
        acknowledged_by = self.acknowledged_by
        if status is GraphArtifactAlertStatus.ACKNOWLEDGED:
            if acknowledged_at is None or acknowledged_by is None:
                raise _schema_error("alert.acknowledgement")
            acknowledged_at = aware_datetime(acknowledged_at, "alert.acknowledged_at")
            if acknowledged_at < created:
                raise _schema_error("alert.acknowledged_at")
            acknowledged_by = identifier(acknowledged_by, "alert.acknowledged_by")
        elif acknowledged_at is not None or acknowledged_by is not None:
            raise _schema_error("alert.acknowledgement")
        object.__setattr__(self, "acknowledged_at", acknowledged_at)
        object.__setattr__(self, "acknowledged_by", acknowledged_by)
        expected_id = _derived_ref("graph-artifact-alert", self.identity_projection())
        if reference(self.alert_id, "alert.alert_id") != expected_id:
            raise _identity_error("alert.alert_id")
        expected_checksum = checksum_for(self.checksum_projection())
        if checksum(self.alert_checksum, "alert.alert_checksum") != expected_checksum:
            raise _identity_error("alert.alert_checksum")
        object.__setattr__(self, "alert_id", expected_id)
        object.__setattr__(self, "alert_checksum", expected_checksum)

    @classmethod
    def create(cls, **values: Any) -> Self:
        alert_id = _derived_ref("graph-artifact-alert", _alert_identity(values))
        projection = _alert_projection({**values, "alert_id": alert_id})
        return cls(**values, alert_id=alert_id, alert_checksum=checksum_for(projection))

    def identity_projection(self) -> dict[str, Any]:
        return _alert_identity(_dataclass_values(self))

    def checksum_projection(self) -> dict[str, Any]:
        return _alert_projection(_dataclass_values(self))

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "alert_checksum": self.alert_checksum}

    def acknowledge(
        self,
        *,
        acknowledged_at: datetime,
        acknowledged_by: str,
    ) -> Self:
        if self.status is GraphArtifactAlertStatus.ACKNOWLEDGED:
            if (
                self.acknowledged_at == acknowledged_at
                and self.acknowledged_by == acknowledged_by
            ):
                return self
            raise _identity_error("alert.acknowledgement")
        values = _dataclass_values(self)
        values.pop("alert_id")
        values.pop("alert_checksum")
        values.update(
            {
                "status": GraphArtifactAlertStatus.ACKNOWLEDGED,
                "acknowledged_at": acknowledged_at,
                "acknowledged_by": acknowledged_by,
            }
        )
        return type(self).create(**values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "alert_id",
                    "kind",
                    "status",
                    "tenant_id",
                    "scope_ref",
                    "policy_version",
                    "window_start",
                    "window_end",
                    "observed_value",
                    "limit_value",
                    "reason_code",
                    "created_at",
                    "acknowledged_at",
                    "acknowledged_by",
                    "alert_checksum",
                }
            ),
            model=cls.__name__,
        )
        for name in ("window_start", "window_end", "created_at"):
            payload[name] = datetime_from_json(payload[name], f"alert.{name}")
        if payload["acknowledged_at"] is not None:
            payload["acknowledged_at"] = datetime_from_json(payload["acknowledged_at"], "alert.acknowledged_at")
        return cls(**payload)


@runtime_checkable
class GraphArtifactUsagePort(Protocol):
    def record_usage(self, fact: GraphArtifactUsageFact) -> GraphArtifactUsageFact:
        ...

    def list_usage(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
        watermark: int | None = None,
    ) -> tuple[GraphArtifactUsageFact, ...]:
        ...

    def usage_watermark(self, *, tenant_id: str) -> int:
        ...


@runtime_checkable
class GraphArtifactPhysicalLifecyclePort(Protocol):
    def quarantine(
        self,
        request: GraphArtifactPhysicalDeleteRequest,
    ) -> GraphArtifactQuarantineReceipt:
        ...

    def purge(
        self,
        receipt: GraphArtifactQuarantineReceipt,
    ) -> GraphArtifactDeletionReceipt:
        ...


@runtime_checkable
class GraphArtifactGovernanceLedgerPort(GraphArtifactUsagePort, Protocol):
    def put_gc_plan(
        self,
        *,
        tenant_id: str,
        plan: ArtifactCatalogGcPlan,
    ) -> ArtifactCatalogGcPlan:
        ...

    def get_gc_plan(
        self,
        *,
        tenant_id: str,
        plan_checksum: str,
    ) -> ArtifactCatalogGcPlan | None:
        ...

    def put_gc_operation(
        self,
        operation: GraphArtifactGcOperation,
    ) -> GraphArtifactGcOperation:
        ...

    def get_gc_operation(
        self,
        *,
        tenant_id: str,
        operation_id: str,
    ) -> GraphArtifactGcOperation | None:
        ...

    def compare_and_set_gc_operation(
        self,
        operation: GraphArtifactGcOperation,
        *,
        expected_checksum: str,
    ) -> GraphArtifactGcOperation:
        ...

    def list_gc_operations(
        self,
        *,
        tenant_id: str,
        include_completed: bool = False,
    ) -> tuple[GraphArtifactGcOperation, ...]:
        ...

    def put_gc_tombstone(
        self,
        tombstone: GraphArtifactDeletionTombstone,
    ) -> GraphArtifactDeletionTombstone:
        ...

    def get_gc_tombstone(
        self,
        *,
        tenant_id: str,
        operation_id: str,
    ) -> GraphArtifactDeletionTombstone | None:
        ...

    def put_cost_report(
        self,
        report: DailyGraphArtifactCostReport,
    ) -> DailyGraphArtifactCostReport:
        ...

    def get_cost_report(
        self,
        *,
        tenant_id: str,
        report_id: str,
    ) -> DailyGraphArtifactCostReport | None:
        ...

    def list_cost_reports(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[DailyGraphArtifactCostReport, ...]:
        ...

    def put_alert(self, alert: GraphArtifactAlert) -> GraphArtifactAlert:
        ...

    def get_alert(
        self,
        *,
        tenant_id: str,
        alert_id: str,
    ) -> GraphArtifactAlert | None:
        ...

    def list_alerts(
        self,
        *,
        tenant_id: str,
        status: GraphArtifactAlertStatus | None = None,
    ) -> tuple[GraphArtifactAlert, ...]:
        ...

    def acknowledge_alert(
        self,
        *,
        tenant_id: str,
        alert_id: str,
        expected_checksum: str,
        acknowledged_at: datetime,
        acknowledged_by: str,
    ) -> GraphArtifactAlert:
        ...


def _usage_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": values["fact_id"],
        "kind": _enum_text(values["kind"]),
        "outcome": _enum_text(values["outcome"]),
        "tenant_id": values["tenant_id"],
        "run_id": values.get("run_id"),
        "graph_id": values.get("graph_id"),
        "node_id": values.get("node_id"),
        "artifact_class": _optional_enum_text(values.get("artifact_class")),
        "retention_class": _optional_enum_text(values.get("retention_class")),
        "policy_version": values["policy_version"],
        "operation_id": values["operation_id"],
        "logical_bytes": values["logical_bytes"],
        "physical_bytes": values["physical_bytes"],
        "loaded_bytes": values["loaded_bytes"],
        "loaded_tokens": values["loaded_tokens"],
        "object_count": values["object_count"],
        "reason_code": values.get("reason_code"),
        "occurred_at": datetime_to_json(values["occurred_at"]),
    }


def _quota_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope": _enum_text(values["scope"]),
        "tenant_id": values["tenant_id"],
        "run_id": values.get("run_id"),
        "artifact_class": _optional_enum_text(values.get("artifact_class")),
        "charged_bytes": values["charged_bytes"],
        "charged_objects": values["charged_objects"],
        "pending_bytes": values["pending_bytes"],
        "pending_objects": values["pending_objects"],
        "limit_bytes": values["limit_bytes"],
        "limit_objects": values["limit_objects"],
        "captured_at": datetime_to_json(values["captured_at"]),
    }


def _gc_intent_identity(values: Mapping[str, Any]) -> dict[str, Any]:
    decision = values["decision"]
    decision_checksum = (
        decision.decision_checksum
        if isinstance(decision, ArtifactCatalogGcDecision)
        else decision["decision_checksum"]
    )
    return {
        "tenant_id": values["tenant_id"],
        "plan_checksum": values["plan_checksum"],
        "decision_checksum": decision_checksum,
    }


def _gc_intent_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    decision = values["decision"]
    entry = values["entry"]
    claims = tuple(sorted(values["claims"], key=lambda item: item.claim_id))
    references = tuple(
        sorted(values["references"], key=lambda item: item.reference_id)
    )
    return {
        "operation_id": values["operation_id"],
        "tenant_id": values["tenant_id"],
        "plan_checksum": values["plan_checksum"],
        "catalog_snapshot_checksum": values["catalog_snapshot_checksum"],
        "policy_version": values["policy_version"],
        "decision": (
            decision.to_dict()
            if isinstance(decision, ArtifactCatalogGcDecision)
            else decision
        ),
        "entry": entry.to_dict() if isinstance(entry, ArtifactCatalogEntry) else entry,
        "claims": [
            item.to_dict() if isinstance(item, ArtifactCatalogClaim) else item
            for item in claims
        ],
        "references": [
            item.to_dict() if isinstance(item, ArtifactLogicalReference) else item
            for item in references
        ],
        "prepared_at": datetime_to_json(values["prepared_at"]),
    }


def _delete_request_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    record = values["record"]
    detach_receipt = values["detach_receipt"]
    return {
        "operation_id": values["operation_id"],
        "plan_checksum": values["plan_checksum"],
        "decision_checksum": values["decision_checksum"],
        "intent_checksum": values["intent_checksum"],
        "record": record.to_dict() if isinstance(record, ArtifactRecord) else record,
        "detach_receipt": (
            detach_receipt.to_dict()
            if isinstance(detach_receipt, ArtifactCatalogGcDetachReceipt)
            else detach_receipt
        ),
        "requested_at": datetime_to_json(values["requested_at"]),
    }


def _quarantine_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": values["operation_id"],
        "ref": values["ref"],
        "content_checksum": values["content_checksum"],
        "byte_size": values["byte_size"],
        "quarantined_at": datetime_to_json(values["quarantined_at"]),
    }


def _deletion_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": values["operation_id"],
        "quarantine_receipt_checksum": values["quarantine_receipt_checksum"],
        "ref": values["ref"],
        "content_checksum": values["content_checksum"],
        "byte_size": values["byte_size"],
        "deleted_at": datetime_to_json(values["deleted_at"]),
    }


def _gc_operation_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    intent = values["intent"]
    request_value = values["request"]
    quarantine = values.get("quarantine")
    deletion = values.get("deletion")
    return {
        "operation_id": values["operation_id"],
        "state": _enum_text(values["state"]),
        "intent": (
            intent.to_dict()
            if isinstance(intent, GraphArtifactGcOperationIntent)
            else intent
        ),
        "request": request_value.to_dict() if isinstance(request_value, GraphArtifactPhysicalDeleteRequest) else request_value,
        "quarantine": quarantine.to_dict() if isinstance(quarantine, GraphArtifactQuarantineReceipt) else quarantine,
        "deletion": deletion.to_dict() if isinstance(deletion, GraphArtifactDeletionReceipt) else deletion,
        "error_code": _optional_enum_text(values.get("error_code")),
        "updated_at": datetime_to_json(values["updated_at"]),
    }


def _gc_tombstone_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tombstone_id": values["tombstone_id"],
        "operation_id": values["operation_id"],
        "tenant_id": values["tenant_id"],
        "entry_id": values["entry_id"],
        "ref": values["ref"],
        "content_checksum": values["content_checksum"],
        "byte_size": values["byte_size"],
        "policy_version": values["policy_version"],
        "deletion_receipt_checksum": values["deletion_receipt_checksum"],
        "completed_at": datetime_to_json(values["completed_at"]),
    }


def _report_identity(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": values["tenant_id"],
        "window_start": datetime_to_json(values["window_start"]),
        "window_end": datetime_to_json(values["window_end"]),
        "policy_version": values["policy_version"],
        "catalog_snapshot_checksum": values["catalog_snapshot_checksum"],
        "usage_watermark": values["usage_watermark"],
    }


def _report_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    aggregates = values["aggregates"]
    return {
        "report_id": values["report_id"],
        "tenant_id": values["tenant_id"],
        "window_start": datetime_to_json(values["window_start"]),
        "window_end": datetime_to_json(values["window_end"]),
        "provisional": values["provisional"],
        "policy_version": values["policy_version"],
        "catalog_snapshot_checksum": values["catalog_snapshot_checksum"],
        "usage_watermark": values["usage_watermark"],
        "aggregates": [item.to_dict() if isinstance(item, GraphArtifactCostAggregate) else item for item in aggregates],
        "generated_at": datetime_to_json(values["generated_at"]),
    }


def _alert_identity(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": _enum_text(values["kind"]),
        "tenant_id": values["tenant_id"],
        "scope_ref": values["scope_ref"],
        "policy_version": values["policy_version"],
        "window_start": datetime_to_json(values["window_start"]),
        "window_end": datetime_to_json(values["window_end"]),
    }


def _alert_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": values["alert_id"],
        "kind": _enum_text(values["kind"]),
        "status": _enum_text(values["status"]),
        "tenant_id": values["tenant_id"],
        "scope_ref": values["scope_ref"],
        "policy_version": values["policy_version"],
        "window_start": datetime_to_json(values["window_start"]),
        "window_end": datetime_to_json(values["window_end"]),
        "observed_value": values["observed_value"],
        "limit_value": values["limit_value"],
        "reason_code": values["reason_code"],
        "created_at": datetime_to_json(values["created_at"]),
        "acknowledged_at": (
            datetime_to_json(values["acknowledged_at"])
            if values.get("acknowledged_at") is not None
            else None
        ),
        "acknowledged_by": values.get("acknowledged_by"),
    }


def _dataclass_values(value: Any) -> dict[str, Any]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _typed_tuple(value: Any, expected: type[Any], field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise _schema_error(field)
    try:
        items = tuple(value)
    except TypeError as exc:
        raise _schema_error(field) from exc
    if not all(isinstance(item, expected) for item in items):
        raise _schema_error(field)
    return items


def _derived_ref(scheme: str, value: Mapping[str, Any]) -> str:
    return f"{scheme}://{checksum_for(dict(value)).removeprefix('sha256:')}"


def _optional_identifier(value: Any, field: str) -> str | None:
    return None if value is None else identifier(value, field)


def _optional_enum(enum_type: type[Any], value: Any, field: str) -> Any:
    return None if value is None else enum_value(enum_type, value, field)


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _optional_enum_text(value: Any) -> str | None:
    return None if value is None else _enum_text(value)


def _controlled_reason_code(value: Any) -> str | None:
    text = optional_text(value, "usage.reason_code", max_length=128)
    if text is None:
        return None
    allowed = {item.value for item in GraphArtifactUsageReason} | {
        item.value for item in GraphArtifactResultErrorCode
    }
    if text not in allowed:
        raise _schema_error("usage.reason_code")
    return text


def _schema_error(field: str) -> Exception:
    return result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)


def _identity_error(field: str) -> Exception:
    return result_error(GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT, field=field)


__all__ = [
    "DailyGraphArtifactCostReport",
    "GraphArtifactDeletionTombstone",
    "GraphArtifactAlert",
    "GraphArtifactAlertKind",
    "GraphArtifactAlertReason",
    "GraphArtifactAlertStatus",
    "GraphArtifactCostAggregate",
    "GraphArtifactCostDimension",
    "GraphArtifactDeletionReceipt",
    "GraphArtifactGcOperation",
    "GraphArtifactGcOperationIntent",
    "GraphArtifactGcOperationState",
    "GraphArtifactGovernanceLedgerPort",
    "GraphArtifactPhysicalDeleteRequest",
    "GraphArtifactPhysicalLifecyclePort",
    "GraphArtifactQuarantineReceipt",
    "GraphArtifactQuotaScope",
    "GraphArtifactQuotaSnapshot",
    "GraphArtifactUsageFact",
    "GraphArtifactUsageKind",
    "GraphArtifactUsageOutcome",
    "GraphArtifactUsageReason",
    "GraphArtifactUsagePort",
]
