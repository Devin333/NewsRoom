from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable


@dataclass(frozen=True)
class ContextEnvelope:
    envelope_id: str
    stable_prefix: dict[str, Any] = field(default_factory=dict)
    dynamic_tail: dict[str, Any] = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.envelope_id).strip():
            raise HarnessValidationError("envelope_id is required")
        if self.token_estimate < 0:
            raise HarnessValidationError("token_estimate must not be negative")
        stable_json_dumps(self.stable_prefix)
        stable_json_dumps(self.dynamic_tail)
        object.__setattr__(self, "envelope_id", str(self.envelope_id))
        object.__setattr__(self, "stable_prefix", dict(self.stable_prefix))
        object.__setattr__(self, "dynamic_tail", dict(self.dynamic_tail))
        object.__setattr__(self, "artifact_refs", tuple(str(ref) for ref in self.artifact_refs))
        object.__setattr__(self, "memory_refs", tuple(str(ref) for ref in self.memory_refs))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in self.evidence_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "stable_prefix": to_jsonable(self.stable_prefix),
            "dynamic_tail": to_jsonable(self.dynamic_tail),
            "artifact_refs": list(self.artifact_refs),
            "memory_refs": list(self.memory_refs),
            "evidence_refs": list(self.evidence_refs),
            "token_estimate": self.token_estimate,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    snapshot_id: str
    envelope_id: str
    refs: tuple[str, ...]
    token_estimate: int
    cache_key: str
    checksum: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.snapshot_id).strip():
            raise HarnessValidationError("snapshot_id is required")
        if not str(self.envelope_id).strip():
            raise HarnessValidationError("envelope_id is required")
        if not self.refs:
            raise HarnessValidationError("ContextSnapshot must store refs instead of large payloads")
        if self.token_estimate < 0:
            raise HarnessValidationError("token_estimate must not be negative")
        if not str(self.cache_key).strip():
            raise HarnessValidationError("cache_key is required")
        if not str(self.checksum).strip():
            raise HarnessValidationError("checksum is required")
        object.__setattr__(self, "refs", tuple(str(ref) for ref in self.refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "envelope_id": self.envelope_id,
            "refs": list(self.refs),
            "token_estimate": self.token_estimate,
            "cache_key": self.cache_key,
            "checksum": self.checksum,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class ContextCompressionSummary:
    summary_id: str
    source_envelope_id: str
    summary_ref: str
    token_estimate_before: int
    token_estimate_after: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.summary_id).strip():
            raise HarnessValidationError("summary_id is required")
        if not str(self.source_envelope_id).strip():
            raise HarnessValidationError("source_envelope_id is required")
        if not str(self.summary_ref).strip():
            raise HarnessValidationError("summary_ref is required")
        if self.token_estimate_before < 0 or self.token_estimate_after < 0:
            raise HarnessValidationError("token estimates must not be negative")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "source_envelope_id": self.source_envelope_id,
            "summary_ref": self.summary_ref,
            "token_estimate_before": self.token_estimate_before,
            "token_estimate_after": self.token_estimate_after,
            "metadata": to_jsonable(self.metadata),
        }


__all__ = ["ContextCompressionSummary", "ContextEnvelope", "ContextSnapshot"]
