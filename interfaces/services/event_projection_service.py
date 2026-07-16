from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from framework.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.ports import EventReaderPort
from framework.events.runtime.models import MAX_PAGE_LIMIT, EventPage, StreamReadRequest
from framework.events.schema.catalog import EventSchemaCatalog
from framework.events.schema.security import EventSecurityProjector
from framework.workflow.runtime.event_projection import (
    WorkflowEventProjection,
    WorkflowEventProjectionExporter,
)
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


MAX_RUN_MANIFEST_BYTES = 1_048_576


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
    projection: WorkflowEventProjection | None = None
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

    def rebuild_run_projection(
        self,
        run_id: str,
        *,
        requested_high_watermark: int | None,
        authorization: EventAuthorizationContext,
    ) -> EventProjectionRebuildResult:
        safe_run_id, stream_id, target = self._run_scope(run_id)
        requested = _optional_high_watermark(requested_high_watermark)
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.PROJECTION_REBUILD,
            target={
                "run_id": safe_run_id,
                "stream_id": stream_id,
                "requested_high_watermark": requested,
                "projection_path": f"{safe_run_id}/events.jsonl",
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
        exporter = self._exporter(
            _PinnedPrefixReader(
                reader=self._reader,
                stream_id=stream_id,
                tenant_id=authorization.tenant_id,
                high_watermark=requested,
            )
        )
        try:
            projection = exporter.export(
                stream_id=stream_id,
                target=target,
                tenant_id=authorization.tenant_id,
                through_sequence=requested,
            )
        except EventStoreUnavailableError as error:
            return EventProjectionRebuildResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                path=target,
                stream_id=stream_id,
                tenant_id=authorization.tenant_id,
                requested_high_watermark=requested,
                durable_high_watermark=durable_high_watermark,
                unavailable_reason_class=type(error).__name__,
            )
        if projection.stream_id != stream_id or projection.high_watermark != requested:
            raise EventContractError("projection exporter changed the requested source scope")
        return EventProjectionRebuildResult(
            availability=EventServiceAvailability.AVAILABLE,
            path=target,
            stream_id=stream_id,
            tenant_id=authorization.tenant_id,
            requested_high_watermark=requested,
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
            target=target,
            tenant_id=authorization.tenant_id,
            projection_high_watermark=metadata.high_watermark,
            projection_event_count=metadata.event_count,
            projection_checksum=metadata.checksum,
            run_is_active=metadata.run_is_active,
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
            self._exporter(self._reader).verify_existing(
                stream_id=stream_id,
                target=target,
                high_watermark=projected,
                event_count=event_count,
                checksum=checksum,
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
        manifest_path = resolve_artifact_descendant(
            self._artifact_root,
            safe_run_id,
            "manifest.json",
            field="run manifest path",
        )
        if not manifest_path.exists():
            raise EventProjectionNotFoundError("run projection is not available")
        if not manifest_path.is_file():
            raise EventProjectionConflictError("run_manifest_not_regular_file")
        try:
            if manifest_path.stat().st_size > MAX_RUN_MANIFEST_BYTES:
                raise EventProjectionConflictError("run_manifest_too_large")
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except EventProjectionConflictError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EventProjectionConflictError("run_manifest_invalid") from error
        if not isinstance(raw_manifest, Mapping):
            raise EventProjectionConflictError("run_manifest_invalid")
        manifest = dict(raw_manifest)
        if manifest.get("run_id") != safe_run_id:
            raise EventProjectionConflictError("run_manifest_identity_conflict")
        raw_projection = manifest.get("event_projection")
        if not isinstance(raw_projection, Mapping):
            raise EventProjectionConflictError("projection_metadata_missing")
        projection = dict(raw_projection)
        if projection.get("path") != "events.jsonl":
            raise EventProjectionConflictError("projection_path_conflict")
        if projection.get("stream_id") != stream_id:
            raise EventProjectionConflictError("projection_stream_conflict")
        self._validate_manifest_tenant_scope(
            manifest=manifest,
            projection=projection,
            stream_id=stream_id,
            tenant_id=tenant_id,
        )
        _validate_legacy_projection_duplicates(manifest, projection)
        status = manifest.get("status")
        if not isinstance(status, str) or not status.strip():
            raise EventProjectionConflictError("run_manifest_status_missing")
        return _ManifestProjectionMetadata(
            high_watermark=projection.get("high_watermark"),
            event_count=projection.get("event_count"),
            checksum=projection.get("checksum"),
            run_is_active=_run_is_active(status),
        )

    def _validate_manifest_tenant_scope(
        self,
        *,
        manifest: Mapping[str, Any],
        projection: Mapping[str, Any],
        stream_id: str,
        tenant_id: str | None,
    ) -> None:
        declared = [
            value
            for container in (manifest, projection)
            if "tenant_id" in container
            for value in (container.get("tenant_id"),)
        ]
        if not declared:
            if tenant_id is None:
                raise EventProjectionNotFoundError("run projection is not available")
            durable = self._reader.get_stream_high_watermark(
                stream_id,
                tenant_id=tenant_id,
            )
            if (
                durable is None
                or isinstance(durable, bool)
                or not isinstance(durable, int)
                or durable < 1
            ):
                raise EventProjectionNotFoundError("run projection is not available")
            return
        if any(not isinstance(value, str) or not value.strip() for value in declared):
            raise EventProjectionConflictError("manifest_tenant_scope_invalid")
        normalized = tuple(str(value).strip() for value in declared)
        if len(set(normalized)) != 1:
            raise EventProjectionConflictError("manifest_tenant_scope_conflict")
        if tenant_id is None or normalized[0] != tenant_id:
            raise EventProjectionNotFoundError("run projection is not available")

    def _run_scope(self, run_id: str) -> tuple[str, str, Path]:
        safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
        target = resolve_artifact_descendant(
            self._artifact_root,
            safe_run_id,
            "events.jsonl",
            field="event projection path",
        )
        return safe_run_id, f"run:{safe_run_id}", target

    def _exporter(self, reader: EventReaderPort) -> WorkflowEventProjectionExporter:
        return WorkflowEventProjectionExporter(
            reader=reader,
            schema_catalog=self._schema_catalog,
            security_projector=self._security_projector,
            page_size=self._page_size,
        )


@dataclass(frozen=True, slots=True)
class _PinnedPrefixReader:
    reader: EventReaderPort
    stream_id: str
    tenant_id: str | None
    high_watermark: int | None

    def get_event(self, event_id: str, *, tenant_id: str | None = None):
        if tenant_id != self.tenant_id:
            raise EventContractError("projection reader crossed the tenant scope")
        return self.reader.get_event(event_id, tenant_id=tenant_id)

    def get_stream_high_watermark(
        self,
        stream_id: str,
        *,
        tenant_id: str | None = None,
    ) -> int | None:
        self._require_scope(stream_id, tenant_id)
        return self.high_watermark

    def read_stream(self, request: StreamReadRequest) -> EventPage:
        self._require_scope(request.stream_id, request.tenant_id)
        if request.through_sequence != self.high_watermark:
            raise EventContractError("projection reader changed the pinned high watermark")
        page = self.reader.read_stream(request)
        if page.high_watermark != self.high_watermark:
            raise EventContractError("event reader changed the projection high watermark")
        return page

    def _require_scope(self, stream_id: str, tenant_id: str | None) -> None:
        if stream_id != self.stream_id or tenant_id != self.tenant_id:
            raise EventContractError("projection reader crossed the requested stream scope")


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


def _validate_legacy_projection_duplicates(
    manifest: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> None:
    aliases = {
        "event_projection_high_watermark": "high_watermark",
        "event_projection_checksum": "checksum",
        "event_count": "event_count",
    }
    if any(
        manifest.get(manifest_key) != projection.get(projection_key)
        for manifest_key, projection_key in aliases.items()
        if manifest_key in manifest
    ):
        raise EventProjectionConflictError("projection_metadata_conflict")


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
