from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.application import (
    DurableGraphEventProjectionAdapter,
    GraphEventProjectionApplicationPort,
    GraphEventProjectionApplicationRequest,
    GraphEventProjectionApplicationStatus,
)
from framework.events.ports import EventReaderPort
from framework.events.runtime.models import MAX_PAGE_LIMIT
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import EventSecurityProjector
from framework.events.projection import GraphEventProjection
from framework.shared.graph_identity import GraphRunIdentity
from framework.harness.artifacts import (
    GraphTerminalManifestV2,
    GraphTerminalManifestPort,
)
from framework.agent.artifacts.stores.errors import ArtifactNotFoundError
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizerPort,
    EventPermission,
    EventServiceAvailability,
    authorize_event_operation,
)


class EventProjectionStatus(str, Enum):
    CURRENT = "current"
    RUNNING = "running"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class EventProjectionSourceRangeError(EventContractError):
    """The requested durable prefix does not exist in the authorized stream."""


class EventProjectionConflictError(EventContractError):
    """Projection metadata, bytes, and durable history cannot all be true."""

    def __init__(self, reason_class: str) -> None:
        self.reason_class = reason_class
        super().__init__(f"event projection conflict: {reason_class}")


class EventProjectionNotFoundError(LookupError):
    """A run projection is not visible in the authorized tenant scope."""


@dataclass(frozen=True, slots=True)
class EventProjectionStatusResult:
    status: EventProjectionStatus
    path: Path
    stream_id: str
    tenant_id: str | None
    durable_high_watermark: int | None
    projection_high_watermark: int | None
    projection_event_count: int
    projection_checksum: str
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", EventProjectionStatus(self.status))
        if self.status is EventProjectionStatus.UNAVAILABLE:
            if self.unavailable_reason_class is None:
                raise ValueError("unavailable projection status requires a reason class")
            if self.durable_high_watermark is not None:
                raise ValueError("unavailable projection status has no durable watermark")
        elif self.unavailable_reason_class is not None:
            raise ValueError("available projection status cannot contain an unavailable reason")


@dataclass(frozen=True, slots=True)
class EventProjectionRebuildResult:
    availability: EventServiceAvailability
    path: Path
    stream_id: str
    tenant_id: str | None
    requested_high_watermark: int | None
    durable_high_watermark: int | None
    projection: GraphEventProjection | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.projection is None:
                raise ValueError("available projection rebuild requires a projection")
            if self.unavailable_reason_class is not None:
                raise ValueError("available projection rebuild cannot have a failure reason")
            if self.projection.high_watermark != self.requested_high_watermark:
                raise ValueError("projection did not use the requested high watermark")
            if self.projection.path != self.path:
                raise ValueError("projection exporter changed the application-owned path")
        elif self.projection is not None:
            raise ValueError("unavailable projection rebuild cannot contain a projection")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable projection rebuild requires a reason class")


@dataclass(frozen=True, slots=True)
class _ManifestProjectionMetadata:
    path: Path
    graph_identity: GraphRunIdentity
    high_watermark: Any
    event_count: Any
    checksum: Any
    run_is_active: bool


