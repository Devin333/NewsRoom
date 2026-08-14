from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from framework.events.canonical import checksum_for
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
    media_type,
    non_negative_int,
    reference,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import ArtifactRecord


class ArtifactReferenceKind(StrEnum):
    RUN = "run"
    REPORT = "report"
    EVIDENCE = "evidence"
    PUBLICATION = "publication"
    REPLAY = "replay"
    CACHE = "cache"
    EPHEMERAL = "ephemeral"


class ArtifactCatalogGcAction(StrEnum):
    KEEP = "keep"
    DELETE_CANDIDATE = "delete_candidate"


class ArtifactCatalogGcReason(StrEnum):
    REFERENCE_PROTECTED = "reference_protected"
    REPLAY_REQUIRED = "replay_required"
    PUBLICATION_REQUIRED = "publication_required"
    RETENTION_INDEFINITE = "retention_indefinite"
    RETENTION_ACTIVE = "retention_active"
    EXPIRED_UNREFERENCED = "expired_unreferenced"


class ArtifactCatalogReconciliationIssueKind(StrEnum):
    ORPHAN_ENTRY = "orphan_entry"
    DANGLING_LOGICAL_IDENTITY = "dangling_logical_identity"
    DANGLING_REFERENCE = "dangling_reference"
    IDENTITY_CONFLICT = "identity_conflict"
    MISSING_PHYSICAL_OBJECT = "missing_physical_object"
    UNREGISTERED_PHYSICAL_OBJECT = "unregistered_physical_object"
    PHYSICAL_IDENTITY_MISMATCH = "physical_identity_mismatch"


