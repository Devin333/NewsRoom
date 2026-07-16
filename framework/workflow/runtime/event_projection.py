from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.events.canonical import StoredEvent, checksum_for, thaw_canonical_json
from framework.events.errors import EventContractError
from framework.events.ports import EventReaderPort
from framework.events.runtime.models import MAX_PAGE_LIMIT, StreamReadRequest
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import EventSecurityProjector


@dataclass(frozen=True, slots=True)
class WorkflowEventProjection:
    path: Path
    stream_id: str
    high_watermark: int | None
    event_count: int
    checksum: str


class WorkflowEventProjectionExporter:
    """Build a deterministic compatibility artifact from a durable stream."""

    def __init__(
        self,
        *,
        reader: EventReaderPort,
        schema_catalog: EventSchemaCatalog,
        security_projector: EventSecurityProjector | None = None,
        page_size: int = 1_000,
    ) -> None:
        if reader is None:
            raise ValueError("event reader is required")
        if not isinstance(schema_catalog, EventSchemaCatalog):
            raise TypeError("schema_catalog must be EventSchemaCatalog")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_PAGE_LIMIT
        ):
            raise ValueError("page_size must be a positive integer")
        self._reader = reader
        self._schema_catalog = schema_catalog
        self._security_projector = security_projector or EventSecurityProjector()
        self._page_size = page_size

    def export(
        self,
        *,
        stream_id: str,
        target: str | Path,
        tenant_id: str | None = None,
        through_sequence: int | None = None,
    ) -> WorkflowEventProjection:
        normalized_stream_id = _required_text(stream_id, "stream_id")
        target_path = Path(target)
        requested_high_watermark = (
            None
            if through_sequence is None
            else _positive_sequence(through_sequence)
        )
        high_watermark = (
            self._reader.get_stream_high_watermark(
                normalized_stream_id,
                tenant_id=tenant_id,
            )
            if requested_high_watermark is None
            else requested_high_watermark
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(
            f".{target_path.name}.{uuid4().hex}.tmp"
        )
        digest = sha256()
        event_count = 0
        try:
            with temporary_path.open("xb") as handle:
                if high_watermark is not None:
                    for event in self._read_prefix(
                        stream_id=normalized_stream_id,
                        tenant_id=tenant_id,
                        high_watermark=high_watermark,
                    ):
                        encoded = _jsonl_bytes(self.project_event(event))
                        handle.write(encoded)
                        digest.update(encoded)
                        event_count += 1
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target_path)
            _fsync_directory(target_path.parent)
        except Exception:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return WorkflowEventProjection(
            path=target_path,
            stream_id=normalized_stream_id,
            high_watermark=high_watermark,
            event_count=event_count,
            checksum=f"sha256:{digest.hexdigest()}",
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
        """Verify that an existing projection is the recorded durable prefix."""

        normalized_stream_id = _required_text(stream_id, "stream_id")
        target_path = Path(target)
        expected_high_watermark = (
            None if high_watermark is None else _positive_sequence(high_watermark)
        )
        expected_count = _nonnegative_count(event_count)
        expected_checksum = _sha256_checksum(checksum)
        if expected_high_watermark is None:
            if expected_count != 0:
                raise EventContractError(
                    "empty event projection must record an event count of zero"
                )
        elif expected_count != expected_high_watermark:
            raise EventContractError(
                "workflow event projection count must equal its stream high watermark"
            )

        current_high_watermark = self._reader.get_stream_high_watermark(
            normalized_stream_id,
            tenant_id=tenant_id,
        )
        if expected_high_watermark is not None and (
            current_high_watermark is None
            or current_high_watermark < expected_high_watermark
        ):
            raise EventContractError(
                "durable stream does not contain the recorded projection prefix"
            )

        digest = sha256()
        verified_count = 0
        try:
            handle = target_path.open("rb")
        except OSError as exc:
            raise EventContractError("event projection artifact is unavailable") from exc
        with handle:
            events = (
                ()
                if expected_high_watermark is None
                else self._read_prefix(
                    stream_id=normalized_stream_id,
                    tenant_id=tenant_id,
                    high_watermark=expected_high_watermark,
                )
            )
            for event in events:
                raw_line = handle.readline()
                if not raw_line or not raw_line.endswith(b"\n"):
                    raise EventContractError(
                        "event projection is missing a complete durable event row"
                    )
                digest.update(raw_line)
                try:
                    row = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EventContractError("event projection row is invalid JSON") from exc
                if not isinstance(row, Mapping) or dict(row) != self.project_event(event):
                    raise EventContractError(
                        "event projection row does not match the durable event"
                    )
                verified_count += 1
            if handle.read(1):
                raise EventContractError(
                    "event projection contains rows beyond its recorded high watermark"
                )

        actual_checksum = f"sha256:{digest.hexdigest()}"
        if verified_count != expected_count:
            raise EventContractError("event projection count does not match its manifest")
        if actual_checksum != expected_checksum:
            raise EventContractError("event projection checksum does not match its manifest")
        return WorkflowEventProjection(
            path=target_path,
            stream_id=normalized_stream_id,
            high_watermark=expected_high_watermark,
            event_count=verified_count,
            checksum=actual_checksum,
        )

    def _read_prefix(
        self,
        *,
        stream_id: str,
        tenant_id: str | None,
        high_watermark: int,
    ):
        request = StreamReadRequest(
            stream_id=stream_id,
            tenant_id=tenant_id,
            limit=self._page_size,
            through_sequence=high_watermark,
        )
        expected_sequence = 1
        while True:
            page = self._reader.read_stream(request)
            if page.stream_id != stream_id or page.tenant_id != tenant_id:
                raise EventContractError("event reader returned another stream scope")
            if page.high_watermark != high_watermark:
                raise EventContractError("event reader changed the projection high watermark")
            for event in page.events:
                if event.stream_sequence != expected_sequence:
                    raise EventContractError(
                        "event projection requires a contiguous stream prefix"
                    )
                expected_sequence += 1
                yield event
            if page.next_cursor is None:
                break
            request = StreamReadRequest(
                stream_id=stream_id,
                tenant_id=tenant_id,
                cursor=page.next_cursor,
                limit=self._page_size,
                through_sequence=high_watermark,
            )
        if expected_sequence - 1 != high_watermark:
            raise EventContractError("event reader returned an incomplete stream prefix")

    def project_event(self, event: StoredEvent) -> dict[str, Any]:
        """Return the schema-aware compatibility row used by JSONL and online reads."""

        return project_workflow_event(
            event,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
        )


def project_workflow_event(
    event: StoredEvent,
    *,
    schema_catalog: EventSchemaCatalog,
    security_projector: EventSecurityProjector | None = None,
) -> dict[str, Any]:
    """Project one durable event without writing or feeding it back to a store."""

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


def _jsonl_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _positive_sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("through_sequence must be a positive integer")
    return value


def _nonnegative_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventContractError("event projection count must be a non-negative integer")
    return value


def _sha256_checksum(value: Any) -> str:
    if not isinstance(value, str):
        raise EventContractError("event projection checksum must be SHA-256")
    prefix, separator, digest = value.partition(":")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EventContractError("event projection checksum must be SHA-256")
    return value


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "WorkflowEventProjection",
    "WorkflowEventProjectionExporter",
    "project_workflow_event",
]
