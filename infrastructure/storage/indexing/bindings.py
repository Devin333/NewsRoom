"""Explicit Graph artifact producer binding projections.

Artifact manifests contain both node-produced members and run/system members.
The latter must never be interpreted as a Graph node merely because the legacy
terminal descriptor has non-empty ``node_id`` or ``attempt_id`` labels.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from framework.events.canonical import checksum_for


GRAPH_ARTIFACT_BINDING_PROJECTION_SCHEMA = (
    "newsroom.graph-artifact-binding-projection/v1"
)
_SHA256_PREFIX = "sha256:"


class GraphArtifactBindingKind(StrEnum):
    NODE = "node"
    SYSTEM = "system"


class GraphArtifactBindingEvidenceSource(StrEnum):
    WORKER_SIDE_EFFECT_INTENT = "worker_side_effect_intent"
    CONTROLLER_TERMINAL_AUTHORITY = "controller_terminal_authority"
    GRAPH_EVENT_PROJECTION = "graph_event_projection"


@dataclass(frozen=True, slots=True)
class GraphArtifactBindingProjection:
    """The explicit producer identity carried by one terminal artifact."""

    artifact_id: str
    kind: GraphArtifactBindingKind | str
    node_id: str | None
    node_instance_id: str | None
    attempt_id: str | None
    evidence_ref: str
    evidence_source: GraphArtifactBindingEvidenceSource | str
    schema_version: str = GRAPH_ARTIFACT_BINDING_PROJECTION_SCHEMA
    binding_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _required_text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "kind", GraphArtifactBindingKind(self.kind))
        object.__setattr__(
            self,
            "evidence_source",
            GraphArtifactBindingEvidenceSource(self.evidence_source),
        )
        object.__setattr__(
            self,
            "evidence_ref",
            _checksum(self.evidence_ref, "evidence_ref"),
        )
        if self.schema_version != GRAPH_ARTIFACT_BINDING_PROJECTION_SCHEMA:
            raise ValueError("unsupported Graph artifact binding projection schema")
        node_id = _optional_text(self.node_id, "node_id")
        node_instance_id = _optional_text(self.node_instance_id, "node_instance_id")
        attempt_id = _optional_text(self.attempt_id, "attempt_id")
        if self.kind is GraphArtifactBindingKind.NODE:
            if node_id is None or node_instance_id is None or attempt_id is None:
                raise ValueError("node Graph artifact binding requires complete node identity")
        elif any(value is not None for value in (node_id, node_instance_id, attempt_id)):
            raise ValueError("system Graph artifact binding cannot carry node identity")
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "node_instance_id", node_instance_id)
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "binding_ref", checksum_for(self.checksum_projection()))

    @classmethod
    def for_node(
        cls,
        *,
        artifact_id: str,
        node_id: str,
        node_instance_id: str,
        attempt_id: str,
        evidence_ref: str,
        evidence_source: GraphArtifactBindingEvidenceSource | str,
    ) -> Self:
        return cls(
            artifact_id=artifact_id,
            kind=GraphArtifactBindingKind.NODE,
            node_id=node_id,
            node_instance_id=node_instance_id,
            attempt_id=attempt_id,
            evidence_ref=evidence_ref,
            evidence_source=evidence_source,
        )

    @classmethod
    def for_system(
        cls,
        *,
        artifact_id: str,
        evidence_ref: str,
        evidence_source: GraphArtifactBindingEvidenceSource | str,
    ) -> Self:
        return cls(
            artifact_id=artifact_id,
            kind=GraphArtifactBindingKind.SYSTEM,
            node_id=None,
            node_instance_id=None,
            attempt_id=None,
            evidence_ref=evidence_ref,
            evidence_source=evidence_source,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt_id": self.attempt_id,
            "evidence_ref": self.evidence_ref,
            "evidence_source": self.evidence_source.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "binding_ref": self.binding_ref}

    def to_node_binding(self) -> Any:
        """Convert only a verified node projection into the legacy writer input."""

        if self.kind is not GraphArtifactBindingKind.NODE:
            raise ValueError("system Graph artifact binding has no node writer input")
        from infrastructure.storage.indexing.contracts import GraphArtifactNodeBinding

        return GraphArtifactNodeBinding(
            artifact_id=self.artifact_id,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            attempt_id=self.attempt_id,
            evidence_ref=self.evidence_ref,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "artifact_id",
                "kind",
                "node_id",
                "node_instance_id",
                "attempt_id",
                "evidence_ref",
                "evidence_source",
                "binding_ref",
            },
            "Graph artifact binding projection",
        )
        projection = cls(
            artifact_id=payload["artifact_id"],
            kind=payload["kind"],
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            attempt_id=payload["attempt_id"],
            evidence_ref=payload["evidence_ref"],
            evidence_source=payload["evidence_source"],
            schema_version=payload["schema_version"],
        )
        if payload["binding_ref"] != projection.binding_ref:
            raise ValueError("Graph artifact binding projection checksum is invalid")
        return projection


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        raise ValueError(f"{field_name} must be a sha256 checksum")
    digest = value.removeprefix(_SHA256_PREFIX)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a sha256 checksum")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty trimmed text")
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _exact_mapping(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{label} fields are invalid")
    return dict(value)


__all__ = [
    "GRAPH_ARTIFACT_BINDING_PROJECTION_SCHEMA",
    "GraphArtifactBindingEvidenceSource",
    "GraphArtifactBindingKind",
    "GraphArtifactBindingProjection",
]
