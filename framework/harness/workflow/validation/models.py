from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workflow.canonical import freeze_json, required_text, thaw_json


class HarnessGraphValidationPhase(StrEnum):
    CONTRACT = "contract"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    DATAFLOW = "dataflow"
    REGISTRY = "registry"
    POLICY = "policy"


_PHASE_ORDER = {phase: index for index, phase in enumerate(HarnessGraphValidationPhase)}


@dataclass(frozen=True, slots=True)
class HarnessGraphDiagnostic:
    phase: HarnessGraphValidationPhase | str
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    path: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        phase = HarnessGraphValidationPhase(self.phase)
        code = required_text(self.code, "diagnostic.code")
        message = required_text(self.message, "diagnostic.message")
        details = freeze_json(self.details, "diagnostic.details")
        if not isinstance(details, Mapping):
            raise HarnessValidationError(
                "diagnostic details must be an object",
                code="invalid_graph_diagnostic",
            )
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "node_id", _optional_text(self.node_id))
        object.__setattr__(self, "edge_id", _optional_text(self.edge_id))
        object.__setattr__(self, "path", _optional_text(self.path))
        object.__setattr__(self, "details", details)

    @property
    def sort_key(self) -> tuple[int, str, str, str, str]:
        return (
            _PHASE_ORDER[self.phase],
            self.code,
            self.node_id or "",
            self.edge_id or "",
            self.path or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "edge_id": self.edge_id,
            "path": self.path,
            "details": thaw_json(self.details),
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphValidationResult:
    graph_checksum: str
    diagnostics: tuple[HarnessGraphDiagnostic, ...] = ()
    truncated: bool = False

    def __post_init__(self) -> None:
        checksum = required_text(self.graph_checksum, "graph_checksum")
        diagnostics = tuple(sorted(self.diagnostics, key=lambda item: item.sort_key))
        if not all(isinstance(item, HarnessGraphDiagnostic) for item in diagnostics):
            raise TypeError("diagnostics must contain HarnessGraphDiagnostic values")
        object.__setattr__(self, "graph_checksum", checksum)
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics

    def raise_if_invalid(self) -> None:
        if self.is_valid:
            return
        raise HarnessValidationError(
            "Harness graph preflight failed",
            code="harness_graph_preflight_failed",
            details={
                "graph_checksum": self.graph_checksum,
                "diagnostic_count": len(self.diagnostics),
                "truncated": self.truncated,
                "diagnostics": [item.to_dict() for item in self.diagnostics],
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_checksum": self.graph_checksum,
            "is_valid": self.is_valid,
            "truncated": self.truncated,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def diagnostic(
    phase: HarnessGraphValidationPhase,
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    edge_id: str | None = None,
    path: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> HarnessGraphDiagnostic:
    return HarnessGraphDiagnostic(
        phase=phase,
        code=code,
        message=message,
        node_id=node_id,
        edge_id=edge_id,
        path=path,
        details=details or {},
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "HarnessGraphDiagnostic",
    "HarnessGraphValidationPhase",
    "HarnessGraphValidationResult",
    "diagnostic",
]
