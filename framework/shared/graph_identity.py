"""Graph-only identity shared by framework-level orchestration carriers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+@/-]{0,511}\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})
CONVERSATION_SCOPE_GRAPH = "graph"
CONVERSATION_SCOPE_STANDALONE = "standalone"


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
class ConversationMessageScope:
    """Discriminated live scope for Graph-bound or standalone messages."""

    scope_kind: str
    graph_identity: GraphExecutionIdentity | None = None
    graph_checkpoint_ref: str | None = None

    def __post_init__(self) -> None:
        if self.scope_kind == CONVERSATION_SCOPE_STANDALONE:
            if self.graph_identity is not None or self.graph_checkpoint_ref is not None:
                raise ValueError("standalone conversation message cannot carry Graph identity")
            return
        if self.scope_kind != CONVERSATION_SCOPE_GRAPH:
            raise ValueError("scope_kind must be 'graph' or 'standalone'")
        if self.graph_identity is None or self.graph_checkpoint_ref is None:
            raise ValueError(
                "Graph message identity requires GraphExecutionIdentity and "
                "graph_checkpoint_ref"
            )
        object.__setattr__(
            self,
            "graph_checkpoint_ref",
            _required_text(self.graph_checkpoint_ref, "graph_checkpoint_ref"),
        )

    @classmethod
    def standalone(cls) -> "ConversationMessageScope":
        return cls(scope_kind=CONVERSATION_SCOPE_STANDALONE)

    @classmethod
    def graph(
        cls,
        identity: GraphExecutionIdentity,
        *,
        graph_checkpoint_ref: str,
    ) -> "ConversationMessageScope":
        return cls(
            scope_kind=CONVERSATION_SCOPE_GRAPH,
            graph_identity=identity,
            graph_checkpoint_ref=graph_checkpoint_ref,
        )

    @classmethod
    def from_message_fields(
        cls,
        *,
        scope_kind: str,
        run_id: Any,
        graph_id: Any,
        graph_version: Any,
        graph_ref: Any,
        graph_checksum: Any,
        node_id: Any,
        node_instance_id: Any,
        graph_checkpoint_ref: Any,
        activity_id: Any,
        attempt: Any,
    ) -> "ConversationMessageScope":
        graph_values = {
            "run_id": run_id,
            "graph_id": graph_id,
            "graph_version": graph_version,
            "graph_ref": graph_ref,
            "graph_checksum": graph_checksum,
            "node_id": node_id,
            "node_instance_id": node_instance_id,
            "activity_id": activity_id,
            "attempt": attempt,
        }
        if scope_kind == CONVERSATION_SCOPE_STANDALONE:
            if any(
                value is not None
                for value in (*graph_values.values(), graph_checkpoint_ref)
            ):
                raise ValueError("standalone conversation message cannot carry Graph identity")
            return cls.standalone()
        if scope_kind != CONVERSATION_SCOPE_GRAPH:
            raise ValueError("scope_kind must be 'graph' or 'standalone'")
        if any(value is None for value in (*graph_values.values(), graph_checkpoint_ref)):
            raise ValueError(
                "Graph message identity requires run_id, graph_id, graph_version, "
                "graph_ref, graph_checksum, node_id, node_instance_id, "
                "graph_checkpoint_ref, activity_id, and attempt"
            )
        identity = GraphExecutionIdentity.from_dict(graph_values)
        for field_name, value in graph_values.items():
            if getattr(identity, field_name) != value:
                raise ValueError(f"{field_name} must be canonical")
        scope = cls.graph(
            identity,
            graph_checkpoint_ref=graph_checkpoint_ref,
        )
        if scope.graph_checkpoint_ref != graph_checkpoint_ref:
            raise ValueError("graph_checkpoint_ref must be canonical")
        return scope

    @property
    def conversation_key(self) -> tuple[str, ...]:
        if self.graph_identity is None:
            return (CONVERSATION_SCOPE_STANDALONE,)
        return (
            CONVERSATION_SCOPE_GRAPH,
            self.graph_identity.run_id,
            self.graph_identity.graph_ref,
            self.graph_identity.graph_checksum,
        )

    def to_message_fields(self) -> dict[str, Any]:
        if self.graph_identity is None:
            return {
                "scope_kind": CONVERSATION_SCOPE_STANDALONE,
                "run_id": None,
                "graph_id": None,
                "graph_version": None,
                "graph_ref": None,
                "graph_checksum": None,
                "node_id": None,
                "node_instance_id": None,
                "graph_checkpoint_ref": None,
                "activity_id": None,
                "attempt": None,
            }
        return {
            "scope_kind": CONVERSATION_SCOPE_GRAPH,
            **self.graph_identity.to_dict(),
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
        }


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
    "CONVERSATION_SCOPE_GRAPH",
    "CONVERSATION_SCOPE_STANDALONE",
    "ConversationMessageScope",
    "GraphExecutionIdentity",
    "GraphIdentity",
    "GraphRunIdentity",
    "GraphStageIdentity",
    "coerce_graph_identity",
]
