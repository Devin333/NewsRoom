from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ResearchRunStoreReason(str, Enum):
    """Allow-listed diagnostics that are safe to expose across interfaces."""

    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_RECORD = "invalid_record"
    SERIALIZATION_FAILED = "serialization_failed"
    RECORD_TOO_LARGE = "record_too_large"
    IDENTITY_MISMATCH = "identity_mismatch"
    IDENTITY_CONFLICT = "identity_conflict"
    SCHEMA_INVALID = "schema_invalid"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    CHECKSUM_INVALID = "checksum_invalid"
    CONTENT_INVALID = "content_invalid"
    FILESYSTEM_UNAVAILABLE = "filesystem_unavailable"
    LOCK_UNAVAILABLE = "lock_unavailable"
    ATOMIC_COMMIT_FAILED = "atomic_commit_failed"


class ResearchRunStoreError(RuntimeError):
    """Base run-store error with a stable, sanitized public projection."""

    code = "research_run_store_error"
    public_message = "Research run storage operation failed."
    retryable = False

    def __init__(self, reason: ResearchRunStoreReason) -> None:
        if not isinstance(reason, ResearchRunStoreReason):
            raise TypeError("reason must be a ResearchRunStoreReason")
        self.reason = reason
        super().__init__(self.public_message)

    @property
    def reason_code(self) -> str:
        return self.reason.value

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.public_message,
            "reason": self.reason_code,
            "retryable": self.retryable,
        }


class ResearchRunStoreValidationError(ResearchRunStoreError, ValueError):
    """A caller supplied a run record or store option that is not valid."""

    code = "research_run_store_invalid"
    public_message = "Research run storage input is invalid."


class ResearchRunStoreConflictError(ResearchRunStoreError):
    """An immutable run identity was reused for different content or scope."""

    code = "research_run_store_conflict"
    public_message = "Research run storage identity conflicts with committed data."


class ResearchRunStoreCorruptionError(ResearchRunStoreError):
    """Persisted run data failed schema, identity, or integrity validation."""

    code = "research_run_store_corrupt"
    public_message = "Research run storage data failed integrity validation."


class ResearchRunStoreUnavailableError(ResearchRunStoreError):
    """The durable filesystem boundary could not complete an operation."""

    code = "research_run_store_unavailable"
    public_message = "Research run storage is temporarily unavailable."
    retryable = True


@dataclass(frozen=True)
class ResearchRunRecord:
    run_id: str
    paper_id: str
    result: Any


@runtime_checkable
class ResearchRunStore(Protocol):
    def save(self, record: ResearchRunRecord) -> None: ...

    def get_by_run_id(self, run_id: str) -> ResearchRunRecord | None: ...

    def get_latest_by_paper_id(self, paper_id: str) -> ResearchRunRecord | None: ...

    def list_by_paper_id(self, paper_id: str) -> list[ResearchRunRecord]: ...


__all__ = [
    "ResearchRunRecord",
    "ResearchRunStore",
    "ResearchRunStoreConflictError",
    "ResearchRunStoreCorruptionError",
    "ResearchRunStoreError",
    "ResearchRunStoreReason",
    "ResearchRunStoreUnavailableError",
    "ResearchRunStoreValidationError",
]
