from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.events.canonical import StoredEvent, checksum_for, thaw_canonical_json
from framework.events.projection import (
    EventProjection,
    EventProjectionExporter,
)
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import EventSecurityProjector


@dataclass(frozen=True, slots=True)
class WorkflowEventProjection(EventProjection):
    """Legacy Workflow projection descriptor retained until Gate C deletion."""


class WorkflowEventProjectionExporter(EventProjectionExporter):
    """Legacy schema mapper backed by the event-owned projection engine."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(projection_name="workflow", **kwargs)

    def project_event(self, event: StoredEvent) -> dict[str, Any]:
        return project_workflow_event(
            event,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
        )

    def export(
        self,
        *,
        stream_id: str,
        target: str | Path,
        tenant_id: str | None = None,
        through_sequence: int | None = None,
    ) -> WorkflowEventProjection:
        projection = super().export(
            stream_id=stream_id,
            target=target,
            tenant_id=tenant_id,
            through_sequence=through_sequence,
        )
        return WorkflowEventProjection(
            path=projection.path,
            stream_id=projection.stream_id,
            high_watermark=projection.high_watermark,
            event_count=projection.event_count,
            checksum=projection.checksum,
        )

    def verify_existing(
        self,
        *,
        stream_id: str,
        target: str | Path,
        high_watermark: int | None,
        event_count: int,
        checksum: str,
        tenant_id: str | None = None,
    ) -> WorkflowEventProjection:
        projection = super().verify_existing(
            stream_id=stream_id,
            target=target,
            high_watermark=high_watermark,
            event_count=event_count,
            checksum=checksum,
            tenant_id=tenant_id,
        )
        return WorkflowEventProjection(
            path=projection.path,
            stream_id=projection.stream_id,
            high_watermark=projection.high_watermark,
            event_count=projection.event_count,
            checksum=projection.checksum,
        )


def project_workflow_event(
    event: StoredEvent,
    *,
    schema_catalog: EventSchemaCatalog,
    security_projector: EventSecurityProjector | None = None,
) -> dict[str, Any]:
    """Project one legacy Workflow event during the bounded migration window."""

    if not isinstance(event, StoredEvent):
        raise TypeError("event must be a StoredEvent")
    if not isinstance(schema_catalog, EventSchemaCatalog):
        raise TypeError("schema_catalog must be EventSchemaCatalog")
    event.verify_integrity()
    registration = schema_catalog.get(event.event_type, event.data_schema)
    projection = (security_projector or EventSecurityProjector()).project_export(
        payload=event.payload,
        extensions=event.extensions,
        policy=registration.sensitivity_policy,
    )
    row = event.to_dict()
    row["payload"] = (
        None
        if projection.payload is None
        else thaw_canonical_json(projection.payload)
    )
    row["extensions"] = thaw_canonical_json(projection.extensions)
    row["source_content_checksum"] = row.pop("content_checksum")
    row["source_record_checksum"] = row.pop("record_checksum")
    row["projection_schema"] = "newsroom.workflow-event-projection/v1"
    business_context = event.business_context
    row.update(
        {
            "run_id": business_context.run_id,
            "workflow_id": business_context.workflow_id,
            "step_id": business_context.step_id,
            "task_id": business_context.task_id,
            "agent_id": business_context.agent_id,
            "tool_call_id": business_context.tool_call_id,
            "request_id": business_context.request_id,
            "component": event.producer.component,
            "trace_id": event.trace.trace_id if event.trace is not None else None,
            "span_id": event.trace.span_id if event.trace is not None else None,
            "parent_span_id": (
                event.trace.parent_span_id if event.trace is not None else None
            ),
        }
    )
    row["projection_checksum"] = checksum_for(row)
    return row


__all__ = [
    "WorkflowEventProjection",
    "WorkflowEventProjectionExporter",
    "project_workflow_event",
]