class EventProjectionService:
    """Build and verify redacted JSONL projections under one artifact root."""

    def __init__(
        self,
        *,
        reader: EventReaderPort,
        authorizer: EventAuthorizerPort,
        artifact_root: str | Path,
        schema_catalog: EventSchemaCatalog,
        security_projector: EventSecurityProjector | None = None,
        page_size: int = 1_000,
        projection: GraphEventProjectionApplicationPort | None = None,
        terminal_manifest_reader: GraphTerminalManifestPort | None = None,
        graph_identity: GraphRunIdentity | None = None,
    ) -> None:
        if reader is None:
            raise ValueError("event reader is required")
        if authorizer is None:
            raise ValueError("event authorizer is required")
        if not isinstance(schema_catalog, EventSchemaCatalog):
            raise TypeError("schema_catalog must be EventSchemaCatalog")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_PAGE_LIMIT
        ):
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_LIMIT}")
        self._reader = reader
        self._authorizer = authorizer
        self._artifact_root = Path(artifact_root).resolve(strict=False)
        self._schema_catalog = schema_catalog
        self._security_projector = security_projector
        self._page_size = page_size
        self._projection = projection or DurableGraphEventProjectionAdapter(
            reader=reader,
            schema_catalog=schema_catalog,
            security_projector=security_projector,
            page_size=page_size,
        )
        if not isinstance(self._projection, GraphEventProjectionApplicationPort):
            raise TypeError(
                "projection must implement GraphEventProjectionApplicationPort"
            )
        if not isinstance(
            terminal_manifest_reader,
            GraphTerminalManifestPort,
        ):
            raise TypeError(
                "terminal_manifest_reader must implement GraphTerminalManifestPort"
            )
        self._terminal_manifest_reader = terminal_manifest_reader
        if graph_identity is not None and not isinstance(
            graph_identity,
            GraphRunIdentity,
        ):
            raise TypeError("graph_identity must be GraphRunIdentity")
        self._default_graph_identity = graph_identity

    def rebuild_run_projection(
        self,
        run_id: str,
        *,
        requested_high_watermark: int | None,
        authorization: EventAuthorizationContext,
        graph_identity: GraphRunIdentity | None = None,
    ) -> EventProjectionRebuildResult:
        safe_run_id, stream_id, target = self._run_scope(run_id)
        requested = _optional_high_watermark(requested_high_watermark)
        identity = (
            graph_identity
            or self._default_graph_identity
            or self._graph_identity_from_manifest(safe_run_id)
        )
        if identity.run_id != safe_run_id:
            raise EventProjectionConflictError("graph_identity_run_conflict")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.PROJECTION_REBUILD,
            target={
                "run_id": safe_run_id,
                "stream_id": stream_id,
                "requested_high_watermark": requested,
                "projection_path": f"{safe_run_id}/events.jsonl",
                "graph_id": identity.graph_id,
                "graph_version": identity.graph_version,
                "graph_checksum": identity.graph_checksum,
            },
        )
        try:
            durable_high_watermark = self._reader.get_stream_high_watermark(
                stream_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return EventProjectionRebuildResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                path=target,
                stream_id=stream_id,
                tenant_id=authorization.tenant_id,
                requested_high_watermark=requested,
                durable_high_watermark=None,
                unavailable_reason_class=type(error).__name__,
            )
        if requested is not None and (
            durable_high_watermark is None or requested > durable_high_watermark
        ):
            raise EventProjectionSourceRangeError(
                "requested projection high watermark exceeds durable history"
            )
        effective_requested = (
            durable_high_watermark if requested is None else requested
        )
        application_request = GraphEventProjectionApplicationRequest(
            graph_identity=identity,
            target=target,
            tenant_id=authorization.tenant_id,
            through_sequence=effective_requested,
        )
        try:
            application_result = self._projection.project_graph_history(
                application_request
            )
        except EventStoreUnavailableError as error:
            return EventProjectionRebuildResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                path=target,
                stream_id=stream_id,
                tenant_id=authorization.tenant_id,
                requested_high_watermark=effective_requested,
                durable_high_watermark=durable_high_watermark,
                unavailable_reason_class=type(error).__name__,
            )
        if (
            application_result.status
            is not GraphEventProjectionApplicationStatus.PROJECTED
            or application_result.projection is None
        ):
            reason = (
                application_result.diagnostic.code.value
                if application_result.diagnostic is not None
                else "graph_history_not_projectable"
            )
            raise EventProjectionConflictError(reason)
        projection = application_result.projection
        if (
            projection.stream_id != stream_id
            or projection.high_watermark != effective_requested
        ):
            raise EventContractError("projection exporter changed the requested source scope")
        return EventProjectionRebuildResult(
            availability=EventServiceAvailability.AVAILABLE,
            path=target,
            stream_id=stream_id,
            tenant_id=authorization.tenant_id,
            requested_high_watermark=effective_requested,
            durable_high_watermark=durable_high_watermark,
            projection=projection,
        )

    def get_run_projection_status(
        self,
        run_id: str,
        *,
        projection_high_watermark: int | None,
        projection_event_count: int | None,
        projection_checksum: str | None,
        run_is_active: bool,
        authorization: EventAuthorizationContext,
    ) -> EventProjectionStatusResult:
        safe_run_id, stream_id, target = self._run_scope(run_id)
        if not isinstance(run_is_active, bool):
            raise TypeError("run_is_active must be a boolean")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.PROJECTION_READ,
            target={
                "run_id": safe_run_id,
                "stream_id": stream_id,
                "projection_path": f"{safe_run_id}/events.jsonl",
                "projection_high_watermark": projection_high_watermark,
                "projection_event_count": projection_event_count,
                "projection_checksum": projection_checksum,
                "run_is_active": run_is_active,
            },
        )
        return self._projection_status(
            stream_id=stream_id,
            target=target,
            tenant_id=authorization.tenant_id,
            projection_high_watermark=projection_high_watermark,
            projection_event_count=projection_event_count,
            projection_checksum=projection_checksum,
            run_is_active=run_is_active,
        )

    def get_run_projection_status_from_manifest(
        self,
        run_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> EventProjectionStatusResult:
        """Read operator status only from server-owned run manifest metadata."""

        safe_run_id, stream_id, target = self._run_scope(run_id)
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.PROJECTION_READ,
            target={
                "run_id": safe_run_id,
                "stream_id": stream_id,
                "projection_path": f"{safe_run_id}/events.jsonl",
                "metadata_source": "run_manifest",
            },
        )
        metadata = self._load_manifest_projection(
            safe_run_id=safe_run_id,
            stream_id=stream_id,
            tenant_id=authorization.tenant_id,
        )
        return self._projection_status(
            stream_id=stream_id,
            target=metadata.path,
            tenant_id=authorization.tenant_id,
            projection_high_watermark=metadata.high_watermark,
            projection_event_count=metadata.event_count,
            projection_checksum=metadata.checksum,
            run_is_active=metadata.run_is_active,
            graph_identity=metadata.graph_identity,
        )

    def _projection_status(
        self,
        *,
        stream_id: str,
        target: Path,
        tenant_id: str | None,
        projection_high_watermark: int | None,
        projection_event_count: int | None,
        projection_checksum: str | None,
        run_is_active: bool,
        graph_identity: GraphRunIdentity | None = None,
    ) -> EventProjectionStatusResult:
        projected = _optional_high_watermark(projection_high_watermark)
        event_count, checksum = _projection_metadata(
            projected,
            projection_event_count,
            projection_checksum,
        )
        try:
            durable = self._reader.get_stream_high_watermark(
                stream_id,
                tenant_id=tenant_id,
            )
        except EventStoreUnavailableError as error:
            return EventProjectionStatusResult(
                status=EventProjectionStatus.UNAVAILABLE,
                path=target,
                stream_id=stream_id,
                tenant_id=tenant_id,
                durable_high_watermark=None,
                projection_high_watermark=projected,
                projection_event_count=event_count,
                projection_checksum=checksum,
                unavailable_reason_class=type(error).__name__,
            )
        if projected is not None and (durable is None or projected > durable):
            raise EventProjectionConflictError("projection_ahead_of_durable_stream")
        if not target.is_file():
            raise EventProjectionConflictError("projection_artifact_missing")
        try:
            identity = (
                graph_identity
                or self._default_graph_identity
                or self._graph_identity_from_manifest(target.parent.name)
            )
            result = self._projection.verify_graph_history(
                GraphEventProjectionApplicationRequest(
                    graph_identity=identity,
                    target=target,
                    tenant_id=tenant_id,
                    through_sequence=projected,
                ),
                event_count=event_count,
                checksum=checksum,
            )
            if (
                result.status is not GraphEventProjectionApplicationStatus.PROJECTED
                or result.projection is None
            ):
                raise EventContractError("Graph event projection history is history-only")
        except EventStoreUnavailableError as error:
            return EventProjectionStatusResult(
                status=EventProjectionStatus.UNAVAILABLE,
                path=target,
                stream_id=stream_id,
                tenant_id=tenant_id,
                durable_high_watermark=None,
                projection_high_watermark=projected,
                projection_event_count=event_count,
                projection_checksum=checksum,
                unavailable_reason_class=type(error).__name__,
            )
        except EventContractError as error:
            raise EventProjectionConflictError("projection_artifact_corrupt") from error
        if projected == durable:
            status = EventProjectionStatus.CURRENT
        elif run_is_active:
            status = EventProjectionStatus.RUNNING
        else:
            status = EventProjectionStatus.STALE
        return EventProjectionStatusResult(
            status=status,
            path=target,
            stream_id=stream_id,
            tenant_id=tenant_id,
            durable_high_watermark=durable,
            projection_high_watermark=projected,
            projection_event_count=event_count,
            projection_checksum=checksum,
        )

    def _load_manifest_projection(
        self,
        *,
        safe_run_id: str,
        stream_id: str,
        tenant_id: str | None,
    ) -> _ManifestProjectionMetadata:
        try:
            manifest = self._terminal_manifest_reader.read_terminal_manifest(
                safe_run_id
            )
        except ArtifactNotFoundError as error:
            raise EventProjectionNotFoundError(
                "run projection is not available"
            ) from error
        except (TypeError, ValueError, OSError) as error:
            raise EventProjectionConflictError("run_manifest_invalid") from error
        if not isinstance(manifest, GraphTerminalManifestV2):
            raise EventProjectionConflictError("run_manifest_invalid")
        if manifest.run_id != safe_run_id:
            raise EventProjectionConflictError("run_manifest_identity_conflict")
        artifact = manifest.artifact("event_projection")
        if artifact is None:
            raise EventProjectionNotFoundError("run projection is not available")
        if artifact.relative_path != "events.jsonl":
            raise EventProjectionConflictError("projection_path_conflict")
        projection_path = resolve_artifact_descendant(
            self._artifact_root,
            safe_run_id,
            artifact.relative_path,
            field="event projection path",
        )
        metadata = artifact.metadata
        if (
            metadata.get("stream_id") != stream_id
            or metadata.get("tenant_id") != manifest.tenant_id
            or metadata.get("checksum") != artifact.content_checksum
            or metadata.get("content_checksum") not in (None, artifact.content_checksum)
        ):
            raise EventProjectionConflictError("projection_metadata_conflict")
        identity = GraphRunIdentity(
            run_id=manifest.run_id,
            graph_id=manifest.graph_id,
            graph_version=manifest.graph_version,
            graph_ref=f"{manifest.graph_id}@{manifest.graph_version}",
            graph_checksum=manifest.normalized_graph_checksum,
        )
        if metadata.get("graph_identity") not in (None, identity.to_dict()):
            raise EventProjectionConflictError("projection_graph_identity_conflict")
        if tenant_id is None or manifest.tenant_id != tenant_id:
            raise EventProjectionNotFoundError("run projection is not available")
        status = manifest.status.value
        _projection_metadata(
            metadata.get("high_watermark"),
            metadata.get("event_count"),
            artifact.content_checksum,
        )
        return _ManifestProjectionMetadata(
            path=projection_path,
            graph_identity=identity,
            high_watermark=metadata.get("high_watermark"),
            event_count=metadata.get("event_count"),
            checksum=artifact.content_checksum,
            run_is_active=_run_is_active(status),
        )

    def _run_scope(self, run_id: str) -> tuple[str, str, Path]:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        target = resolve_artifact_descendant(
            self._artifact_root,
            safe_run_id,
            "events.jsonl",
            field="event projection path",
        )
        return safe_run_id, f"run:{safe_run_id}", target

    def _graph_identity_from_manifest(self, run_id: str) -> GraphRunIdentity:
        manifest = self._terminal_manifest_reader.read_terminal_manifest(run_id)
        if not isinstance(manifest, GraphTerminalManifestV2):
            raise EventProjectionConflictError("run_manifest_invalid")
        return GraphRunIdentity(
            run_id=manifest.run_id,
            graph_id=manifest.graph_id,
            graph_version=manifest.graph_version,
            graph_ref=f"{manifest.graph_id}@{manifest.graph_version}",
            graph_checksum=manifest.normalized_graph_checksum,
        )


def _projection_metadata(
    high_watermark: int | None,
    event_count: Any,
    checksum: Any,
) -> tuple[int, str]:
    if event_count is None or checksum is None:
        raise EventProjectionConflictError("projection_metadata_partial")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
        raise EventProjectionConflictError("projection_event_count_invalid")
    expected_count = 0 if high_watermark is None else high_watermark
    if event_count != expected_count:
        raise EventProjectionConflictError("projection_metadata_partial")
    if not isinstance(checksum, str):
        raise EventProjectionConflictError("projection_checksum_invalid")
    prefix, separator, digest = checksum.partition(":")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise EventProjectionConflictError("projection_checksum_invalid")
    return event_count, checksum


def _optional_high_watermark(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EventProjectionConflictError("projection_high_watermark_invalid")
    return value


def _run_is_active(value: str) -> bool:
    return value.strip().casefold() in {
        "created",
        "draft",
        "ready",
        "running",
        "retrying",
        "paused",
        "waiting_for_human",
    }


__all__ = [
    "EventProjectionConflictError",
    "EventProjectionNotFoundError",
    "EventProjectionRebuildResult",
    "EventProjectionService",
    "EventProjectionSourceRangeError",
    "EventProjectionStatus",
    "EventProjectionStatusResult",
]
