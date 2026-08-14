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


class ArtifactLifecycleAuthorityKind(StrEnum):
    TERMINAL_RUN = "terminal_run"
    PUBLICATION_RETIRED = "publication_retired"


class ArtifactReferenceRetirementReason(StrEnum):
    RETENTION_EXPIRED = "retention_expired"
    PUBLICATION_RETIRED = "publication_retired"


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
    tenant_id: str
    ref: str
    action: ArtifactCatalogGcAction
    reason: ArtifactCatalogGcReason
    active_reference_ids: tuple[str, ...]
    byte_size: int
    claim_ids: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()
    decision_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", reference(self.entry_id, "gc_decision.entry_id"))
        object.__setattr__(
            self,
            "tenant_id",
            identifier(self.tenant_id, "gc_decision.tenant_id"),
        )
        object.__setattr__(self, "ref", reference(self.ref, "gc_decision.ref"))
        object.__setattr__(self, "action", enum_value(ArtifactCatalogGcAction, self.action, "gc_decision.action"))
        object.__setattr__(self, "reason", enum_value(ArtifactCatalogGcReason, self.reason, "gc_decision.reason"))
        refs = _reference_tuple(self.active_reference_ids, "gc_decision.active_reference_ids")
        object.__setattr__(self, "active_reference_ids", refs)
        object.__setattr__(self, "byte_size", non_negative_int(self.byte_size, "gc_decision.byte_size"))
        claims = _reference_tuple(self.claim_ids, "gc_decision.claim_ids")
        all_refs = _reference_tuple(self.reference_ids, "gc_decision.reference_ids")
        if not set(refs).issubset(all_refs):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_decision.reference_ids",
            )
        object.__setattr__(self, "claim_ids", claims)
        object.__setattr__(self, "reference_ids", all_refs)
        if self.action is ArtifactCatalogGcAction.DELETE_CANDIDATE and refs:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_decision.active_reference_ids",
            )
        expected = checksum_for(self.checksum_projection())
        actual = (
            expected
            if self.decision_checksum is None
            else checksum(self.decision_checksum, "gc_decision.decision_checksum")
        )
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="gc_decision.decision_checksum",
            )
        object.__setattr__(self, "decision_checksum", expected)

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "tenant_id": self.tenant_id,
            "ref": self.ref,
            "action": self.action.value,
            "reason": self.reason.value,
            "active_reference_ids": list(self.active_reference_ids),
            "byte_size": self.byte_size,
            "claim_ids": list(self.claim_ids),
            "reference_ids": list(self.reference_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "decision_checksum": self.decision_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "entry_id",
                        "tenant_id",
                        "ref",
                        "action",
                        "reason",
                        "active_reference_ids",
                        "byte_size",
                        "claim_ids",
                        "reference_ids",
                        "decision_checksum",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogGcPlan:
    generated_at: datetime
    decisions: tuple[ArtifactCatalogGcDecision, ...]
    plan_checksum: str
    catalog_snapshot_checksum: str = "sha256:" + "0" * 64
    policy_version: str = "graph-artifact-policy@1"

    def __post_init__(self) -> None:
        generated_at = aware_datetime(self.generated_at, "gc_plan.generated_at")
        decisions = _model_tuple(self.decisions, ArtifactCatalogGcDecision, "gc_plan.decisions")
        decisions = tuple(sorted(decisions, key=lambda item: item.entry_id))
        snapshot_checksum = checksum(
            self.catalog_snapshot_checksum,
            "gc_plan.catalog_snapshot_checksum",
        )
        policy_version = exact_reference(self.policy_version, "gc_plan.policy_version")
        expected = checksum_for(
            {
                "generated_at": datetime_to_json(generated_at),
                "decisions": [item.to_dict() for item in decisions],
                "catalog_snapshot_checksum": snapshot_checksum,
                "policy_version": policy_version,
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
        object.__setattr__(self, "catalog_snapshot_checksum", snapshot_checksum)
        object.__setattr__(self, "policy_version", policy_version)

    @classmethod
    def create(
        cls,
        *,
        generated_at: datetime,
        decisions: Sequence[ArtifactCatalogGcDecision],
        catalog_snapshot_checksum: str | None = None,
        policy_version: str = "graph-artifact-policy@1",
    ) -> Self:
        ordered = tuple(sorted(decisions, key=lambda item: item.entry_id))
        snapshot_checksum = catalog_snapshot_checksum or checksum_for(
            {"decisions": [item.to_dict() for item in ordered]}
        )
        payload = {
            "generated_at": datetime_to_json(aware_datetime(generated_at, "gc_plan.generated_at")),
            "decisions": [item.to_dict() for item in ordered],
            "catalog_snapshot_checksum": snapshot_checksum,
            "policy_version": policy_version,
        }
        return cls(
            generated_at=generated_at,
            decisions=ordered,
            plan_checksum=checksum_for(payload),
            catalog_snapshot_checksum=snapshot_checksum,
            policy_version=policy_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime_to_json(self.generated_at),
            "decisions": [item.to_dict() for item in self.decisions],
            "plan_checksum": self.plan_checksum,
            "catalog_snapshot_checksum": self.catalog_snapshot_checksum,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "generated_at",
                    "decisions",
                    "plan_checksum",
                    "catalog_snapshot_checksum",
                    "policy_version",
                }
            ),
            model=cls.__name__,
        )
        return cls(
            generated_at=datetime_from_json(payload["generated_at"], "gc_plan.generated_at"),
            decisions=tuple(
                ArtifactCatalogGcDecision.from_dict(item)
                for item in _mapping_sequence(payload["decisions"], "gc_plan.decisions")
            ),
            plan_checksum=payload["plan_checksum"],
            catalog_snapshot_checksum=payload["catalog_snapshot_checksum"],
            policy_version=payload["policy_version"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactCatalogSnapshot:
    captured_at: datetime
    entries: tuple[ArtifactCatalogEntry, ...]
    claims: tuple[ArtifactCatalogClaim, ...]
    references: tuple[ArtifactLogicalReference, ...]
    snapshot_checksum: str

    def __post_init__(self) -> None:
        captured_at = aware_datetime(self.captured_at, "catalog_snapshot.captured_at")
        entries = tuple(
            sorted(
                _model_tuple(self.entries, ArtifactCatalogEntry, "catalog_snapshot.entries"),
                key=lambda item: item.entry_id,
            )
        )
        claims = tuple(
            sorted(
                _model_tuple(self.claims, ArtifactCatalogClaim, "catalog_snapshot.claims"),
                key=lambda item: item.claim_id,
            )
        )
        references = tuple(
            sorted(
                _model_tuple(
                    self.references,
                    ArtifactLogicalReference,
                    "catalog_snapshot.references",
                ),
                key=lambda item: item.reference_id,
            )
        )
        entry_ids = {item.entry_id for item in entries}
        if any(item.entry_id not in entry_ids for item in (*claims, *references)):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT,
                field="catalog_snapshot.ownership",
            )
        expected = checksum_for(
            {
                "entries": [item.to_dict() for item in entries],
                "claims": [item.to_dict() for item in claims],
                "references": [item.to_dict() for item in references],
            }
        )
        if checksum(self.snapshot_checksum, "catalog_snapshot.snapshot_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="catalog_snapshot.snapshot_checksum",
            )
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "snapshot_checksum", expected)

    @classmethod
    def create(
        cls,
        *,
        captured_at: datetime,
        entries: Sequence[ArtifactCatalogEntry],
        claims: Sequence[ArtifactCatalogClaim],
        references: Sequence[ArtifactLogicalReference],
    ) -> Self:
        ordered_entries = tuple(sorted(entries, key=lambda item: item.entry_id))
        ordered_claims = tuple(sorted(claims, key=lambda item: item.claim_id))
        ordered_references = tuple(
            sorted(references, key=lambda item: item.reference_id)
        )
        return cls(
            captured_at=captured_at,
            entries=ordered_entries,
            claims=ordered_claims,
            references=ordered_references,
            snapshot_checksum=checksum_for(
                {
                    "entries": [item.to_dict() for item in ordered_entries],
                    "claims": [item.to_dict() for item in ordered_claims],
                    "references": [item.to_dict() for item in ordered_references],
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": datetime_to_json(self.captured_at),
            "entries": [item.to_dict() for item in self.entries],
            "claims": [item.to_dict() for item in self.claims],
            "references": [item.to_dict() for item in self.references],
            "snapshot_checksum": self.snapshot_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {"captured_at", "entries", "claims", "references", "snapshot_checksum"}
            ),
            model=cls.__name__,
        )
        return cls(
            captured_at=datetime_from_json(
                payload["captured_at"],
                "catalog_snapshot.captured_at",
            ),
            entries=tuple(
                ArtifactCatalogEntry.from_dict(item)
                for item in _mapping_sequence(payload["entries"], "catalog_snapshot.entries")
            ),
            claims=tuple(
                ArtifactCatalogClaim.from_dict(item)
                for item in _mapping_sequence(payload["claims"], "catalog_snapshot.claims")
            ),
            references=tuple(
                ArtifactLogicalReference.from_dict(item)
                for item in _mapping_sequence(
                    payload["references"],
                    "catalog_snapshot.references",
                )
            ),
            snapshot_checksum=payload["snapshot_checksum"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactLifecycleAuthorization:
    authorization_id: str
    kind: ArtifactLifecycleAuthorityKind
    tenant_id: str
    owner_run_id: str
    owner_id: str
    lifecycle_ref: str
    observed_at: datetime
    policy_version: str
    authorization_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            enum_value(ArtifactLifecycleAuthorityKind, self.kind, "lifecycle.kind"),
        )
        for field_name in ("tenant_id", "owner_run_id", "owner_id"):
            object.__setattr__(
                self,
                field_name,
                identifier(getattr(self, field_name), f"lifecycle.{field_name}"),
            )
        object.__setattr__(
            self,
            "lifecycle_ref",
            reference(self.lifecycle_ref, "lifecycle.lifecycle_ref"),
        )
        object.__setattr__(
            self,
            "observed_at",
            aware_datetime(self.observed_at, "lifecycle.observed_at"),
        )
        object.__setattr__(
            self,
            "policy_version",
            exact_reference(self.policy_version, "lifecycle.policy_version"),
        )
        projection = self.identity_projection()
        expected_id = _derived_reference("catalog-lifecycle", projection)
        if reference(self.authorization_id, "lifecycle.authorization_id") != expected_id:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="lifecycle.authorization_id",
            )
        expected_checksum = checksum_for(
            {"authorization_id": expected_id, **projection}
        )
        if checksum(
            self.authorization_checksum,
            "lifecycle.authorization_checksum",
        ) != expected_checksum:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="lifecycle.authorization_checksum",
            )
        object.__setattr__(self, "authorization_id", expected_id)
        object.__setattr__(self, "authorization_checksum", expected_checksum)

    @classmethod
    def create(cls, **values: Any) -> Self:
        projection = _lifecycle_authorization_projection(values)
        authorization_id = _derived_reference("catalog-lifecycle", projection)
        return cls(
            **values,
            authorization_id=authorization_id,
            authorization_checksum=checksum_for(
                {"authorization_id": authorization_id, **projection}
            ),
        )

    def identity_projection(self) -> dict[str, Any]:
        return _lifecycle_authorization_projection(
            {
                "kind": self.kind,
                "tenant_id": self.tenant_id,
                "owner_run_id": self.owner_run_id,
                "owner_id": self.owner_id,
                "lifecycle_ref": self.lifecycle_ref,
                "observed_at": self.observed_at,
                "policy_version": self.policy_version,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            **self.identity_projection(),
            "authorization_checksum": self.authorization_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "authorization_id",
                    "kind",
                    "tenant_id",
                    "owner_run_id",
                    "owner_id",
                    "lifecycle_ref",
                    "observed_at",
                    "policy_version",
                    "authorization_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["observed_at"] = datetime_from_json(
            payload["observed_at"],
            "lifecycle.observed_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactReferenceRetirementRequest:
    reference: ArtifactLogicalReference
    authorization: ArtifactLifecycleAuthorization
    reason: ArtifactReferenceRetirementReason
    requested_at: datetime
    request_checksum: str

    def __post_init__(self) -> None:
        _require_type(self.reference, ArtifactLogicalReference, "retirement.reference")
        _require_type(
            self.authorization,
            ArtifactLifecycleAuthorization,
            "retirement.authorization",
        )
        object.__setattr__(
            self,
            "reason",
            enum_value(ArtifactReferenceRetirementReason, self.reason, "retirement.reason"),
        )
        object.__setattr__(
            self,
            "requested_at",
            aware_datetime(self.requested_at, "retirement.requested_at"),
        )
        if (
            self.reference.tenant_id != self.authorization.tenant_id
            or self.reference.owner_run_id != self.authorization.owner_run_id
            or self.reference.owner_id != self.authorization.owner_id
            or self.requested_at < self.authorization.observed_at
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="retirement.authorization",
            )
        if (
            self.authorization.kind is ArtifactLifecycleAuthorityKind.TERMINAL_RUN
            and self.reference.kind
            not in {
                ArtifactReferenceKind.RUN,
                ArtifactReferenceKind.EVIDENCE,
                ArtifactReferenceKind.REPLAY,
            }
        ) or (
            self.authorization.kind
            is ArtifactLifecycleAuthorityKind.PUBLICATION_RETIRED
            and self.reference.kind
            not in {ArtifactReferenceKind.REPORT, ArtifactReferenceKind.PUBLICATION}
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT,
                field="retirement.reference.kind",
            )
        expected_reason = (
            ArtifactReferenceRetirementReason.RETENTION_EXPIRED
            if self.authorization.kind is ArtifactLifecycleAuthorityKind.TERMINAL_RUN
            else ArtifactReferenceRetirementReason.PUBLICATION_RETIRED
        )
        if self.reason is not expected_reason:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_REFERENCE_CONFLICT,
                field="retirement.reason",
            )
        expected = checksum_for(self.checksum_projection())
        if checksum(self.request_checksum, "retirement.request_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="retirement.request_checksum",
            )
        object.__setattr__(self, "request_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(
            **values,
            request_checksum=checksum_for(_retirement_request_projection(values)),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return _retirement_request_projection(
            {
                "reference": self.reference,
                "authorization": self.authorization,
                "reason": self.reason,
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
                {"reference", "authorization", "reason", "requested_at", "request_checksum"}
            ),
            model=cls.__name__,
        )
        payload["reference"] = ArtifactLogicalReference.from_dict(payload["reference"])
        payload["authorization"] = ArtifactLifecycleAuthorization.from_dict(
            payload["authorization"]
        )
        payload["requested_at"] = datetime_from_json(
            payload["requested_at"],
            "retirement.requested_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactReferenceRetirementReceipt:
    request_checksum: str
    reference: ArtifactLogicalReference
    authorization_id: str
    reason: ArtifactReferenceRetirementReason
    retired_at: datetime
    receipt_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_checksum",
            checksum(self.request_checksum, "retirement_receipt.request_checksum"),
        )
        _require_type(self.reference, ArtifactLogicalReference, "retirement_receipt.reference")
        object.__setattr__(
            self,
            "authorization_id",
            reference(self.authorization_id, "retirement_receipt.authorization_id"),
        )
        object.__setattr__(
            self,
            "reason",
            enum_value(
                ArtifactReferenceRetirementReason,
                self.reason,
                "retirement_receipt.reason",
            ),
        )
        object.__setattr__(
            self,
            "retired_at",
            aware_datetime(self.retired_at, "retirement_receipt.retired_at"),
        )
        expected = checksum_for(self.checksum_projection())
        if checksum(self.receipt_checksum, "retirement_receipt.receipt_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="retirement_receipt.receipt_checksum",
            )
        object.__setattr__(self, "receipt_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(
            **values,
            receipt_checksum=checksum_for(_retirement_receipt_projection(values)),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return _retirement_receipt_projection(
            {
                "request_checksum": self.request_checksum,
                "reference": self.reference,
                "authorization_id": self.authorization_id,
                "reason": self.reason,
                "retired_at": self.retired_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "request_checksum",
                    "reference",
                    "authorization_id",
                    "reason",
                    "retired_at",
                    "receipt_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["reference"] = ArtifactLogicalReference.from_dict(payload["reference"])
        payload["retired_at"] = datetime_from_json(
            payload["retired_at"],
            "retirement_receipt.retired_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogGcDetachRequest:
    plan_checksum: str
    catalog_snapshot_checksum: str
    decision: ArtifactCatalogGcDecision
    requested_at: datetime
    request_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_checksum", checksum(self.plan_checksum, "gc_detach.plan_checksum"))
        object.__setattr__(
            self,
            "catalog_snapshot_checksum",
            checksum(self.catalog_snapshot_checksum, "gc_detach.catalog_snapshot_checksum"),
        )
        _require_type(self.decision, ArtifactCatalogGcDecision, "gc_detach.decision")
        if self.decision.action is not ArtifactCatalogGcAction.DELETE_CANDIDATE:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="gc_detach.decision.action",
            )
        object.__setattr__(
            self,
            "requested_at",
            aware_datetime(self.requested_at, "gc_detach.requested_at"),
        )
        expected = checksum_for(self.checksum_projection())
        if checksum(self.request_checksum, "gc_detach.request_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="gc_detach.request_checksum",
            )
        object.__setattr__(self, "request_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(
            **values,
            request_checksum=checksum_for(_gc_detach_request_projection(values)),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return _gc_detach_request_projection(
            {
                "plan_checksum": self.plan_checksum,
                "catalog_snapshot_checksum": self.catalog_snapshot_checksum,
                "decision": self.decision,
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
                    "plan_checksum",
                    "catalog_snapshot_checksum",
                    "decision",
                    "requested_at",
                    "request_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["decision"] = ArtifactCatalogGcDecision.from_dict(payload["decision"])
        payload["requested_at"] = datetime_from_json(
            payload["requested_at"],
            "gc_detach.requested_at",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactCatalogGcDetachReceipt:
    request_checksum: str
    entry: ArtifactCatalogEntry
    claims: tuple[ArtifactCatalogClaim, ...]
    references: tuple[ArtifactLogicalReference, ...]
    detached_at: datetime
    receipt_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_checksum",
            checksum(self.request_checksum, "gc_detach_receipt.request_checksum"),
        )
        _require_type(self.entry, ArtifactCatalogEntry, "gc_detach_receipt.entry")
        claims = tuple(
            sorted(
                _model_tuple(self.claims, ArtifactCatalogClaim, "gc_detach_receipt.claims"),
                key=lambda item: item.claim_id,
            )
        )
        references = tuple(
            sorted(
                _model_tuple(
                    self.references,
                    ArtifactLogicalReference,
                    "gc_detach_receipt.references",
                ),
                key=lambda item: item.reference_id,
            )
        )
        if any(item.entry_id != self.entry.entry_id for item in (*claims, *references)):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="gc_detach_receipt.ownership",
            )
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "references", references)
        object.__setattr__(
            self,
            "detached_at",
            aware_datetime(self.detached_at, "gc_detach_receipt.detached_at"),
        )
        expected = checksum_for(self.checksum_projection())
        if checksum(self.receipt_checksum, "gc_detach_receipt.receipt_checksum") != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="gc_detach_receipt.receipt_checksum",
            )
        object.__setattr__(self, "receipt_checksum", expected)

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(
            **values,
            receipt_checksum=checksum_for(_gc_detach_receipt_projection(values)),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return _gc_detach_receipt_projection(
            {
                "request_checksum": self.request_checksum,
                "entry": self.entry,
                "claims": self.claims,
                "references": self.references,
                "detached_at": self.detached_at,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_checksum": self.receipt_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "request_checksum",
                    "entry",
                    "claims",
                    "references",
                    "detached_at",
                    "receipt_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["entry"] = ArtifactCatalogEntry.from_dict(payload["entry"])
        payload["claims"] = tuple(
            ArtifactCatalogClaim.from_dict(item)
            for item in _mapping_sequence(payload["claims"], "gc_detach_receipt.claims")
        )
        payload["references"] = tuple(
            ArtifactLogicalReference.from_dict(item)
            for item in _mapping_sequence(
                payload["references"],
                "gc_detach_receipt.references",
            )
        )
        payload["detached_at"] = datetime_from_json(
            payload["detached_at"],
            "gc_detach_receipt.detached_at",
        )
        return cls(**payload)


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


def _lifecycle_authorization_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": ArtifactLifecycleAuthorityKind(values["kind"]).value,
        "tenant_id": values["tenant_id"],
        "owner_run_id": values["owner_run_id"],
        "owner_id": values["owner_id"],
        "lifecycle_ref": values["lifecycle_ref"],
        "observed_at": datetime_to_json(values["observed_at"]),
        "policy_version": values["policy_version"],
    }


def _retirement_request_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    logical_reference = values["reference"]
    authorization = values["authorization"]
    return {
        "reference": (
            logical_reference.to_dict()
            if isinstance(logical_reference, ArtifactLogicalReference)
            else logical_reference
        ),
        "authorization": (
            authorization.to_dict()
            if isinstance(authorization, ArtifactLifecycleAuthorization)
            else authorization
        ),
        "reason": ArtifactReferenceRetirementReason(values["reason"]).value,
        "requested_at": datetime_to_json(values["requested_at"]),
    }


def _retirement_receipt_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    logical_reference = values["reference"]
    return {
        "request_checksum": values["request_checksum"],
        "reference": (
            logical_reference.to_dict()
            if isinstance(logical_reference, ArtifactLogicalReference)
            else logical_reference
        ),
        "authorization_id": values["authorization_id"],
        "reason": ArtifactReferenceRetirementReason(values["reason"]).value,
        "retired_at": datetime_to_json(values["retired_at"]),
    }


def _gc_detach_request_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    decision = values["decision"]
    return {
        "plan_checksum": values["plan_checksum"],
        "catalog_snapshot_checksum": values["catalog_snapshot_checksum"],
        "decision": (
            decision.to_dict()
            if isinstance(decision, ArtifactCatalogGcDecision)
            else decision
        ),
        "requested_at": datetime_to_json(values["requested_at"]),
    }


def _gc_detach_receipt_projection(values: Mapping[str, Any]) -> dict[str, Any]:
    entry = values["entry"]
    claims = tuple(sorted(values["claims"], key=lambda item: item.claim_id))
    references = tuple(
        sorted(values["references"], key=lambda item: item.reference_id)
    )
    return {
        "request_checksum": values["request_checksum"],
        "entry": entry.to_dict() if isinstance(entry, ArtifactCatalogEntry) else entry,
        "claims": [
            item.to_dict() if isinstance(item, ArtifactCatalogClaim) else item
            for item in claims
        ],
        "references": [
            item.to_dict() if isinstance(item, ArtifactLogicalReference) else item
            for item in references
        ],
        "detached_at": datetime_to_json(values["detached_at"]),
    }


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
    "ArtifactCatalogGcDetachReceipt",
    "ArtifactCatalogGcDetachRequest",
    "ArtifactCatalogIdentity",
    "ArtifactCatalogReconciliationIssue",
    "ArtifactCatalogReconciliationIssueKind",
    "ArtifactCatalogReconciliationPlan",
    "ArtifactCatalogRegistrationRequest",
    "ArtifactCatalogRegistrationResult",
    "ArtifactCatalogSnapshot",
    "ArtifactLifecycleAuthorization",
    "ArtifactLifecycleAuthorityKind",
    "ArtifactLogicalReference",
    "ArtifactReferenceKind",
    "ArtifactReferenceRetirementReason",
    "ArtifactReferenceRetirementReceipt",
    "ArtifactReferenceRetirementRequest",
    "ArtifactVerificationReceipt",
]
