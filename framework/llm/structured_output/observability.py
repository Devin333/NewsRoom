from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Iterable, Mapping

from framework.shared.graph_identity import GraphExecutionIdentity


STRUCTURED_OUTPUT_EVENT_TYPES = frozenset(
    {
        "structured_output_contract_compiled",
        "structured_output_schema_preflight_failed",
        "structured_output_provider_projection_selected",
        "structured_output_provider_projection_rejected",
        "structured_output_decode_rejected",
        "structured_output_local_validation_failed",
        "structured_output_typed_validation_failed",
        "structured_output_repair_requested",
        "structured_output_validation_accepted",
        "structured_output_repair_budget_exhausted",
        "structured_output_cache_validation",
    }
)


@dataclass(frozen=True)
class StructuredOutputEvent:
    event_type: str
    run_id: str | None = None
    execution_identity: GraphExecutionIdentity | None = None
    attempt_ref: str | None = None
    schema_digest: str | None = None
    schema_revision: str | None = None
    schema_dialect: str | None = None
    typed_adapter_revision: str | None = None
    provider: str | None = None
    deployment_id: str | None = None
    provider_capability_revision: str | None = None
    projection_digest: str | None = None
    projection_mode: str | None = None
    issue_code: str | None = None
    instance_path: tuple[str | int, ...] = ()
    schema_path: tuple[str | int, ...] = ()
    issue_count: int = 0
    response_fingerprint: str | None = None
    budget_disposition: str | None = None
    validation_duration_seconds: float | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.event_type not in STRUCTURED_OUTPUT_EVENT_TYPES:
            raise ValueError("unsupported structured-output event type")
        if isinstance(self.issue_count, bool) or not 0 <= self.issue_count <= 20:
            raise ValueError("structured-output issue_count must be between 0 and 20")
        for field_name in ("instance_path", "schema_path"):
            path = tuple(getattr(self, field_name))
            if len(path) > 64 or any(
                isinstance(item, bool)
                or not isinstance(item, (str, int))
                or (isinstance(item, str) and len(item) > 128)
                for item in path
            ):
                raise ValueError(f"structured-output {field_name} is not bounded")
            object.__setattr__(self, field_name, path)
        if self.validation_duration_seconds is not None and (
            self.validation_duration_seconds < 0
        ):
            raise ValueError("validation duration must be non-negative")
        identity = self.execution_identity
        if identity is not None and not isinstance(identity, GraphExecutionIdentity):
            identity = GraphExecutionIdentity.from_dict(identity)
        if identity is not None:
            if self.run_id is not None and self.run_id != identity.run_id:
                raise ValueError("structured-output run_id must match execution identity")
            object.__setattr__(self, "run_id", identity.run_id)
        object.__setattr__(self, "execution_identity", identity)

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "execution_identity": (
                self.execution_identity.to_dict()
                if self.execution_identity is not None
                else None
            ),
            "attempt_ref": self.attempt_ref,
            "schema_digest": self.schema_digest,
            "schema_revision": self.schema_revision,
            "schema_dialect": self.schema_dialect,
            "typed_adapter_revision": self.typed_adapter_revision,
            "provider": self.provider,
            "deployment_id": self.deployment_id,
            "provider_capability_revision": self.provider_capability_revision,
            "projection_digest": self.projection_digest,
            "projection_mode": self.projection_mode,
            "issue_code": self.issue_code,
            "instance_path": list(self.instance_path),
            "schema_path": list(self.schema_path),
            "issue_count": self.issue_count,
            "response_fingerprint": self.response_fingerprint,
            "budget_disposition": self.budget_disposition,
            "validation_duration_seconds": self.validation_duration_seconds,
            "timestamp": self.occurred_at.isoformat(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"event_type": self.event_type, **self.to_payload()}


StructuredOutputEventSink = Callable[[StructuredOutputEvent], None]


@dataclass(frozen=True)
class StructuredOutputMetricPoint:
    name: str
    value: float = 1.0
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", dict(self.labels))


def project_structured_output_metrics(
    events: Iterable[Mapping[str, Any]],
) -> tuple[StructuredOutputMetricPoint, ...]:
    points: list[StructuredOutputMetricPoint] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        metadata = event.get("metadata")
        payload = dict(metadata) if isinstance(metadata, Mapping) else dict(event)
        if event_type == "structured_output_contract_compiled":
            points.append(
                _point(
                    "structured_output_requests_total",
                    mode="managed",
                    outcome="compiled",
                )
            )
            schema_bytes = payload.get("schema_bytes")
            if isinstance(schema_bytes, (int, float)) and not isinstance(schema_bytes, bool):
                points.append(
                    StructuredOutputMetricPoint(
                        name="structured_output_schema_bytes",
                        value=float(schema_bytes),
                    )
                )
        elif event_type == "structured_output_schema_preflight_failed":
            points.append(
                _point(
                    "structured_output_schema_preflight_failures_total",
                    code=_bounded(payload.get("issue_code"), "unknown"),
                )
            )
        elif event_type == "structured_output_provider_projection_selected":
            points.append(
                _point(
                    "structured_output_provider_projection_total",
                    mode=_bounded(payload.get("projection_mode"), "unknown"),
                    outcome="selected",
                )
            )
        elif event_type == "structured_output_provider_projection_rejected":
            points.append(
                _point(
                    "structured_output_provider_projection_total",
                    mode="rejected",
                    outcome="rejected",
                )
            )
        elif event_type in {
            "structured_output_decode_rejected",
            "structured_output_local_validation_failed",
            "structured_output_typed_validation_failed",
        }:
            points.append(
                _point(
                    "structured_output_validation_failures_total",
                    code=_bounded(payload.get("issue_code"), "unknown"),
                    validator=_bounded(payload.get("validator"), "unknown"),
                )
            )
            points.append(
                _point(
                    "structured_output_provider_vs_local_failure_total",
                    provider=_bounded(event.get("provider"), "unknown"),
                    mode=_bounded(payload.get("projection_mode"), "local_gate"),
                )
            )
        elif event_type == "structured_output_repair_requested":
            points.append(
                _point("structured_output_repair_total", outcome="requested")
            )
        elif event_type == "structured_output_validation_accepted":
            points.append(
                _point(
                    "structured_output_requests_total",
                    mode=_bounded(payload.get("projection_mode"), "managed"),
                    outcome="accepted",
                )
            )
            repair_count = payload.get("repair_count")
            if isinstance(repair_count, int) and repair_count > 0:
                points.append(
                    _point("structured_output_repair_total", outcome="succeeded")
                )
        elif event_type == "structured_output_repair_budget_exhausted":
            points.append(
                StructuredOutputMetricPoint(
                    name="structured_output_repair_budget_exhausted_total"
                )
            )
        elif event_type == "structured_output_cache_validation":
            points.append(
                _point(
                    "structured_output_cache_validation_total",
                    outcome=_bounded(payload.get("outcome"), "unknown"),
                )
            )
        duration = payload.get("validation_duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            points.append(
                StructuredOutputMetricPoint(
                    name="structured_output_validation_duration_seconds",
                    value=max(0.0, float(duration)),
                )
            )
    return tuple(points)


def _point(name: str, **labels: str) -> StructuredOutputMetricPoint:
    return StructuredOutputMetricPoint(name=name, labels=labels)


def _bounded(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip()[:64]


__all__ = [
    "STRUCTURED_OUTPUT_EVENT_TYPES",
    "StructuredOutputEvent",
    "StructuredOutputEventSink",
    "StructuredOutputMetricPoint",
    "project_structured_output_metrics",
]
