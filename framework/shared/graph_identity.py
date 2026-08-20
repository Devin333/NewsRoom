"""Graph-only identity shared by framework-level orchestration carriers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+@/-]{0,511}\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})


@dataclass(frozen=True, slots=True)
class GraphStageIdentity:
    """Exact Graph node-instance identity without an activity attempt."""

    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str
    node_id: str
    node_instance_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "graph_id",
            "graph_version",
            "node_id",
            "node_instance_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.graph_version.casefold() in _MOVING_VERSIONS:
            raise ValueError("graph_version must be exact")
        graph_ref = _required_text(self.graph_ref, "graph_ref")
        if graph_ref != f"{self.graph_id}@{self.graph_version}":
            raise ValueError("graph_ref must match graph_id and graph_version")
        checksum = _required_text(self.graph_checksum, "graph_checksum")
        if _CHECKSUM.fullmatch(checksum) is None:
            raise ValueError("graph_checksum must be a sha256 checksum")
        object.__setattr__(self, "graph_ref", graph_ref)
        object.__setattr__(self, "graph_checksum", checksum)

    @property
    def run_identity(self) -> "GraphRunIdentity":
        return GraphRunIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphStageIdentity":
        if not isinstance(value, Mapping):
            raise TypeError("graph_stage_identity must be an object")
        expected = {
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "node_id",
            "node_instance_id",
        }
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        if unknown:
            raise ValueError(f"graph_stage_identity contains unknown fields: {unknown}")
        if missing:
            raise ValueError(f"graph_stage_identity is missing fields: {missing}")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class GraphExecutionIdentity:
    """Exact physical Graph activity identity for active execution records."""

    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str
    node_id: str
    node_instance_id: str
    activity_id: str
    attempt: int

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "graph_id",
            "graph_version",
            "node_id",
            "node_instance_id",
            "activity_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if self.graph_version.casefold() in _MOVING_VERSIONS:
            raise ValueError("graph_version must be exact")
        graph_ref = _required_text(self.graph_ref, "graph_ref")
        if graph_ref != f"{self.graph_id}@{self.graph_version}":
            raise ValueError("graph_ref must match graph_id and graph_version")
        checksum = _required_text(self.graph_checksum, "graph_checksum")
        if _CHECKSUM.fullmatch(checksum) is None:
            raise ValueError("graph_checksum must be a sha256 checksum")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        object.__setattr__(self, "graph_ref", graph_ref)
        object.__setattr__(self, "graph_checksum", checksum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
        }

    @property
    def run_identity(self) -> "GraphRunIdentity":
        return GraphRunIdentity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphExecutionIdentity":
        if not isinstance(value, Mapping):
            raise TypeError("graph_execution_identity must be an object")
        expected = {
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "node_id",
            "node_instance_id",
            "activity_id",
            "attempt",
        }
        unknown = sorted(set(value) - expected)
        missing = sorted(expected - set(value))
        if unknown:
            raise ValueError(f"graph_execution_identity contains unknown fields: {unknown}")
        if missing:
            raise ValueError(f"graph_execution_identity is missing fields: {missing}")
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class GraphRunIdentity:
    """Exact immutable identity for one admitted Graph run."""

    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str

    def __post_init__(self) -> None:
        for field_name in ("run_id", "graph_id", "graph_version"):
            value = _required_text(getattr(self, field_name), field_name)
            if field_name == "graph_version" and value.casefold() in _MOVING_VERSIONS:
                raise ValueError("graph_version must be exact")
            object.__setattr__(self, field_name, value)
        graph_ref = _required_text(self.graph_ref, "graph_ref")
        if graph_ref != f"{self.graph_id}@{self.graph_version}":
            raise ValueError("graph_ref must match graph_id and graph_version")
        checksum = _required_text(self.graph_checksum, "graph_checksum")
        if _CHECKSUM.fullmatch(checksum) is None:
            raise ValueError("graph_checksum must be a sha256 checksum")
        object.__setattr__(self, "graph_ref", graph_ref)
        object.__setattr__(self, "graph_checksum", checksum)

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphRunIdentity":
        if not isinstance(value, Mapping):
            raise TypeError("graph_identity must be an object")
        expected = {
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
        }
        unknown = sorted(set(value) - expected)
        if unknown:
            raise ValueError(f"graph_identity contains unknown fields: {unknown}")
        missing = sorted(expected - set(value))
        if missing:
            raise ValueError(f"graph_identity is missing fields: {missing}")
        return cls(**dict(value))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or _TEXT.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} is invalid")
    return normalized


GraphIdentity = GraphRunIdentity | GraphStageIdentity | GraphExecutionIdentity


def coerce_graph_identity(value: Any) -> GraphIdentity:
    """Hydrate the exact Graph identity variant without accepting mixed fields."""
    if isinstance(value, (GraphRunIdentity, GraphStageIdentity, GraphExecutionIdentity)):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("graph_identity must be a Graph identity object")
    fields = set(value)
    if "activity_id" in fields or "attempt" in fields:
        return GraphExecutionIdentity.from_dict(value)
    if "node_id" in fields or "node_instance_id" in fields:
        return GraphStageIdentity.from_dict(value)
    return GraphRunIdentity.from_dict(value)


__all__ = [
    "GraphExecutionIdentity",
    "GraphIdentity",
    "GraphRunIdentity",
    "GraphStageIdentity",
    "coerce_graph_identity",
]