_PROTECTED_REFERENCE_KINDS = frozenset(
    {
        ArtifactReferenceKind.RUN,
        ArtifactReferenceKind.REPORT,
        ArtifactReferenceKind.EVIDENCE,
        ArtifactReferenceKind.PUBLICATION,
        ArtifactReferenceKind.REPLAY,
    }
)
_EXPIRING_REFERENCE_KINDS = frozenset(
    {ArtifactReferenceKind.CACHE, ArtifactReferenceKind.EPHEMERAL}
)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogIdentity:
    tenant_id: str
    content_checksum: str
    media_type: str
    producer_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "catalog_identity.tenant_id"))
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "catalog_identity.content_checksum"),
        )
        object.__setattr__(self, "media_type", media_type(self.media_type, "catalog_identity.media_type"))
        object.__setattr__(
            self,
            "producer_revision",
            exact_reference(self.producer_revision, "catalog_identity.producer_revision"),
        )

    @classmethod
    def from_record(cls, record: ArtifactRecord) -> Self:
        _require_type(record, ArtifactRecord, "record")
        return cls(
            tenant_id=record.tenant_id,
            content_checksum=record.content_checksum,
            media_type=record.media_type,
            producer_revision=record.producer_revision,
        )

    @property
    def entry_id(self) -> str:
        return _derived_reference("catalog-entry", self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "content_checksum": self.content_checksum,
            "media_type": self.media_type,
            "producer_revision": self.producer_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {"tenant_id", "content_checksum", "media_type", "producer_revision"}
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactVerificationReceipt:
    tenant_id: str
    ref: str
    content_checksum: str
    byte_size: int
    media_type: str
    verified_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", identifier(self.tenant_id, "verification.tenant_id"))
        object.__setattr__(self, "ref", reference(self.ref, "verification.ref"))
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "verification.content_checksum"),
        )
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "verification.byte_size"))
        object.__setattr__(self, "media_type", media_type(self.media_type, "verification.media_type"))
        object.__setattr__(self, "verified_at", aware_datetime(self.verified_at, "verification.verified_at"))

    @classmethod
    def for_record(cls, record: ArtifactRecord, *, verified_at: datetime) -> Self:
        _require_type(record, ArtifactRecord, "record")
        return cls(
            tenant_id=record.tenant_id,
            ref=record.ref,
            content_checksum=record.content_checksum,
            byte_size=record.byte_size,
            media_type=record.media_type,
            verified_at=verified_at,
        )

    def verify(self, record: ArtifactRecord) -> None:
        _require_type(record, ArtifactRecord, "record")
        if self.tenant_id != record.tenant_id:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="verification.tenant_id",
            )
        fields = {
            "ref": (self.ref, record.ref),
            "content_checksum": (self.content_checksum, record.content_checksum),
            "byte_size": (self.byte_size, record.byte_size),
            "media_type": (self.media_type, record.media_type),
        }
        for field_name, (actual, expected) in fields.items():
            if actual != expected:
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                    field=f"verification.{field_name}",
                )
        if self.verified_at < record.created_at:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                field="verification.verified_at",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "ref": self.ref,
            "content_checksum": self.content_checksum,
            "byte_size": self.byte_size,
            "media_type": self.media_type,
            "verified_at": datetime_to_json(self.verified_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {"tenant_id", "ref", "content_checksum", "byte_size", "media_type", "verified_at"}
            ),
            model=cls.__name__,
        )
        payload["verified_at"] = datetime_from_json(payload["verified_at"], "verification.verified_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogEntry:
    entry_id: str
    identity: ArtifactCatalogIdentity
    record: ArtifactRecord
    verified_at: datetime

    def __post_init__(self) -> None:
        _require_type(self.identity, ArtifactCatalogIdentity, "catalog_entry.identity")
        _require_type(self.record, ArtifactRecord, "catalog_entry.record")
        expected_identity = ArtifactCatalogIdentity.from_record(self.record)
        if self.identity != expected_identity:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="catalog_entry.identity",
            )
        expected_entry_id = self.identity.entry_id
        actual_entry_id = reference(self.entry_id, "catalog_entry.entry_id")
        if actual_entry_id != expected_entry_id:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="catalog_entry.entry_id",
            )
        verified_at = aware_datetime(self.verified_at, "catalog_entry.verified_at")
        if verified_at < self.record.created_at:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                field="catalog_entry.verified_at",
            )
        object.__setattr__(self, "entry_id", actual_entry_id)
        object.__setattr__(self, "verified_at", verified_at)

    @classmethod
    def from_verified_record(
        cls,
        record: ArtifactRecord,
        receipt: ArtifactVerificationReceipt,
    ) -> Self:
        _require_type(receipt, ArtifactVerificationReceipt, "receipt")
        receipt.verify(record)
        identity = ArtifactCatalogIdentity.from_record(record)
        return cls(
            entry_id=identity.entry_id,
            identity=identity,
            record=record,
            verified_at=receipt.verified_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "identity": self.identity.to_dict(),
            "record": self.record.to_dict(),
            "verified_at": datetime_to_json(self.verified_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset({"entry_id", "identity", "record", "verified_at"}),
            model=cls.__name__,
        )
        payload["identity"] = ArtifactCatalogIdentity.from_dict(payload["identity"])
        payload["record"] = ArtifactRecord.from_dict(payload["record"])
        payload["verified_at"] = datetime_from_json(payload["verified_at"], "catalog_entry.verified_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogClaim:
    claim_id: str
    entry_id: str
    tenant_id: str
    run_id: str
    artifact_id: str
    created_at: datetime
    record: ArtifactRecord

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", reference(self.entry_id, "catalog_claim.entry_id"))
        _require_type(self.record, ArtifactRecord, "catalog_claim.record")
        for field_name in ("tenant_id", "run_id", "artifact_id"):
            object.__setattr__(
                self,
                field_name,
                identifier(getattr(self, field_name), f"catalog_claim.{field_name}"),
            )
        expected = _derived_reference("catalog-claim", self.logical_identity())
        actual = reference(self.claim_id, "catalog_claim.claim_id")
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="catalog_claim.claim_id",
            )
        object.__setattr__(self, "claim_id", actual)
        created_at = aware_datetime(self.created_at, "catalog_claim.created_at")
        object.__setattr__(self, "created_at", created_at)
        if (
            self.record.tenant_id != self.tenant_id
            or self.record.run_id != self.run_id
            or self.record.artifact_id != self.artifact_id
            or ArtifactCatalogIdentity.from_record(self.record).entry_id != self.entry_id
            or self.record.created_at != created_at
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="catalog_claim.record",
            )

    @classmethod
    def claim_id_for(
        cls,
        *,
        tenant_id: str,
        run_id: str,
        artifact_id: str,
    ) -> str:
        identity = {
            "tenant_id": identifier(tenant_id, "catalog_claim.tenant_id"),
            "run_id": identifier(run_id, "catalog_claim.run_id"),
            "artifact_id": identifier(artifact_id, "catalog_claim.artifact_id"),
        }
        return _derived_reference("catalog-claim", identity)

    @classmethod
    def for_record(
        cls,
        record: ArtifactRecord,
        *,
        entry_id: str,
        canonical_ref: str | None = None,
    ) -> Self:
        _require_type(record, ArtifactRecord, "record")
        logical_record = (
            replace(record, ref=reference(canonical_ref, "catalog_claim.canonical_ref"))
            if canonical_ref is not None
            else record
        )
        return cls(
            claim_id=cls.claim_id_for(
                tenant_id=record.tenant_id,
                run_id=record.run_id,
                artifact_id=record.artifact_id,
            ),
            entry_id=entry_id,
            tenant_id=record.tenant_id,
            run_id=record.run_id,
            artifact_id=record.artifact_id,
            created_at=record.created_at,
            record=logical_record,
        )

    def logical_identity(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "created_at": datetime_to_json(self.created_at),
            "record": self.record.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "claim_id",
                    "entry_id",
                    "tenant_id",
                    "run_id",
                    "artifact_id",
                    "created_at",
                    "record",
                }
            ),
            model=cls.__name__,
        )
        payload["created_at"] = datetime_from_json(payload["created_at"], "catalog_claim.created_at")
        payload["record"] = ArtifactRecord.from_dict(payload["record"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactLogicalReference:
    reference_id: str
    entry_id: str
    tenant_id: str
    owner_run_id: str
    owner_id: str
    kind: ArtifactReferenceKind
    expires_at: datetime | None
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", reference(self.entry_id, "logical_reference.entry_id"))
        for field_name in ("tenant_id", "owner_run_id", "owner_id"):
            object.__setattr__(
                self,
                field_name,
                identifier(getattr(self, field_name), f"logical_reference.{field_name}"),
            )
        object.__setattr__(
            self,
            "kind",
            enum_value(ArtifactReferenceKind, self.kind, "logical_reference.kind"),
        )
        created_at = aware_datetime(self.created_at, "logical_reference.created_at")
        object.__setattr__(self, "created_at", created_at)
        expires_at = self.expires_at
        if expires_at is not None:
            expires_at = aware_datetime(expires_at, "logical_reference.expires_at")
            if expires_at <= created_at:
                raise result_error(
                    GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                    field="logical_reference.expires_at",
                )
        if self.kind in _PROTECTED_REFERENCE_KINDS and expires_at is not None:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="logical_reference.expires_at",
            )
        if self.kind in _EXPIRING_REFERENCE_KINDS and expires_at is None:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="logical_reference.expires_at",
            )
        object.__setattr__(self, "expires_at", expires_at)
        expected = _derived_reference("catalog-reference", self.logical_identity())
        actual = reference(self.reference_id, "logical_reference.reference_id")
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT,
                field="logical_reference.reference_id",
            )
        object.__setattr__(self, "reference_id", actual)

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        tenant_id: str,
        owner_run_id: str,
        owner_id: str,
        kind: ArtifactReferenceKind,
        created_at: datetime,
        expires_at: datetime | None = None,
    ) -> Self:
        identity = {
            "entry_id": entry_id,
            "tenant_id": tenant_id,
            "owner_run_id": owner_run_id,
            "owner_id": owner_id,
            "kind": ArtifactReferenceKind(kind).value,
        }
        return cls(
            reference_id=_derived_reference("catalog-reference", identity),
            entry_id=entry_id,
            tenant_id=tenant_id,
            owner_run_id=owner_run_id,
            owner_id=owner_id,
            kind=kind,
            expires_at=expires_at,
            created_at=created_at,
        )

    def logical_identity(self) -> dict[str, str]:
        return {
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "owner_run_id": self.owner_run_id,
            "owner_id": self.owner_id,
            "kind": self.kind.value,
        }

    def is_active_at(self, now: datetime) -> bool:
        actual_now = aware_datetime(now, "logical_reference.active_at")
        return self.expires_at is None or self.expires_at > actual_now

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "owner_run_id": self.owner_run_id,
            "owner_id": self.owner_id,
            "kind": self.kind.value,
            "expires_at": datetime_to_json(self.expires_at) if self.expires_at is not None else None,
            "created_at": datetime_to_json(self.created_at),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "reference_id",
                    "entry_id",
                    "tenant_id",
                    "owner_run_id",
                    "owner_id",
                    "kind",
                    "expires_at",
                    "created_at",
                }
            ),
            model=cls.__name__,
        )
        payload["expires_at"] = (
            datetime_from_json(payload["expires_at"], "logical_reference.expires_at")
            if payload["expires_at"] is not None
            else None
        )
        payload["created_at"] = datetime_from_json(payload["created_at"], "logical_reference.created_at")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogRegistrationRequest:
    record: ArtifactRecord
    verification: ArtifactVerificationReceipt
    initial_reference: ArtifactLogicalReference

    def __post_init__(self) -> None:
        _require_type(self.record, ArtifactRecord, "registration.record")
        _require_type(self.verification, ArtifactVerificationReceipt, "registration.verification")
        _require_type(self.initial_reference, ArtifactLogicalReference, "registration.initial_reference")
        self.verification.verify(self.record)
        entry_id = ArtifactCatalogIdentity.from_record(self.record).entry_id
        reference_value = self.initial_reference
        expected_kind = _initial_reference_kind(self.record)
        expected_expires_at = (
            self.record.expires_at
            if expected_kind in _EXPIRING_REFERENCE_KINDS
            else None
        )
        if (
            reference_value.entry_id != entry_id
            or reference_value.tenant_id != self.record.tenant_id
            or reference_value.owner_run_id != self.record.run_id
            or reference_value.owner_id != self.record.artifact_id
            or reference_value.kind is not expected_kind
            or reference_value.created_at != self.record.created_at
            or reference_value.expires_at != expected_expires_at
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT,
                field="registration.initial_reference",
            )

    @classmethod
    def from_verified_record(
        cls,
        record: ArtifactRecord,
        *,
        verified_at: datetime,
    ) -> Self:
        identity = ArtifactCatalogIdentity.from_record(record)
        receipt = ArtifactVerificationReceipt.for_record(record, verified_at=verified_at)
        initial_kind = _initial_reference_kind(record)
        initial_reference = ArtifactLogicalReference.create(
            entry_id=identity.entry_id,
            tenant_id=record.tenant_id,
            owner_run_id=record.run_id,
            owner_id=record.artifact_id,
            kind=initial_kind,
            created_at=record.created_at,
            expires_at=(
                record.expires_at
                if initial_kind in _EXPIRING_REFERENCE_KINDS
                else None
            ),
        )
        return cls(record=record, verification=receipt, initial_reference=initial_reference)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "verification": self.verification.to_dict(),
            "initial_reference": self.initial_reference.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset({"record", "verification", "initial_reference"}),
            model=cls.__name__,
        )
        return cls(
            record=ArtifactRecord.from_dict(payload["record"]),
            verification=ArtifactVerificationReceipt.from_dict(payload["verification"]),
            initial_reference=ArtifactLogicalReference.from_dict(payload["initial_reference"]),
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogRegistrationResult:
    entry: ArtifactCatalogEntry
    claim: ArtifactCatalogClaim
    reference: ArtifactLogicalReference
    deduplicated: bool

    def __post_init__(self) -> None:
        _require_type(self.entry, ArtifactCatalogEntry, "registration_result.entry")
        _require_type(self.claim, ArtifactCatalogClaim, "registration_result.claim")
        _require_type(self.reference, ArtifactLogicalReference, "registration_result.reference")
        object.__setattr__(self, "deduplicated", boolean(self.deduplicated, "registration_result.deduplicated"))
        if self.claim.entry_id != self.entry.entry_id or self.reference.entry_id != self.entry.entry_id:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="registration_result.entry_id",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "claim": self.claim.to_dict(),
            "reference": self.reference.to_dict(),
            "deduplicated": self.deduplicated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset({"entry", "claim", "reference", "deduplicated"}),
            model=cls.__name__,
        )
        return cls(
            entry=ArtifactCatalogEntry.from_dict(payload["entry"]),
            claim=ArtifactCatalogClaim.from_dict(payload["claim"]),
            reference=ArtifactLogicalReference.from_dict(payload["reference"]),
            deduplicated=payload["deduplicated"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogGcDecision:
    entry_id: str
    ref: str
    action: ArtifactCatalogGcAction
    reason: ArtifactCatalogGcReason
    active_reference_ids: tuple[str, ...]
    byte_size: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", reference(self.entry_id, "gc_decision.entry_id"))
        object.__setattr__(self, "ref", reference(self.ref, "gc_decision.ref"))
        object.__setattr__(self, "action", enum_value(ArtifactCatalogGcAction, self.action, "gc_decision.action"))
        object.__setattr__(self, "reason", enum_value(ArtifactCatalogGcReason, self.reason, "gc_decision.reason"))
        refs = _reference_tuple(self.active_reference_ids, "gc_decision.active_reference_ids")
        object.__setattr__(self, "active_reference_ids", refs)
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "gc_decision.byte_size"))
        if self.action is ArtifactCatalogGcAction.DELETE_CANDIDATE and refs:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_decision.active_reference_ids",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "ref": self.ref,
            "action": self.action.value,
            "reason": self.reason.value,
            "active_reference_ids": list(self.active_reference_ids),
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {"entry_id", "ref", "action", "reason", "active_reference_ids", "byte_size"}
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogGcPlan:
    generated_at: datetime
    decisions: tuple[ArtifactCatalogGcDecision, ...]
    plan_checksum: str

    def __post_init__(self) -> None:
        generated_at = aware_datetime(self.generated_at, "gc_plan.generated_at")
        decisions = _model_tuple(self.decisions, ArtifactCatalogGcDecision, "gc_plan.decisions")
        decisions = tuple(sorted(decisions, key=lambda item: item.entry_id))
        expected = checksum_for(
            {
                "generated_at": datetime_to_json(generated_at),
                "decisions": [item.to_dict() for item in decisions],
            }
        )
        actual = checksum(self.plan_checksum, "gc_plan.plan_checksum")
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="gc_plan.plan_checksum",
            )
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "plan_checksum", actual)

    @classmethod
    def create(
        cls,
        *,
        generated_at: datetime,
        decisions: Sequence[ArtifactCatalogGcDecision],
    ) -> Self:
        ordered = tuple(sorted(decisions, key=lambda item: item.entry_id))
        payload = {
            "generated_at": datetime_to_json(aware_datetime(generated_at, "gc_plan.generated_at")),
            "decisions": [item.to_dict() for item in ordered],
        }
        return cls(
            generated_at=generated_at,
            decisions=ordered,
            plan_checksum=checksum_for(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime_to_json(self.generated_at),
            "decisions": [item.to_dict() for item in self.decisions],
            "plan_checksum": self.plan_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset({"generated_at", "decisions", "plan_checksum"}),
            model=cls.__name__,
        )
        return cls(
            generated_at=datetime_from_json(payload["generated_at"], "gc_plan.generated_at"),
            decisions=tuple(
                ArtifactCatalogGcDecision.from_dict(item)
                for item in _mapping_sequence(payload["decisions"], "gc_plan.decisions")
            ),
            plan_checksum=payload["plan_checksum"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogReconciliationIssue:
    issue_id: str
    kind: ArtifactCatalogReconciliationIssueKind
    subject_id: str
    entry_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", enum_value(ArtifactCatalogReconciliationIssueKind, self.kind, "reconciliation_issue.kind"))
        object.__setattr__(self, "subject_id", reference(self.subject_id, "reconciliation_issue.subject_id"))
        entry_id = self.entry_id
        if entry_id is not None:
            entry_id = reference(entry_id, "reconciliation_issue.entry_id")
        object.__setattr__(self, "entry_id", entry_id)
        expected = _derived_reference(
            "catalog-issue",
            {"kind": self.kind.value, "subject_id": self.subject_id, "entry_id": entry_id},
        )
        actual = reference(self.issue_id, "reconciliation_issue.issue_id")
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="reconciliation_issue.issue_id",
            )
        object.__setattr__(self, "issue_id", actual)

    @classmethod
    def create(
        cls,
        *,
        kind: ArtifactCatalogReconciliationIssueKind,
        subject_id: str,
        entry_id: str | None = None,
    ) -> Self:
        normalized_kind = ArtifactCatalogReconciliationIssueKind(kind)
        payload = {"kind": normalized_kind.value, "subject_id": subject_id, "entry_id": entry_id}
        return cls(
            issue_id=_derived_reference("catalog-issue", payload),
            kind=normalized_kind,
            subject_id=subject_id,
            entry_id=entry_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "entry_id": self.entry_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset({"issue_id", "kind", "subject_id", "entry_id"}),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogReconciliationPlan:
    generated_at: datetime
    issues: tuple[ArtifactCatalogReconciliationIssue, ...]
    plan_checksum: str

    def __post_init__(self) -> None:
        generated_at = aware_datetime(self.generated_at, "reconciliation_plan.generated_at")
        issues = _model_tuple(self.issues, ArtifactCatalogReconciliationIssue, "reconciliation_plan.issues")
        issues = tuple(sorted(issues, key=lambda item: item.issue_id))
        expected = checksum_for(
            {
                "generated_at": datetime_to_json(generated_at),
                "issues": [item.to_dict() for item in issues],
            }
        )
        actual = checksum(self.plan_checksum, "reconciliation_plan.plan_checksum")
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="reconciliation_plan.plan_checksum",
            )
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "plan_checksum", actual)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    @classmethod
    def create(
        cls,
        *,
        generated_at: datetime,
        issues: Sequence[ArtifactCatalogReconciliationIssue],
    ) -> Self:
        ordered = tuple(sorted(issues, key=lambda item: item.issue_id))
        payload = {
            "generated_at": datetime_to_json(aware_datetime(generated_at, "reconciliation_plan.generated_at")),
            "issues": [item.to_dict() for item in ordered],
        }
        return cls(
            generated_at=generated_at,
            issues=ordered,
            plan_checksum=checksum_for(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime_to_json(self.generated_at),
            "issues": [item.to_dict() for item in self.issues],
            "plan_checksum": self.plan_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset({"generated_at", "issues", "plan_checksum"}),
            model=cls.__name__,
        )
        return cls(
            generated_at=datetime_from_json(payload["generated_at"], "reconciliation_plan.generated_at"),
            issues=tuple(
                ArtifactCatalogReconciliationIssue.from_dict(item)
                for item in _mapping_sequence(payload["issues"], "reconciliation_plan.issues")
            ),
            plan_checksum=payload["plan_checksum"],
        )


def _derived_reference(scheme: str, value: Mapping[str, Any]) -> str:
    digest = checksum_for(dict(value)).removeprefix("sha256:")
    return f"{scheme}://{digest}"


def _initial_reference_kind(record: ArtifactRecord) -> ArtifactReferenceKind:
    if record.required_for_replay or record.artifact_class.value == "transcript":
        return ArtifactReferenceKind.REPLAY
    if record.required_for_publication:
        return ArtifactReferenceKind.PUBLICATION
    if record.artifact_class.value == "report":
        return ArtifactReferenceKind.REPORT
    if record.artifact_class.value == "evidence":
        return ArtifactReferenceKind.EVIDENCE
    if record.retention_class.value == "cache":
        return ArtifactReferenceKind.CACHE
    if record.retention_class.value == "ephemeral":
        return ArtifactReferenceKind.EPHEMERAL
    return ArtifactReferenceKind.RUN


def _require_type(value: Any, expected: type[Any], field: str) -> None:
    if not isinstance(value, expected):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)


def _mapping_sequence(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
        result.append(item)
    return tuple(result)


def _model_tuple(value: Any, expected: type[Any], field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
    result = tuple(value)
    if not all(isinstance(item, expected) for item in result):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
    return result


def _reference_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
    normalized = tuple(reference(item, field) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise result_error(GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID, field=field)
    return normalized


__all__ = [
    "ArtifactCatalogClaim",
    "ArtifactCatalogEntry",
    "ArtifactCatalogGcAction",
    "ArtifactCatalogGcDecision",
    "ArtifactCatalogGcPlan",
    "ArtifactCatalogGcReason",
    "ArtifactCatalogIdentity",
    "ArtifactCatalogReconciliationIssue",
    "ArtifactCatalogReconciliationIssueKind",
    "ArtifactCatalogReconciliationPlan",
    "ArtifactCatalogRegistrationRequest",
    "ArtifactCatalogRegistrationResult",
    "ArtifactLogicalReference",
    "ArtifactReferenceKind",
    "ArtifactVerificationReceipt",
]
