from __future__ import annotations

import json
import os
import re
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
from framework.events.telemetry import (
    EventTelemetry,
    TelemetryInstrumentationScope,
    TelemetryResource,
    default_event_telemetry,
)
from framework.shared.graph_identity import (
    GraphExecutionIdentity,
    GraphRunIdentity,
    GraphStageIdentity,
)


CANONICAL_EVENT_PROJECTION_SCHEMA = "newsroom.event-projection/v1"
GRAPH_EVENT_CONTEXT_EXTENSION = "graph_context"
GRAPH_EVENT_CONTEXT_SCHEMA = "newsroom.graph-event-context/v2"
GRAPH_EVENT_PROJECTION_SCHEMA = "newsroom.graph-event-projection/v2"

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MOVING_VERSIONS = frozenset({"current", "default", "latest", "stable"})
_GRAPH_CONTEXT_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "graph_id",
        "graph_version",
        "graph_ref",
        "graph_checksum",
        "graph_schema_version",
        "compiler_version",
        "normalized_graph_checksum",
        "stage_identity",
        "execution_identity",
    }
)


@dataclass(frozen=True, slots=True)
class EventProjection:
    path: Path
    stream_id: str
    high_watermark: int | None
    event_count: int
    checksum: str


@dataclass(frozen=True, slots=True)
class GraphEventExecutionVersion:
    """Pinned compilation details carried alongside canonical Graph identity."""

    graph_schema_version: str
    compiler_version: str
    normalized_graph_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "graph_schema_version",
            _exact_version(self.graph_schema_version, "graph_schema_version"),
        )
        object.__setattr__(
            self,
            "compiler_version",
            _exact_version(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(
            self,
            "normalized_graph_checksum",
            _sha256_checksum(
                self.normalized_graph_checksum,
                "normalized_graph_checksum",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "normalized_graph_checksum": self.normalized_graph_checksum,
        }


@dataclass(frozen=True, slots=True)
class GraphEventContext:
    identity: GraphRunIdentity
    execution_version: GraphEventExecutionVersion
    stage_identity: GraphStageIdentity | None = None
    execution_identity: GraphExecutionIdentity | None = None
    schema: str = GRAPH_EVENT_CONTEXT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.identity, GraphRunIdentity):
            raise TypeError("identity must be GraphRunIdentity")
        if not isinstance(self.execution_version, GraphEventExecutionVersion):
            raise TypeError("execution_version must be GraphEventExecutionVersion")
        if self.schema != GRAPH_EVENT_CONTEXT_SCHEMA:
            raise EventContractError("graph event context schema is unsupported")
        if self.execution_version.normalized_graph_checksum != self.identity.graph_checksum:
            raise EventContractError(
                "graph event execution checksum conflicts with Graph identity"
            )
        execution_identity = self.execution_identity
        stage_identity = self.stage_identity
        if stage_identity is not None and not isinstance(stage_identity, GraphStageIdentity):
            raise TypeError("stage_identity must be GraphStageIdentity or None")
        if stage_identity is not None and stage_identity.run_identity != self.identity:
            raise EventContractError(
                "graph stage identity conflicts with Graph run identity"
            )
        if execution_identity is not None:
            if not isinstance(execution_identity, GraphExecutionIdentity):
                raise TypeError(
                    "execution_identity must be GraphExecutionIdentity or None"
                )
            if execution_identity.run_identity != self.identity:
                raise EventContractError(
                    "graph event execution identity conflicts with Graph run identity"
                )
            if stage_identity is not None:
                raise EventContractError(
                    "graph event context cannot carry both stage and execution identity"
                )

    @property
    def node_id(self) -> str | None:
        identity = self.execution_identity or self.stage_identity
        return None if identity is None else identity.node_id

    @property
    def node_instance_id(self) -> str | None:
        identity = self.execution_identity or self.stage_identity
        return None if identity is None else identity.node_instance_id

    @property
    def activity_id(self) -> str | None:
        identity = self.execution_identity
        return None if identity is None else identity.activity_id

    @property
    def attempt(self) -> int | None:
        identity = self.execution_identity
        return None if identity is None else identity.attempt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            **self.identity.to_dict(),
            **self.execution_version.to_dict(),
            "execution_identity": (
                None
                if self.execution_identity is None
                else self.execution_identity.to_dict()
            ),
            "stage_identity": (
                None
                if self.stage_identity is None
                else self.stage_identity.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GraphEventContext:
        payload = _exact_mapping(value, _GRAPH_CONTEXT_FIELDS, "graph event context")
        try:
            identity = GraphRunIdentity(
                run_id=payload["run_id"],
                graph_id=payload["graph_id"],
                graph_version=payload["graph_version"],
                graph_ref=payload["graph_ref"],
                graph_checksum=payload["graph_checksum"],
            )
        except (TypeError, ValueError) as error:
            raise EventContractError(str(error)) from error
        raw_stage_identity = payload["stage_identity"]
        if raw_stage_identity is not None and not isinstance(raw_stage_identity, Mapping):
            raise EventContractError("graph event stage_identity must be an object")
        try:
            stage_identity = (
                None
                if raw_stage_identity is None
                else GraphStageIdentity.from_dict(raw_stage_identity)
            )
        except (TypeError, ValueError) as error:
            raise EventContractError(str(error)) from error
        raw_execution_identity = payload["execution_identity"]
        if raw_execution_identity is not None and not isinstance(
            raw_execution_identity,
            Mapping,
        ):
            raise EventContractError("graph event execution_identity must be an object")
        try:
            execution_identity = (
                None
                if raw_execution_identity is None
                else GraphExecutionIdentity.from_dict(raw_execution_identity)
            )
        except (TypeError, ValueError) as error:
            raise EventContractError(str(error)) from error
        return cls(
            identity=identity,
            execution_version=GraphEventExecutionVersion(
                graph_schema_version=payload["graph_schema_version"],
                compiler_version=payload["compiler_version"],
                normalized_graph_checksum=payload["normalized_graph_checksum"],
            ),
            stage_identity=stage_identity,
            execution_identity=execution_identity,
            schema=payload["schema"],
        )


@dataclass(frozen=True, slots=True)
class GraphEventProjection(EventProjection):
    graph_identity: GraphRunIdentity
    execution_version: GraphEventExecutionVersion

    def __post_init__(self) -> None:
        if not isinstance(self.graph_identity, GraphRunIdentity):
            raise TypeError("graph_identity must be GraphRunIdentity")
        if not isinstance(self.execution_version, GraphEventExecutionVersion):
            raise TypeError("execution_version must be GraphEventExecutionVersion")
        if self.execution_version.normalized_graph_checksum != self.graph_identity.graph_checksum:
            raise EventContractError(
                "graph event projection execution checksum conflicts with Graph identity"
            )
        if self.stream_id != f"run:{self.graph_identity.run_id}":
            raise EventContractError(
                "graph event projection stream conflicts with Graph run identity"
            )


class _ProjectionSession:
    def __init__(self, exporter: EventProjectionExporter, stream_id: str) -> None:
        self._exporter = exporter
        self._stream_id = stream_id

    def project(self, event: StoredEvent) -> dict[str, Any]:
        return self._exporter.project_event(event)


class _GraphProjectionSession(_ProjectionSession):
    def __init__(
        self,
        exporter: GraphEventProjectionExporter,
        stream_id: str,
    ) -> None:
        super().__init__(exporter, stream_id)
        self._graph_exporter = exporter
        self._stream_id = stream_id
        self.identity: GraphRunIdentity | None = None
        self.execution_version: GraphEventExecutionVersion | None = None

    def project(self, event: StoredEvent) -> dict[str, Any]:
        context = graph_event_context(event)
        if self._stream_id != f"run:{context.identity.run_id}":
            raise EventContractError(
                "graph event projection received another run stream"
            )
        if self.identity is None:
            self.identity = context.identity
        elif self.identity != context.identity:
            raise EventContractError(
                "graph event projection contains conflicting Graph identity"
            )
        if self.execution_version is None:
            self.execution_version = context.execution_version
        elif self.execution_version != context.execution_version:
            raise EventContractError(
                "graph event projection contains conflicting Graph execution version"
            )
        return self._graph_exporter.project_event(event)


class EventProjectionExporter:
    """Build and verify a bounded deterministic projection of one event stream."""

    def __init__(
        self,
        *,
        reader: EventReaderPort,
        schema_catalog: EventSchemaCatalog,
        security_projector: EventSecurityProjector | None = None,
        page_size: int = 1_000,
        telemetry: EventTelemetry | None = None,
        projection_name: str = "canonical",
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
        self._projection_name = _required_text(projection_name, "projection_name")
        self._telemetry = telemetry or default_event_telemetry(
            resource=TelemetryResource(service_name="newsroom-event-runtime"),
            scope=TelemetryInstrumentationScope(
                name="framework.events.projection",
                version="1",
            ),
        )

    def export(
        self,
        *,
        stream_id: str,
        target: str | Path,
        tenant_id: str | None = None,
        through_sequence: int | None = None,
    ) -> EventProjection:
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
        session = self._projection_session(normalized_stream_id)
        try:
            with temporary_path.open("xb") as handle:
                if high_watermark is not None:
                    for event in self._read_prefix(
                        stream_id=normalized_stream_id,
                        tenant_id=tenant_id,
                        high_watermark=high_watermark,
                    ):
                        encoded = _jsonl_bytes(session.project(event))
                        handle.write(encoded)
                        digest.update(encoded)
                        event_count += 1
                projection = self._build_projection(
                    path=target_path,
                    stream_id=normalized_stream_id,
                    high_watermark=high_watermark,
                    event_count=event_count,
                    checksum=f"sha256:{digest.hexdigest()}",
                    session=session,
                )
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
        self._record_projection_metrics(high_watermark=high_watermark, staleness=0)
        return projection

    def verify_existing(
        self,
        *,
        stream_id: str,
        target: str | Path,
        high_watermark: int | None,
        event_count: int,
        checksum: str,
        tenant_id: str | None = None,
    ) -> EventProjection:
        """Verify that an existing projection is the recorded durable prefix."""

        normalized_stream_id = _required_text(stream_id, "stream_id")
        target_path = Path(target)
        expected_high_watermark = (
            None if high_watermark is None else _positive_sequence(high_watermark)
        )
        expected_count = _nonnegative_count(event_count)
        expected_checksum = _sha256_checksum(checksum, "projection checksum")
        if expected_high_watermark is None:
            if expected_count != 0:
                raise EventContractError(
                    "empty event projection must record an event count of zero"
                )
        elif expected_count != expected_high_watermark:
            raise EventContractError(
                "event projection count must equal its stream high watermark"
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
        session = self._projection_session(normalized_stream_id)
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
                if not isinstance(row, Mapping) or dict(row) != session.project(event):
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
        projection = self._build_projection(
            path=target_path,
            stream_id=normalized_stream_id,
            high_watermark=expected_high_watermark,
            event_count=verified_count,
            checksum=actual_checksum,
            session=session,
        )
        self._record_projection_metrics(
            high_watermark=expected_high_watermark,
            staleness=max(
                0,
                (current_high_watermark or 0) - (expected_high_watermark or 0),
            ),
        )
        return projection

    def project_event(self, event: StoredEvent) -> dict[str, Any]:
        return project_canonical_event(
            event,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
        )

    def _projection_session(self, stream_id: str) -> _ProjectionSession:
        return _ProjectionSession(self, stream_id)

    def _build_projection(
        self,
        *,
        path: Path,
        stream_id: str,
        high_watermark: int | None,
        event_count: int,
        checksum: str,
        session: _ProjectionSession,
    ) -> EventProjection:
        del session
        return EventProjection(
            path=path,
            stream_id=stream_id,
            high_watermark=high_watermark,
            event_count=event_count,
            checksum=checksum,
        )

    def _record_projection_metrics(
        self,
        *,
        high_watermark: int | None,
        staleness: int,
    ) -> None:
        labels = {"projection": self._projection_name}
        self._telemetry.record_gauge(
            "event_projection_high_watermark",
            high_watermark or 0,
            labels=labels,
        )
        self._telemetry.record_gauge(
            "event_projection_staleness",
            staleness,
            labels=labels,
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


class GraphEventProjectionExporter(EventProjectionExporter):
    """Project only one checksum-bound Graph run identity."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(projection_name="graph", **kwargs)

    def project_event(self, event: StoredEvent) -> dict[str, Any]:
        return project_graph_event(
            event,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
        )

    def _projection_session(self, stream_id: str) -> _GraphProjectionSession:
        return _GraphProjectionSession(self, stream_id)

    def _build_projection(
        self,
        *,
        path: Path,
        stream_id: str,
        high_watermark: int | None,
        event_count: int,
        checksum: str,
        session: _ProjectionSession,
    ) -> GraphEventProjection:
        if not isinstance(session, _GraphProjectionSession):
            raise EventContractError("graph event projection session is invalid")
        if session.identity is None:
            raise EventContractError(
                "graph event projection requires initialized Graph history"
            )
        if session.execution_version is None:
            raise EventContractError(
                "graph event projection requires initialized Graph execution version"
            )
        return GraphEventProjection(
            path=path,
            stream_id=stream_id,
            high_watermark=high_watermark,
            event_count=event_count,
            checksum=checksum,
            graph_identity=session.identity,
            execution_version=session.execution_version,
        )


def project_canonical_event(
    event: StoredEvent,
    *,
    schema_catalog: EventSchemaCatalog,
    security_projector: EventSecurityProjector | None = None,
) -> dict[str, Any]:
    """Project one canonical event for owner-controlled offline comparisons."""

    row = _security_projected_row(
        event,
        schema_catalog=schema_catalog,
        security_projector=security_projector,
    )
    row["projection_schema"] = CANONICAL_EVENT_PROJECTION_SCHEMA
    business_context = event.business_context
    row.update(
        {
            "run_id": business_context.run_id,
            "task_id": business_context.task_id,
            "agent_id": business_context.agent_id,
            "tool_call_id": business_context.tool_call_id,
            "request_id": business_context.request_id,
            "component": event.producer.component,
            **_trace_projection(event),
        }
    )
    row["projection_checksum"] = checksum_for(row)
    return row


def graph_event_context(event: StoredEvent) -> GraphEventContext:
    if not isinstance(event, StoredEvent):
        raise TypeError("event must be a StoredEvent")
    event.verify_integrity()
    raw_context = thaw_canonical_json(
        event.extensions.get(GRAPH_EVENT_CONTEXT_EXTENSION)
    )
    if not isinstance(raw_context, Mapping):
        raise EventContractError("graph event context extension is required")
    context = GraphEventContext.from_dict(raw_context)
    run_id = context.identity.run_id
    business_context = event.business_context
    if (
        event.stream_id != f"run:{run_id}"
        or event.correlation_id != run_id
        or business_context.run_id != run_id
    ):
        raise EventContractError(
            "graph event envelope conflicts with Graph run identity"
        )
    expected_ref = (
        f"{context.identity.graph_id}@{context.identity.graph_version}"
    )
    if (
        business_context.graph_id != context.identity.graph_id
        or business_context.graph_version != context.identity.graph_version
        or business_context.graph_ref != expected_ref
        or business_context.graph_checksum
        != context.identity.graph_checksum
    ):
        raise EventContractError(
            "graph event envelope conflicts with the pinned Graph identity"
        )
    if context.stage_identity is not None and (
        business_context.stage_id != context.node_id
        or business_context.node_instance_id != context.node_instance_id
    ):
        raise EventContractError(
            "graph event envelope conflicts with the Graph stage identity"
        )
    if context.execution_identity is not None and (
        business_context.stage_id != context.node_id
        or business_context.node_instance_id != context.node_instance_id
        or business_context.execution_identity != context.execution_identity
    ):
        raise EventContractError(
            "graph event envelope conflicts with the Graph execution identity"
        )
    if (
        context.stage_identity is None
        and context.execution_identity is None
        and business_context.node_instance_id is not None
    ):
        raise EventContractError(
            "run-level Graph event cannot carry a node_instance_id"
        )
    return context


def project_graph_event(
    event: StoredEvent,
    *,
    schema_catalog: EventSchemaCatalog,
    security_projector: EventSecurityProjector | None = None,
) -> dict[str, Any]:
    """Project one Graph event after exact run, Graph, and node validation."""

    context = graph_event_context(event)
    row = _security_projected_row(
        event,
        schema_catalog=schema_catalog,
        security_projector=security_projector,
    )
    business_context = event.business_context
    row["business_context"] = {
        "run_id": business_context.run_id,
        "graph_id": business_context.graph_id,
        "graph_version": business_context.graph_version,
        "graph_ref": business_context.graph_ref,
        "graph_checksum": business_context.graph_checksum,
        "execution_identity": (
            None
            if business_context.execution_identity is None
            else business_context.execution_identity.to_dict()
        ),
        "stage_id": business_context.stage_id,
        "node_instance_id": business_context.node_instance_id,
        "task_id": business_context.task_id,
        "agent_id": business_context.agent_id,
        "tool_call_id": business_context.tool_call_id,
        "request_id": business_context.request_id,
    }
    row["projection_schema"] = GRAPH_EVENT_PROJECTION_SCHEMA
    row.update(
        {
            **context.identity.to_dict(),
            "node_id": context.node_id,
            "node_instance_id": context.node_instance_id,
            "activity_id": context.activity_id,
            "attempt": context.attempt,
            "execution_identity": (
                None
                if context.execution_identity is None
                else context.execution_identity.to_dict()
            ),
            "component": event.producer.component,
            **_trace_projection(event),
        }
    )
    row["projection_checksum"] = checksum_for(row)
    return row


def _security_projected_row(
    event: StoredEvent,
    *,
    schema_catalog: EventSchemaCatalog,
    security_projector: EventSecurityProjector | None,
) -> dict[str, Any]:
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
    return row


def _trace_projection(event: StoredEvent) -> dict[str, str | None]:
    trace = event.trace
    return {
        "trace_id": trace.trace_id if trace is not None else None,
        "span_id": trace.span_id if trace is not None else None,
        "parent_span_id": trace.parent_span_id if trace is not None else None,
    }


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
        raise EventContractError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _exact_version(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if normalized.casefold() in _MOVING_VERSIONS:
        raise EventContractError(f"{field_name} must be an exact version")
    return normalized


def _identifier(value: Any, field_name: str, *, pattern: re.Pattern[str]) -> str:
    normalized = _required_text(value, field_name)
    if pattern.fullmatch(normalized) is None or normalized in {".", ".."}:
        raise EventContractError(f"{field_name} is invalid")
    return normalized


def _positive_sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("through_sequence must be a positive integer")
    return value


def _nonnegative_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventContractError("event projection count must be a non-negative integer")
    return value


def _sha256_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
        raise EventContractError(f"{field_name} must be SHA-256")
    return value


def _exact_mapping(
    value: Mapping[str, Any],
    expected_fields: frozenset[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EventContractError(f"{model} must be an object")
    payload = dict(value)
    if set(payload) != expected_fields:
        raise EventContractError(f"{model} fields are invalid")
    return payload


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "CANONICAL_EVENT_PROJECTION_SCHEMA",
    "EventProjection",
    "EventProjectionExporter",
    "GRAPH_EVENT_CONTEXT_EXTENSION",
    "GRAPH_EVENT_CONTEXT_SCHEMA",
    "GRAPH_EVENT_PROJECTION_SCHEMA",
    "GraphEventContext",
    "GraphEventExecutionVersion",
    "GraphEventProjection",
    "GraphEventProjectionExporter",
    "graph_event_context",
    "project_canonical_event",
    "project_graph_event",
]
