"""Graph-owned observability value contracts.

State-derived metric and health projections remain in the control plane; this
module owns the immutable values they return.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.canonical import required_text


class HarnessGraphHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HarnessGraphDiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class HarnessGraphMetricSample:
    name: str
    value: float
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", required_text(self.name, "metric.name"))
        if not isinstance(self.value, int | float) or isinstance(self.value, bool):
            raise TypeError("metric value must be numeric")
        labels = dict(self.labels)
        allowed = {"lifecycle", "outcome", "result"}
        if set(labels).difference(allowed):
            raise HarnessValidationError(
                "graph metric contains a high-cardinality label",
                code="graph_metric_label_rejected",
            )
        object.__setattr__(
            self,
            "labels",
            MappingProxyType({key: str(labels[key]) for key in sorted(labels)}),
        )
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "labels": dict(self.labels)}


@dataclass(frozen=True, slots=True)
class HarnessGraphOperatorDiagnostic:
    code: str
    severity: HarnessGraphDiagnosticSeverity | str
    evidence_refs: tuple[str, ...] = ()
    current_value: int | None = None
    threshold: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", required_text(self.code, "diagnostic.code"))
        object.__setattr__(
            self,
            "severity",
            HarnessGraphDiagnosticSeverity(self.severity),
        )
        refs = tuple(sorted(str(item) for item in self.evidence_refs))
        if any(not _is_checksum(item) for item in refs):
            raise HarnessValidationError(
                "operator diagnostics may expose checksum evidence only",
                code="graph_diagnostic_reference_rejected",
            )
        object.__setattr__(self, "evidence_refs", refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "evidence_refs": list(self.evidence_refs),
            "current_value": self.current_value,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class HarnessGraphHealthReport:
    status: HarnessGraphHealthStatus | str
    diagnostics: tuple[HarnessGraphOperatorDiagnostic, ...]
    last_event_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HarnessGraphHealthStatus(self.status))
        diagnostics = tuple(self.diagnostics)
        if not all(
            isinstance(item, HarnessGraphOperatorDiagnostic) for item in diagnostics
        ):
            raise TypeError("diagnostics must contain HarnessGraphOperatorDiagnostic")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(diagnostics, key=lambda item: (item.severity.value, item.code))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "last_event_sequence": self.last_event_sequence,
        }


def _is_checksum(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


__all__ = [
    "HarnessGraphDiagnosticSeverity",
    "HarnessGraphHealthReport",
    "HarnessGraphHealthStatus",
    "HarnessGraphMetricSample",
    "HarnessGraphOperatorDiagnostic",
]
