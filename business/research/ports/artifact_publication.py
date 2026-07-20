"""Pure Research artifact publication contract identifiers and read claims.

This module intentionally contains no filesystem or Harness implementation.  It
defines the small, immutable evidence projection that an infrastructure reader
hands to the application-owned accepted-run resolver.  Keeping this projection
in the port prevents the adapter from silently treating a boolean ``accepted``
flag as sufficient publication authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

RESEARCH_ARTIFACT_EFFECT_KIND = "research.artifact.bundle"
RESEARCH_ARTIFACT_HANDLER_ID = "research.artifact.bundle"
RESEARCH_ARTIFACT_HANDLER_VERSION = "1"
RESEARCH_ARTIFACT_HANDLER_REF = (
    f"{RESEARCH_ARTIFACT_HANDLER_ID}@{RESEARCH_ARTIFACT_HANDLER_VERSION}"
)
RESEARCH_ARTIFACT_SCHEMA_VERSION = "newsroom.research-artifact-bundle/v1"
RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION = "newsroom.research-artifact-manifest/v1"
RESEARCH_ARTIFACT_MANIFEST_VERSION = "newsroom.research-artifact-manifest/v2"


@dataclass(frozen=True, slots=True)
class ResearchArtifactReadClaim:
    """Immutable evidence presented to the accepted-run resolver.

    ``schema_version`` is ``v2`` for finalized publication manifests and ``v1``
    for a legacy manifest being opened through a dual reader.  Legacy claims
    intentionally carry optional evidence because old bytes are not rewritten;
    the resolver must classify them from the durable run record instead.
    """

    run_id: str
    schema_version: str
    identity_scope_ref: str | None
    subject_scope_ref: str | None
    publication_authority_ref: str | None
    artifact_evidence_ref: str | None
    terminal_side_effect_outcome_ref: str | None
    artifact_refs: tuple[tuple[str, str], ...]
    member_checksums: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ResearchArtifactReadResolution:
    """Application-owned result of resolving a publication read claim.

    A legacy manifest may not carry an identity scope.  In that case a plain
    boolean resolver result is intentionally insufficient: only an
    application resolver that checked the strict v1 Research run record may
    provide the missing scope evidence here.  For v2 claims the field normally
    mirrors the claim's persisted scope.
    """

    accepted: bool
    identity_scope_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be bool")
        if self.identity_scope_ref is not None and (
            not isinstance(self.identity_scope_ref, str)
            or not self.identity_scope_ref.strip()
        ):
            raise ValueError("identity_scope_ref must be a non-empty string")


@runtime_checkable
class ResearchArtifactDiagnosticReader(Protocol):
    """Read-only port for explicitly scoped non-canonical artifact bytes."""

    def read_diagnostic_artifact(
        self,
        ref: str,
        *,
        identity_scope_ref: str,
        subject_scope_ref: str | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ResearchArtifactDiagnosticClaim:
    """Scope-bound request for a non-canonical artifact diagnostic read."""

    run_id: str
    schema_version: str
    disposition: str
    identity_scope_ref: str
    subject_scope_ref: str | None
    artifact_type: str


def artifact_evidence_ref(artifact_refs: Mapping[str, str]) -> str:
    """Return the canonical checksum used by Research run disposition.

    This intentionally matches ``framework.events.canonical.checksum_for``
    without importing framework code into the business port.
    """

    return _checksum_for({"artifact_refs": dict(artifact_refs)})


def artifact_member_evidence_ref(
    members: Sequence[Mapping[str, Any]],
) -> str:
    """Return a stable checksum over published member integrity metadata."""

    projection = sorted(
        (
            {
                "artifact_type": str(member["artifact_type"]),
                "artifact_ref": str(member["artifact_ref"]),
                "path": str(member["path"]),
                "checksum": str(member["checksum"]),
                "size_bytes": int(member["size_bytes"]),
                "content_type": str(member["content_type"]),
            }
            for member in members
        ),
        key=lambda item: item["artifact_type"],
    )
    return _checksum_for({"members": projection})


def _checksum_for(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


__all__ = [
    "RESEARCH_ARTIFACT_EFFECT_KIND",
    "RESEARCH_ARTIFACT_HANDLER_ID",
    "RESEARCH_ARTIFACT_HANDLER_REF",
    "RESEARCH_ARTIFACT_HANDLER_VERSION",
    "RESEARCH_ARTIFACT_LEGACY_MANIFEST_VERSION",
    "RESEARCH_ARTIFACT_MANIFEST_VERSION",
    "RESEARCH_ARTIFACT_SCHEMA_VERSION",
    "ResearchArtifactDiagnosticClaim",
    "ResearchArtifactDiagnosticReader",
    "ResearchArtifactReadClaim",
    "ResearchArtifactReadResolution",
    "artifact_evidence_ref",
    "artifact_member_evidence_ref",
]
