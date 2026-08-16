from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.canonical import required_text
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    NormalizedHarnessGraph,
)
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HarnessGraphReference:
    """Exact normalized Graph identity shared by Graph runtime contracts."""

    graph_id: str
    workflow_ref: HarnessContractReference | None
    schema_version: str
    compiler_version: str
    condition_policy_version: str
    checksum: str
    graph_ref: HarnessContractReference | None = None

    def __post_init__(self) -> None:
        graph_id = required_text(self.graph_id, "graph_ref.graph_id")
        schema_version = required_text(
            self.schema_version,
            "graph_ref.schema_version",
        )
        workflow_ref = self.workflow_ref
        graph_ref = self.graph_ref
        if schema_version == NORMALIZED_HARNESS_GRAPH_SCHEMA:
            if not isinstance(workflow_ref, HarnessContractReference):
                raise TypeError("workflow_ref must be HarnessContractReference")
            if workflow_ref.contract_kind is not HarnessContractKind.WORKFLOW:
                raise HarnessValidationError(
                    "legacy graph reference must use legacy orchestration contract kind",
                    code="graph_state_contract_kind_mismatch",
                )
            if graph_ref is not None:
                raise HarnessValidationError(
                    "legacy graph reference cannot carry Graph-only identity",
                    code="graph_state_identity_schema_mismatch",
                )
        elif schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            if workflow_ref is not None:
                raise HarnessValidationError(
                    "Graph-only reference cannot carry legacy orchestration identity",
                    code="legacy_graph_identity_forbidden",
                )
            if not isinstance(graph_ref, HarnessContractReference):
                raise TypeError("graph_ref must be HarnessContractReference")
            if graph_ref.contract_kind is not HarnessContractKind.GRAPH:
                raise HarnessValidationError(
                    "Graph-only reference must use Graph contract kind",
                    code="graph_state_contract_kind_mismatch",
                )
            if graph_ref.contract_id != graph_id:
                raise HarnessValidationError(
                    "Graph-only reference does not match graph_id",
                    code="graph_state_graph_identity_mismatch",
                )
        else:
            raise HarnessValidationError(
                "unsupported normalized graph reference schema",
                code="unsupported_graph_reference_schema",
                details={"schema_version": schema_version},
            )
        compiler_version = required_text(
            self.compiler_version,
            "graph_ref.compiler_version",
        )
        expected_compiler_version = (
            HARNESS_GRAPH_ONLY_COMPILER_VERSION
            if schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
            else HARNESS_GRAPH_COMPILER_VERSION
        )
        if compiler_version != expected_compiler_version:
            raise HarnessValidationError(
                "graph reference uses an unsupported compiler version",
                code="unsupported_graph_compiler",
                details={"compiler_version": compiler_version},
            )
        condition_policy_version = required_text(
            self.condition_policy_version,
            "graph_ref.condition_policy_version",
        )
        if condition_policy_version != HARNESS_CONDITION_POLICY_VERSION:
            raise HarnessValidationError(
                "graph reference uses an unsupported condition policy version",
                code="unsupported_condition_policy",
                details={"condition_policy_version": condition_policy_version},
            )
        object.__setattr__(self, "graph_id", graph_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "compiler_version", compiler_version)
        object.__setattr__(
            self,
            "condition_policy_version",
            condition_policy_version,
        )
        object.__setattr__(
            self,
            "checksum",
            _checksum(self.checksum, "graph_ref.checksum"),
        )

    @classmethod
    def from_graph(cls, graph: NormalizedHarnessGraph) -> "HarnessGraphReference":
        if not isinstance(graph, NormalizedHarnessGraph):
            raise TypeError("graph must be NormalizedHarnessGraph")
        return cls(
            graph_id=graph.graph_id,
            workflow_ref=graph.workflow_ref,
            schema_version=graph.schema_version,
            compiler_version=graph.compiler_version,
            condition_policy_version=graph.condition_policy_version,
            checksum=graph.checksum,
            graph_ref=graph.graph_ref,
        )

    @property
    def identity_ref(self) -> HarnessContractReference:
        reference = self.graph_ref or self.workflow_ref
        if reference is None:  # pragma: no cover - constructor invariant
            raise AssertionError("graph reference identity is unavailable")
        return reference

    @property
    def identity_version(self) -> str:
        return self.identity_ref.version

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "graph_id": self.graph_id,
            "schema_version": self.schema_version,
            "compiler_version": self.compiler_version,
            "condition_policy_version": self.condition_policy_version,
            "checksum": self.checksum,
        }
        if self.schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA:
            assert self.graph_ref is not None
            payload["graph_ref"] = self.graph_ref.to_dict()
        else:
            assert self.workflow_ref is not None
            payload["workflow_ref"] = self.workflow_ref.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HarnessGraphReference":
        if not isinstance(value, Mapping):
            raise HarnessValidationError(
                "graph reference must be an object",
                code="invalid_graph_state_projection",
            )
        schema_version = value.get("schema_version")
        identity_field = (
            "graph_ref"
            if schema_version == GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA
            else "workflow_ref"
        )
        _exact_keys(
            value,
            {
                "graph_id",
                identity_field,
                "schema_version",
                "compiler_version",
                "condition_policy_version",
                "checksum",
            },
            "graph reference",
        )
        return cls(
            graph_id=value["graph_id"],
            workflow_ref=(
                None
                if identity_field == "graph_ref"
                else HarnessContractReference.from_dict(value["workflow_ref"])
            ),
            schema_version=value["schema_version"],
            compiler_version=value["compiler_version"],
            condition_policy_version=value["condition_policy_version"],
            checksum=value["checksum"],
            graph_ref=(
                HarnessContractReference.from_dict(value["graph_ref"])
                if identity_field == "graph_ref"
                else None
            ),
        )


def _checksum(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if _CHECKSUM_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(
            f"{field_name} must be a canonical sha256 reference",
            code="invalid_graph_checksum_reference",
            details={"field": field_name},
        )
    return text


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} fields do not match its schema",
            code="invalid_graph_state_projection",
            details={
                "missing": sorted(expected.difference(actual)),
                "unknown": sorted(
                    str(item) for item in actual.difference(expected)
                ),
            },
        )


__all__ = ["HarnessGraphReference"]
