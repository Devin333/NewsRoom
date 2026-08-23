"""Graph-only identity helpers for the Harness control plane.

Durable orchestration transitions are owned by ``graph_runtime``.  This module
is intentionally limited to immutable Graph identity/checksum helpers; the
retired flat state projection and transition reader are no longer part of
the production import graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.state import HarnessRunSpec, run_spec_checksum
from framework.harness.graph.model import NormalizedHarnessGraph
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_GRAPH_CONTROL_POLICY_VERSION,
    HARNESS_GRAPH_REDUCER_VERSION,
    HARNESS_GRAPH_RUNTIME_VERSION,
)


HARNESS_GRAPH_HISTORY_SCHEMA = "newsroom.harness-graph-control-commit/v1"
HARNESS_GRAPH_PROJECTION_HISTORY_SCHEMA = (
    "newsroom.harness-graph-projection-record/v1"
)
HARNESS_GRAPH_EVENT_SOURCE = "io.newsroom.harness.graph-control-plane"


@dataclass(frozen=True, slots=True)
class HarnessGraphIdentity:
    """The exact identity bound to every live Graph replay operation."""

    graph_id: str
    graph_version: str
    graph_checksum: str
    definition_checksum: str

    def __post_init__(self) -> None:
        for field_name in (
            "graph_id",
            "graph_version",
            "graph_checksum",
            "definition_checksum",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)

    @property
    def identity_version(self) -> str:
        return f"{self.graph_id}@{self.graph_version}"

    def to_dict(self) -> dict[str, str]:
        return {
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_checksum": self.graph_checksum,
            "definition_checksum": self.definition_checksum,
        }


def graph_identity(value: Any) -> HarnessGraphIdentity:
    """Return the canonical identity for a normalized Graph or Graph reference."""

    if isinstance(value, NormalizedHarnessGraph):
        reference = value.graph_ref
        if value.schema_version != GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            raise ValueError("legacy normalized Graph identity is not admitted")
        if reference is None or value.definition_checksum is None:
            raise ValueError("Graph identity is incomplete")
        return HarnessGraphIdentity(
            graph_id=value.graph_id,
            graph_version=value.identity_version,
            graph_checksum=value.checksum,
            definition_checksum=value.definition_checksum,
        )
    if isinstance(value, HarnessGraphReference):
        if value.graph_ref is None:
            raise ValueError("legacy Graph reference is not admitted")
        return HarnessGraphIdentity(
            graph_id=value.graph_id,
            graph_version=value.identity_version,
            graph_checksum=value.checksum,
            definition_checksum=value.checksum,
        )
    # HarnessRunSpec carries the immutable Graph definition before compilation.
    # Bind it by its own version/checksum; no legacy orchestration projection is
    # consulted at this boundary.
    if all(hasattr(value, name) for name in ("graph_id", "graph_version", "definition_checksum", "to_dict")):
        definition_checksum = str(value.definition_checksum)
        return HarnessGraphIdentity(
            graph_id=str(value.graph_id),
            graph_version=str(value.graph_version),
            graph_checksum=checksum_for(value.to_dict()),
            definition_checksum=definition_checksum,
        )
    raise TypeError("value must be a normalized Graph or Graph reference")


def graph_run_spec_identity(run_spec: HarnessRunSpec) -> HarnessGraphIdentity:
    """Bind a run specification to its Graph identity without projecting state."""

    if not isinstance(run_spec, HarnessRunSpec):
        raise TypeError("run_spec must be HarnessRunSpec")
    return graph_identity(run_spec.graph)


def initial_graph_state_checksum(run_spec: HarnessRunSpec) -> str:
    """Checksum the immutable Graph identity used by a newly admitted run."""

    identity = graph_run_spec_identity(run_spec)
    return checksum_for(
        {
            "run_id": run_spec.run_id,
            "run_spec_checksum": run_spec_checksum(run_spec),
            "graph_identity": identity.to_dict(),
        }
    )


__all__ = [
    "HARNESS_GRAPH_CONTROL_POLICY_VERSION",
    "HARNESS_GRAPH_EVENT_SOURCE",
    "HARNESS_GRAPH_HISTORY_SCHEMA",
    "HARNESS_GRAPH_PROJECTION_HISTORY_SCHEMA",
    "HARNESS_GRAPH_REDUCER_VERSION",
    "HARNESS_GRAPH_RUNTIME_VERSION",
    "HarnessGraphIdentity",
    "graph_identity",
    "graph_run_spec_identity",
    "initial_graph_state_checksum",
    "run_spec_checksum",
]
