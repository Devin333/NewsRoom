from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any

from framework.artifacts.paths import (
    ArtifactPathError,
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.shared.json import to_jsonable as to_json_safe
from framework.events.errors import EventStoreUnavailableError
from framework.events.canonical import checksum_for
from framework.events.runtime.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    StreamSequenceCursor,
)
from framework.events.schema import EventSchemaCatalog, default_event_schema_catalog
from framework.workflow.inspection import (
    WorkflowArtifactContentRecord,
    WorkflowReplayContentBundle,
    WorkflowRunInspectionError,
    WorkflowRunInspector,
    WorkflowRunListItem,
    redact_sensitive_values,
)
from framework.workflow.runtime.event_projection import project_workflow_event
from framework.workflow.runtime.manifest import normalize_legacy_run_manifest
from interfaces.services.event_projection_service import (
    EventProjectionConflictError,
    EventProjectionService,
    EventProjectionStatus,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventReaderService,
    EventServiceAvailability,
    EventStreamReadResult,
)
from interfaces.services.run_inspection_projection import project_manifest_output_preview


_MAX_PROJECTION_LINE_BYTES = 256 * 1024


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    workflow_id: str | None = None
    workflow_version: str | None = None
    profile: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    report_id: str | None = None
    artifact_dir: str | None = None
    quality_score: float | None = None
    step_count: int | None = None
    event_count: int | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "profile": self.profile,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_id": self.report_id,
            "artifact_dir": self.artifact_dir,
            "quality_score": self.quality_score,
            "step_count": self.step_count,
            "event_count": self.event_count,
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class RunListResult:
    runs: list[RunSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"run_count": len(self.runs), "runs": [run.to_dict() for run in self.runs]}


@dataclass(frozen=True)
class RunDetail:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    artifact_dir: str | None = None
    output_preview: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.manifest.get("workflow_id"),
            "workflow_version": self.manifest.get("workflow_version"),
            "profile": self.manifest.get("profile"),
            "status": self.manifest.get("status"),
            "started_at": self.manifest.get("started_at"),
            "finished_at": self.manifest.get("finished_at"),
            "report_id": _manifest_report_id(self.manifest),
            "artifact_dir": self.artifact_dir,
            "output_preview": to_json_safe(self.output_preview or {}),
            "error": to_json_safe(self.error),
            "metrics": to_json_safe(self.metrics or {}),
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True)
class RunEventsResult:
    run_id: str
    events: list[dict[str, Any]]
    events_path: str | None
    next_sequence_cursor: str | None = None
    high_watermark: int | None = None
    source: str = "durable_store"
    projection_status: str = "unavailable"
    projection_checksum: str | None = None
    projection_high_watermark: int | None = None
    availability: str = "available"
    unavailable_reason_class: str | None = None
    sse_resume_cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id is required")
        if self.source not in {"durable_store", "projection"}:
            raise ValueError("source must be durable_store or projection")
        if self.projection_status not in {
            status.value for status in EventProjectionStatus
        }:
            raise ValueError("projection_status is invalid")
        if self.availability not in {
            status.value for status in EventServiceAvailability
        }:
            raise ValueError("availability is invalid")
        if self.availability == EventServiceAvailability.AVAILABLE.value:
            if self.source != "durable_store":
                raise ValueError("available event results require durable_store source")
            if self.unavailable_reason_class is not None:
                raise ValueError("available event results cannot contain a failure reason")
        else:
            if self.unavailable_reason_class is None:
                raise ValueError("unavailable event results require a reason class")
            if self.next_sequence_cursor is not None:
                raise ValueError("projection fallback cannot issue a durable cursor")
            if self.sse_resume_cursor is not None:
                raise ValueError("projection fallback cannot issue an SSE resume cursor")
        if self.high_watermark is not None and (
            isinstance(self.high_watermark, bool)
            or not isinstance(self.high_watermark, int)
            or self.high_watermark < 0
        ):
            raise ValueError("high_watermark must be a non-negative integer")
        if self.projection_high_watermark is not None and (
            isinstance(self.projection_high_watermark, bool)
            or not isinstance(self.projection_high_watermark, int)
            or self.projection_high_watermark < 0
        ):
            raise ValueError("projection_high_watermark must be a non-negative integer")
        if self.projection_checksum is not None and not _is_checksum(
            self.projection_checksum
        ):
            raise ValueError("projection_checksum is invalid")
        if self.source == "projection" and self.high_watermark is not None:
            raise ValueError("projection fallback has no authoritative high watermark")
        for event in self.events:
            if not isinstance(event, dict):
                raise TypeError("events must contain dictionaries")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
            "next_sequence_cursor": self.next_sequence_cursor,
            "high_watermark": self.high_watermark,
            "source": self.source,
            "projection_status": self.projection_status,
            "projection_checksum": self.projection_checksum,
            "projection_high_watermark": self.projection_high_watermark,
            "availability": self.availability,
            "unavailable_reason_class": self.unavailable_reason_class,
            "sse_resume_cursor": self.sse_resume_cursor,
        }


@dataclass(frozen=True)
class RunStepsResult:
    run_id: str
    steps: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_count": len(self.steps),
            "steps": [to_json_safe(step) for step in self.steps],
        }


@dataclass(frozen=True)
class RunReplayArtifact:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    content: Any = None
    read_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "content": self.content,
            "read_error": self.read_error,
            "metadata": to_json_safe(self.metadata),
        }


@dataclass(frozen=True)
class RunReplayResult:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    events: list[dict[str, Any]]
    events_path: str | None
    artifacts: list[RunReplayArtifact]
    step_results: dict[str, Any]
    integrity: dict[str, Any]
    events_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
            "event_count": len(self.events),
            "events": [dict(event) for event in self.events],
            "events_path": self.events_path,
            "events_error": self.events_error,
            "artifact_count": len(self.artifacts),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "step_result_count": len(self.step_results),
            "step_results": to_json_safe(self.step_results),
            "integrity": to_json_safe(self.integrity),
        }


@dataclass(frozen=True)
class RunDiagnosticsResult:
    run_id: str
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "diagnostics": to_json_safe(self.diagnostics),
        }


@dataclass(frozen=True)
class RunHealthResult:
    run_id: str
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "health": to_json_safe(self.health),
        }


@dataclass(frozen=True)
class RunCatalogHealthResult:
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"health": to_json_safe(self.health)}


@dataclass(frozen=True)
class RunComparisonResult:
    base_run_id: str
    target_run_id: str
    comparison: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_run_id": self.base_run_id,
            "target_run_id": self.target_run_id,
            "comparison": to_json_safe(self.comparison),
        }


class RunInspectionService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        event_reader_service: EventReaderService | None = None,
        event_projection_service: EventProjectionService | None = None,
        event_authorization: EventAuthorizationContext | None = None,
        event_schema_catalog: EventSchemaCatalog | None = None,
        event_services_factory: Callable[
            [],
            tuple[
                EventReaderService,
                EventProjectionService,
                EventAuthorizationContext,
                EventSchemaCatalog,
            ],
        ]
        | None = None,
        allow_stale_projection: bool = True,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self._inspector = WorkflowRunInspector(self.artifact_root)
        self._event_reader_service = event_reader_service
        self._event_projection_service = event_projection_service
        self._event_authorization = event_authorization or EventAuthorizationContext(
            principal_id="local-run-inspection",
            tenant_id=None,
            authentication_evidence_ref="authn://local/run-inspection",
        )
        self._event_schema_catalog = event_schema_catalog or default_event_schema_catalog()
        self._event_services_factory = event_services_factory
        self._event_services_lock = Lock()
        self._durable_event_reader_expected = (
            event_reader_service is not None or event_services_factory is not None
        )
        self._allow_stale_projection = bool(allow_stale_projection)
        self._event_store_unavailable_reason_class: str | None = None
        if event_projection_service is not None and event_reader_service is None:
            raise ValueError("event projection service requires an event reader service")
        if event_services_factory is not None and (
            event_reader_service is not None or event_projection_service is not None
        ):
            raise ValueError("lazy event services cannot be combined with configured services")

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        workflow_id: str | None = None,
        profile: str | None = None,
    ) -> RunListResult:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        catalog = self._inspector.list_runs(
            limit=limit,
            offset=offset,
            status=status,
            workflow_id=workflow_id,
            profile=profile,
            include_invalid=True,
        )
        return RunListResult(
            [
                _summary_from_run_item(item)
                for item in catalog.runs
                if not _is_unreadable_manifest(item)
            ]
        )

    def get_run(self, run_id: str) -> RunDetail:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        manifest_path = _run_manifest_path(run_dir)
        if not manifest_path.exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        manifest = normalize_legacy_run_manifest(self._inspector.load_manifest(run_dir))
        return RunDetail(
            run_id=str(manifest.get("run_id") or run_id),
            manifest=manifest,
            manifest_path=str(manifest_path),
            artifact_dir=str(run_dir),
            output_preview=_manifest_output_preview(manifest),
            error=_manifest_error(manifest),
            metrics=_manifest_metrics(manifest),
        )

    def get_run_events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        step_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ) -> RunEventsResult:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        if limit is not None and limit > MAX_PAGE_LIMIT:
            raise ValueError(f"limit must be less than or equal to {MAX_PAGE_LIMIT}")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        if sequence_cursor is not None and offset:
            raise ValueError("offset and sequence_cursor cannot be combined")
        detail = self.get_run(run_id)
        self._ensure_event_services()
        if self._event_reader_service is not None:
            result = self._read_durable_events(
                detail,
                event_type=event_type,
                step_id=step_id,
                limit=limit,
                offset=offset,
                sequence_cursor=sequence_cursor,
            )
            if result is not None:
                return result
        return self._read_stale_projection(
            detail,
            event_type=event_type,
            step_id=step_id,
            limit=limit,
            offset=offset,
            sequence_cursor=sequence_cursor,
        )

    def get_run_events_for_sse(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        sequence_cursor: str | None = None,
        last_event_id: str | None = None,
    ) -> RunEventsResult:
        """Read the current durable tail after an SSE resume position."""

        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        if limit is not None and limit > MAX_PAGE_LIMIT:
            raise ValueError(f"limit must be less than or equal to {MAX_PAGE_LIMIT}")
        if sequence_cursor is not None and last_event_id is not None:
            raise ValueError("sequence_cursor and Last-Event-ID cannot be combined")
        detail = self.get_run(run_id)
        self._ensure_event_services()
        if self._event_reader_service is None:
            return self._read_stale_projection(
                detail,
                event_type=None,
                step_id=None,
                limit=limit,
                offset=0,
                sequence_cursor=(sequence_cursor or last_event_id),
            )
        if sequence_cursor is not None:
            result = self._read_durable_events(
                detail,
                event_type=None,
                step_id=None,
                limit=limit,
                offset=0,
                sequence_cursor=sequence_cursor,
            )
            if result is None:
                return self._read_stale_projection(
                    detail,
                    event_type=None,
                    step_id=None,
                    limit=limit,
                    offset=0,
                    sequence_cursor=sequence_cursor,
                )
            return _with_sse_resume_cursors(
                result,
                stream_id=f"run:{detail.run_id}",
                tenant_id=self._event_authorization.tenant_id,
            )

        after_sequence = (
            0
            if last_event_id is None
            else _decode_sse_resume_cursor(
                last_event_id,
                run_id=detail.run_id,
                tenant_id=self._event_authorization.tenant_id,
            )
        )
        watermark = self._event_reader_service.get_high_watermark(
            f"run:{detail.run_id}",
            authorization=self._event_authorization,
        )
        if watermark.availability is EventServiceAvailability.UNAVAILABLE:
            self._event_store_unavailable_reason_class = watermark.unavailable_reason_class
            return self._read_stale_projection(
                detail,
                event_type=None,
                step_id=None,
                limit=limit,
                offset=0,
                sequence_cursor=last_event_id,
            )
        high_watermark = watermark.high_watermark
        if high_watermark is None and after_sequence:
            raise ValueError("Last-Event-ID does not exist in the durable stream")
        if high_watermark is not None and after_sequence > high_watermark:
            raise ValueError("Last-Event-ID is ahead of the durable stream")
        if high_watermark is None or after_sequence >= high_watermark:
            page = EventStreamReadResult(
                availability=EventServiceAvailability.AVAILABLE,
                stream_id=f"run:{detail.run_id}",
                tenant_id=self._event_authorization.tenant_id,
                high_watermark=high_watermark,
            )
        else:
            cursor = (
                None
                if after_sequence == 0
                else StreamSequenceCursor(
                    stream_id=f"run:{detail.run_id}",
                    tenant_id=self._event_authorization.tenant_id,
                    after_sequence=after_sequence,
                    high_watermark=high_watermark,
                )
            )
            page = self._event_reader_service.read_run_events(
                detail.run_id,
                authorization=self._event_authorization,
                cursor=cursor,
                limit=limit or DEFAULT_PAGE_LIMIT,
                through_sequence=high_watermark,
            )
            if page.availability is EventServiceAvailability.UNAVAILABLE:
                self._event_store_unavailable_reason_class = page.unavailable_reason_class
                return self._read_stale_projection(
                    detail,
                    event_type=None,
                    step_id=None,
                    limit=limit,
                    offset=0,
                    sequence_cursor=last_event_id,
                )
        projection = self._projection_metadata(detail)
        projection_status = self._durable_projection_status(
            detail,
            durable_high_watermark=high_watermark,
            projection=projection,
        )
        events = [
            project_workflow_event(
                event,
                schema_catalog=self._event_schema_catalog,
            )
            for event in page.events
        ]
        result = RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=projection["path"],
            next_sequence_cursor=(
                None
                if page.next_cursor is None
                else _encode_sequence_cursor(page.next_cursor)
            ),
            high_watermark=high_watermark,
            source="durable_store",
            projection_status=projection_status.value,
            projection_checksum=projection["checksum"],
            projection_high_watermark=projection["high_watermark"],
            availability=EventServiceAvailability.AVAILABLE.value,
        )
        return _with_sse_resume_cursors(
            result,
            stream_id=f"run:{detail.run_id}",
            tenant_id=self._event_authorization.tenant_id,
            fallback_after_sequence=after_sequence,
        )

    def _read_durable_events(
        self,
        detail: RunDetail,
        *,
        event_type: str | None,
        step_id: str | None,
        limit: int | None,
        offset: int,
        sequence_cursor: str | None,
    ) -> RunEventsResult | None:
        assert self._event_reader_service is not None
        cursor = (
            None
            if sequence_cursor is None
            else _decode_sequence_cursor(
                sequence_cursor,
                run_id=detail.run_id,
                tenant_id=self._event_authorization.tenant_id,
            )
        )
        page = self._read_durable_page(
            detail.run_id,
            event_type=event_type,
            step_id=step_id,
            result_limit=limit or DEFAULT_PAGE_LIMIT,
            legacy_offset=offset,
            cursor=cursor,
        )
        if page.availability is EventServiceAvailability.UNAVAILABLE:
            self._event_store_unavailable_reason_class = page.unavailable_reason_class
            return None
        projection = self._projection_metadata(detail)
        projection_status = self._durable_projection_status(
            detail,
            durable_high_watermark=page.high_watermark,
            projection=projection,
        )
        events = [
            project_workflow_event(
                event,
                schema_catalog=self._event_schema_catalog,
            )
            for event in page.events
        ]
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=projection["path"],
            next_sequence_cursor=(
                None
                if page.next_cursor is None
                else _encode_sequence_cursor(page.next_cursor)
            ),
            high_watermark=page.high_watermark,
            source="durable_store",
            projection_status=projection_status.value,
            projection_checksum=projection["checksum"],
            projection_high_watermark=projection["high_watermark"],
            availability=EventServiceAvailability.AVAILABLE.value,
        )

    def _read_durable_page(
        self,
        run_id: str,
        *,
        event_type: str | None,
        step_id: str | None,
        result_limit: int,
        legacy_offset: int,
        cursor: StreamSequenceCursor | None,
    ) -> EventStreamReadResult:
        assert self._event_reader_service is not None
        remaining_offset = legacy_offset
        current_cursor = cursor
        while True:
            request_limit = min(
                MAX_PAGE_LIMIT,
                max(1, remaining_offset + result_limit),
            )
            page = self._event_reader_service.read_run_events(
                run_id,
                authorization=self._event_authorization,
                cursor=current_cursor,
                limit=request_limit,
                event_types=(frozenset({event_type}) if event_type is not None else frozenset()),
                step_id=step_id,
            )
            if page.availability is EventServiceAvailability.UNAVAILABLE:
                return page
            if remaining_offset >= len(page.events):
                remaining_offset -= len(page.events)
                if page.next_cursor is None:
                    return EventStreamReadResult(
                        availability=EventServiceAvailability.AVAILABLE,
                        stream_id=page.stream_id,
                        tenant_id=page.tenant_id,
                        high_watermark=page.high_watermark,
                    )
                current_cursor = page.next_cursor
                continue
            selected = page.events[remaining_offset : remaining_offset + result_limit]
            selected_end = remaining_offset + len(selected)
            if selected and selected_end < len(page.events):
                assert page.high_watermark is not None
                next_cursor = StreamSequenceCursor(
                    stream_id=page.stream_id,
                    tenant_id=page.tenant_id,
                    after_sequence=selected[-1].stream_sequence,
                    high_watermark=page.high_watermark,
                )
            else:
                next_cursor = page.next_cursor
            return EventStreamReadResult(
                availability=EventServiceAvailability.AVAILABLE,
                stream_id=page.stream_id,
                tenant_id=page.tenant_id,
                events=selected,
                high_watermark=page.high_watermark,
                next_cursor=next_cursor,
            )

    def _read_stale_projection(
        self,
        detail: RunDetail,
        *,
        event_type: str | None,
        step_id: str | None,
        limit: int | None,
        offset: int,
        sequence_cursor: str | None,
    ) -> RunEventsResult:
        if not self._allow_stale_projection:
            raise EventStoreUnavailableError("durable event store is unavailable")
        if not self._durable_event_reader_expected:
            return self._read_legacy_projection(
                detail,
                event_type=event_type,
                step_id=step_id,
                limit=limit,
                offset=offset,
                sequence_cursor=sequence_cursor,
            )
        projection = self._projection_metadata(detail)
        artifacts = detail.manifest.get("artifacts") or {}
        if "events" not in artifacts:
            return self._unavailable_projection_result(detail, projection)
        try:
            events = _read_verified_projection_events(
                path=projection["path"],
                run_id=detail.run_id,
                tenant_id=self._event_authorization.tenant_id,
                high_watermark=projection["high_watermark"],
                event_count=projection["event_count"],
                checksum=projection["checksum"],
                event_type=event_type,
                step_id=step_id,
                offset=offset,
                limit=(0 if sequence_cursor is not None else limit or DEFAULT_PAGE_LIMIT),
            )
        except EventProjectionConflictError:
            return self._unavailable_projection_result(
                detail,
                projection,
                reason_class=EventProjectionConflictError.__name__,
            )
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=projection["path"],
            high_watermark=None,
            source="projection",
            projection_status=EventProjectionStatus.STALE.value,
            projection_checksum=projection["checksum"],
            projection_high_watermark=projection["high_watermark"],
            availability=EventServiceAvailability.UNAVAILABLE.value,
            unavailable_reason_class=(
                self._event_store_unavailable_reason_class
                or EventStoreUnavailableError.__name__
            ),
        )

    def _read_legacy_projection(
        self,
        detail: RunDetail,
        *,
        event_type: str | None,
        step_id: str | None,
        limit: int | None,
        offset: int,
        sequence_cursor: str | None,
    ) -> RunEventsResult:
        projection = self._projection_metadata(detail)
        artifacts = detail.manifest.get("artifacts") or {}
        if "events" not in artifacts:
            return self._unavailable_projection_result(detail, projection)
        run_dir = _resolve_run_dir_for_service(self.artifact_root, detail.run_id)
        try:
            event_records = self._inspector.read_events(run_dir, manifest=detail.manifest)
            events = [redact_sensitive_values(event.to_dict()) for event in event_records]
            events_path = self._inspector.artifact_path(
                run_dir,
                "events",
                manifest=detail.manifest,
            )
        except WorkflowRunInspectionError as error:
            if "not found" in str(error):
                return self._unavailable_projection_result(detail, projection)
            if isinstance(error.__cause__, ArtifactPathError):
                raise ArtifactPathError(str(error)) from error
            raise ValueError(str(error)) from error
        if sequence_cursor is not None:
            events = []
        else:
            events = [
                event
                for event in events
                if _event_matches(event, event_type=event_type, step_id=step_id)
            ]
            if offset:
                events = events[offset:]
            events = events[: limit or DEFAULT_PAGE_LIMIT]
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=str(events_path),
            source="projection",
            projection_status=EventProjectionStatus.STALE.value,
            projection_checksum=projection["checksum"],
            projection_high_watermark=projection["high_watermark"],
            availability=EventServiceAvailability.UNAVAILABLE.value,
            unavailable_reason_class=(
                self._event_store_unavailable_reason_class
                or EventStoreUnavailableError.__name__
            ),
        )

    def _unavailable_projection_result(
        self,
        detail: RunDetail,
        projection: Mapping[str, Any],
        *,
        reason_class: str | None = None,
    ) -> RunEventsResult:
        return RunEventsResult(
            run_id=detail.run_id,
            events=[],
            events_path=projection.get("path"),
            source="projection",
            projection_status=EventProjectionStatus.UNAVAILABLE.value,
            projection_checksum=projection.get("checksum"),
            projection_high_watermark=projection.get("high_watermark"),
            availability=EventServiceAvailability.UNAVAILABLE.value,
            unavailable_reason_class=(
                reason_class
                or self._event_store_unavailable_reason_class
                or EventStoreUnavailableError.__name__
            ),
        )

    def _ensure_event_services(self) -> None:
        if self._event_reader_service is not None or self._event_services_factory is None:
            return
        with self._event_services_lock:
            if self._event_reader_service is not None or self._event_services_factory is None:
                return
            try:
                reader, projection, authorization, catalog = self._event_services_factory()
            except EventStoreUnavailableError as error:
                self._event_store_unavailable_reason_class = type(error).__name__
                return
            if not isinstance(reader, EventReaderService):
                raise TypeError("lazy event reader must be an EventReaderService")
            if not isinstance(projection, EventProjectionService):
                raise TypeError("lazy event projection must be an EventProjectionService")
            if not isinstance(authorization, EventAuthorizationContext):
                raise TypeError("lazy event authorization is invalid")
            if not isinstance(catalog, EventSchemaCatalog):
                raise TypeError("lazy event schema catalog is invalid")
            self._event_reader_service = reader
            self._event_projection_service = projection
            self._event_authorization = authorization
            self._event_schema_catalog = catalog
            self._event_services_factory = None

    def _projection_metadata(self, detail: RunDetail) -> dict[str, Any]:
        manifest = detail.manifest
        raw_projection = manifest.get("event_projection")
        projection = (
            dict(raw_projection) if isinstance(raw_projection, Mapping) else {}
        )
        artifacts = manifest.get("artifacts")
        artifact_map = dict(artifacts) if isinstance(artifacts, Mapping) else {}
        relative_path = projection.get("path") or artifact_map.get("events")
        path: str | None = None
        if isinstance(relative_path, str) and relative_path.strip():
            run_dir = _resolve_run_dir_for_service(self.artifact_root, detail.run_id)
            path = str(
                resolve_artifact_descendant(
                    run_dir,
                    relative_path,
                    field="events projection path",
                )
            )
        high_watermark = projection.get(
            "high_watermark",
            manifest.get("event_projection_high_watermark"),
        )
        if high_watermark is not None and (
            isinstance(high_watermark, bool)
            or not isinstance(high_watermark, int)
            or high_watermark < 1
        ):
            high_watermark = None
        event_count = projection.get("event_count", manifest.get("event_count"))
        if event_count is not None and (
            isinstance(event_count, bool)
            or not isinstance(event_count, int)
            or event_count < 0
        ):
            event_count = None
        checksum = projection.get(
            "checksum",
            manifest.get("event_projection_checksum"),
        )
        if not _is_checksum(checksum):
            checksum = None
        return {
            "path": path,
            "high_watermark": high_watermark,
            "event_count": event_count,
            "checksum": checksum,
        }

    def _durable_projection_status(
        self,
        detail: RunDetail,
        *,
        durable_high_watermark: int | None,
        projection: Mapping[str, Any],
    ) -> EventProjectionStatus:
        if (
            self._event_projection_service is None
            or projection.get("path") is None
            or projection.get("event_count") is None
            or projection.get("checksum") is None
        ):
            return EventProjectionStatus.UNAVAILABLE
        status = self._event_projection_service.get_run_projection_status(
            detail.run_id,
            projection_high_watermark=projection.get("high_watermark"),
            projection_event_count=projection.get("event_count"),
            projection_checksum=projection.get("checksum"),
            run_is_active=_run_is_active(detail.manifest.get("status")),
            authorization=self._event_authorization,
        )
        return status.status

    def get_run_steps(self, run_id: str) -> RunStepsResult:
        detail = self.get_run(run_id)
        manifest_steps = detail.manifest.get("steps") or {}
        if not isinstance(manifest_steps, dict):
            raise ValueError(f"invalid steps manifest for run: {run_id}")
        path = [str(step_id) for step_id in detail.manifest.get("path", [])]
        steps = [
            _step_view(step_id, payload, sequence=path.index(step_id) if step_id in path else None)
            for step_id, payload in sorted(manifest_steps.items())
        ]
        steps.sort(key=lambda step: (step["sequence"] is None, step["sequence"] or 0, step["step_id"]))
        return RunStepsResult(run_id=detail.run_id, steps=steps)

    def replay_run(self, run_id: str) -> RunReplayResult:
        run_dir = _resolve_run_dir_for_service(self.artifact_root, run_id)
        if not _run_manifest_path(run_dir).exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        bundle = self._inspector.build_replay_content_bundle(
            run_dir=run_dir,
            redact=True,
            strict_artifact_integrity=True,
        )
        return _replay_result_from_content_bundle(bundle)

    def get_run_diagnostics(self, run_id: str) -> RunDiagnosticsResult:
        run_dir = _existing_run_dir(self.artifact_root, run_id)
        try:
            diagnostics = self._inspector.build_diagnostics(run_dir=run_dir)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunDiagnosticsResult(
            run_id=str(diagnostics.inspection.run_id or run_id),
            diagnostics=diagnostics.to_dict(),
        )

    def get_run_health(self, run_id: str) -> RunHealthResult:
        run_dir = _existing_run_dir(self.artifact_root, run_id)
        try:
            health = self._inspector.build_health_report(run_dir=run_dir)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunHealthResult(
            run_id=str(health.run_id or run_id),
            health=health.to_dict(),
        )

    def get_catalog_health(self) -> RunCatalogHealthResult:
        return RunCatalogHealthResult(self._inspector.catalog_health().to_dict())

    def compare_runs(self, base_run_id: str, target_run_id: str) -> RunComparisonResult:
        _existing_run_dir(self.artifact_root, base_run_id)
        _existing_run_dir(self.artifact_root, target_run_id)
        try:
            comparison = self._inspector.compare_runs(base_run_id, target_run_id)
        except WorkflowRunInspectionError as exc:
            raise ValueError(str(exc)) from exc
        return RunComparisonResult(
            base_run_id=base_run_id,
            target_run_id=target_run_id,
            comparison=comparison.to_dict(),
        )


def _summary_from_run_item(item: WorkflowRunListItem) -> RunSummary:
    return RunSummary(
        run_id=item.run_id,
        status=str(item.status or "unknown"),
        workflow_id=item.workflow_id,
        workflow_version=item.workflow_version,
        profile=item.profile,
        started_at=item.started_at,
        finished_at=item.finished_at,
        report_id=None,
        artifact_dir=item.run_dir,
        step_count=item.step_count,
        event_count=item.event_count,
        manifest_path=item.manifest_path,
    )


def _is_unreadable_manifest(item: WorkflowRunListItem) -> bool:
    return bool(item.invalid_reason and "invalid JSON artifact" in item.invalid_reason)


def _replay_result_from_content_bundle(bundle: WorkflowReplayContentBundle) -> RunReplayResult:
    return RunReplayResult(
        run_id=str(bundle.run_id or "unknown"),
        manifest=dict(bundle.manifest),
        manifest_path=bundle.manifest_path,
        events=[dict(event) for event in bundle.events],
        events_path=bundle.events_path,
        events_error=bundle.events_error,
        artifacts=[
            _replay_artifact_from_content_record(artifact)
            for artifact in bundle.artifacts
        ],
        step_results=dict(bundle.step_results),
        integrity=dict(bundle.integrity),
    )


def _replay_artifact_from_content_record(
    artifact: WorkflowArtifactContentRecord,
) -> RunReplayArtifact:
    return RunReplayArtifact(
        artifact_key=artifact.artifact_key,
        relative_path=artifact.relative_path,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        content=artifact.content,
        read_error=artifact.read_error,
        metadata=dict(artifact.metadata),
    )


def _resolve_run_dir_for_service(artifact_root: Path, run_id: str) -> Path:
    safe_run_id = validate_artifact_path_segment(run_id, field="run_id")
    return resolve_artifact_descendant(
        artifact_root,
        safe_run_id,
        field="run_id",
    )


def _existing_run_dir(artifact_root: Path, run_id: str) -> Path:
    run_dir = _resolve_run_dir_for_service(artifact_root, run_id)
    if not _run_manifest_path(run_dir).exists():
        raise FileNotFoundError(f"run not found: {run_id}")
    return run_dir


def _run_manifest_path(run_dir: Path) -> Path:
    return resolve_artifact_descendant(
        run_dir,
        "manifest.json",
        field="run manifest path",
    )


def _manifest_report_id(manifest: dict[str, Any]) -> str | None:
    report_id = manifest.get("report_id")
    if report_id is not None:
        return str(report_id)
    output = manifest.get("output")
    if isinstance(output, dict) and output.get("report_id") is not None:
        return str(output["report_id"])
    return None


def _manifest_output_preview(manifest: dict[str, Any]) -> dict[str, Any]:
    output = manifest.get("output")
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    if isinstance(output, dict):
        return project_manifest_output_preview(
            output,
            business_output=_manifest_business_output(manifest),
            artifacts=artifacts,
        )
    return project_manifest_output_preview({}, business_output={}, artifacts=artifacts)


def _manifest_business_output(manifest: dict[str, Any]) -> dict[str, Any]:
    output = manifest.get("output")
    if not isinstance(output, dict):
        return {}
    return dict(output)


def _manifest_error(manifest: dict[str, Any]) -> dict[str, Any] | None:
    error = manifest.get("error")
    if isinstance(error, dict):
        return error
    if error is None:
        return None
    return {"message": str(error)}


def _manifest_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    metrics = manifest.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return {
        key: value
        for key, value in {
            "step_count": manifest.get("step_count"),
            "event_count": manifest.get("event_count"),
            "checkpoint_count": manifest.get("checkpoint_count"),
            "operation_count": manifest.get("operation_count"),
        }.items()
        if value is not None
    }


def _event_matches(
    event: dict[str, Any],
    *,
    event_type: str | None,
    step_id: str | None,
) -> bool:
    if event_type is not None and event.get("event_type") != event_type:
        return False
    if step_id is None:
        return True
    raw_payload = event.get("payload")
    payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    return event.get("step_id") == step_id or payload.get("step_id") == step_id


def _read_verified_projection_events(
    *,
    path: Any,
    run_id: str,
    tenant_id: str | None,
    high_watermark: Any,
    event_count: Any,
    checksum: Any,
    event_type: str | None,
    step_id: str | None,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(path, str) or not path:
        raise EventProjectionConflictError("projection_artifact_missing")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0:
        raise EventProjectionConflictError("projection_event_count_invalid")
    if high_watermark is None:
        if event_count != 0:
            raise EventProjectionConflictError("projection_metadata_partial")
    elif (
        isinstance(high_watermark, bool)
        or not isinstance(high_watermark, int)
        or high_watermark < 1
        or event_count != high_watermark
    ):
        raise EventProjectionConflictError("projection_metadata_partial")
    if not _is_checksum(checksum):
        raise EventProjectionConflictError("projection_checksum_invalid")

    expected_stream_id = f"run:{run_id}"
    digest = sha256()
    selected: list[dict[str, Any]] = []
    matched_count = 0
    verified_count = 0
    try:
        handle = Path(path).open("rb")
    except OSError as error:
        raise EventProjectionConflictError("projection_artifact_missing") from error
    with handle:
        while True:
            raw_line = handle.readline(_MAX_PROJECTION_LINE_BYTES + 1)
            if not raw_line:
                break
            if len(raw_line) > _MAX_PROJECTION_LINE_BYTES:
                raise EventProjectionConflictError("projection_row_too_large")
            if not raw_line.endswith(b"\n"):
                raise EventProjectionConflictError("projection_row_incomplete")
            digest.update(raw_line)
            verified_count += 1
            try:
                raw_row = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise EventProjectionConflictError("projection_row_invalid") from error
            if not isinstance(raw_row, Mapping):
                raise EventProjectionConflictError("projection_row_invalid")
            row = dict(raw_row)
            if (
                row.get("projection_schema")
                != "newsroom.workflow-event-projection/v1"
                or row.get("stream_id") != expected_stream_id
                or row.get("tenant_id") != tenant_id
                or row.get("run_id") != run_id
                or row.get("stream_sequence") != verified_count
            ):
                raise EventProjectionConflictError("projection_row_scope_conflict")
            row_checksum = row.pop("projection_checksum", None)
            if not isinstance(row_checksum, str) or checksum_for(row) != row_checksum:
                raise EventProjectionConflictError("projection_row_checksum_invalid")
            row["projection_checksum"] = row_checksum

            event = redact_sensitive_values(
                {
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "run_id": row.get("run_id"),
                    "occurred_at": row.get("occurred_at"),
                    "step_id": row.get("step_id"),
                    "payload": (
                        dict(row["payload"])
                        if isinstance(row.get("payload"), Mapping)
                        else {}
                    ),
                    "line_number": verified_count,
                }
            )
            if _event_matches(event, event_type=event_type, step_id=step_id):
                if matched_count >= offset and len(selected) < limit:
                    selected.append(event)
                matched_count += 1

    if verified_count != event_count:
        raise EventProjectionConflictError("projection_event_count_mismatch")
    if (high_watermark is None and verified_count != 0) or (
        high_watermark is not None and verified_count != high_watermark
    ):
        raise EventProjectionConflictError("projection_high_watermark_mismatch")
    if f"sha256:{digest.hexdigest()}" != checksum:
        raise EventProjectionConflictError("projection_checksum_mismatch")
    return selected


def _encode_sequence_cursor(cursor: StreamSequenceCursor) -> str:
    if not isinstance(cursor, StreamSequenceCursor):
        raise TypeError("cursor must be a StreamSequenceCursor")
    payload = {
        "schema_version": "newsroom.run-event-cursor/v1",
        "stream_id": cursor.stream_id,
        "tenant_id": cursor.tenant_id,
        "after_sequence": cursor.after_sequence,
        "high_watermark": cursor.high_watermark,
    }
    envelope = {**payload, "checksum": checksum_for(payload)}
    encoded = json.dumps(
        envelope,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_sequence_cursor(
    value: str,
    *,
    run_id: str,
    tenant_id: str | None,
) -> StreamSequenceCursor:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        raise ValueError("sequence_cursor is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("sequence_cursor is invalid") from error
    if not isinstance(payload, Mapping):
        raise ValueError("sequence_cursor is invalid")
    expected_fields = {
        "schema_version",
        "stream_id",
        "tenant_id",
        "after_sequence",
        "high_watermark",
        "checksum",
    }
    if set(payload) != expected_fields:
        raise ValueError("sequence_cursor is invalid")
    checksum = payload.get("checksum")
    projection = {key: item for key, item in payload.items() if key != "checksum"}
    if payload.get("schema_version") != "newsroom.run-event-cursor/v1" or (
        not isinstance(checksum, str) or checksum_for(projection) != checksum
    ):
        raise ValueError("sequence_cursor failed integrity validation")
    expected_stream = f"run:{validate_artifact_path_segment(run_id, field='run_id')}"
    if payload.get("stream_id") != expected_stream or payload.get("tenant_id") != tenant_id:
        raise ValueError("sequence_cursor does not match the requested run scope")
    try:
        return StreamSequenceCursor(
            stream_id=expected_stream,
            tenant_id=tenant_id,
            after_sequence=payload.get("after_sequence"),
            high_watermark=payload.get("high_watermark"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("sequence_cursor is invalid") from error


def _encode_sse_resume_cursor(
    *,
    stream_id: str,
    tenant_id: str | None,
    after_sequence: int,
) -> str:
    if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 1:
        raise ValueError("after_sequence must be a positive integer")
    payload = {
        "schema_version": "newsroom.run-event-sse-cursor/v1",
        "stream_id": stream_id,
        "tenant_id": tenant_id,
        "after_sequence": after_sequence,
    }
    envelope = {**payload, "checksum": checksum_for(payload)}
    encoded = json.dumps(
        envelope,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_sse_resume_cursor(
    value: str,
    *,
    run_id: str,
    tenant_id: str | None,
) -> int:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        raise ValueError("Last-Event-ID is invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Last-Event-ID is invalid") from error
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "stream_id",
        "tenant_id",
        "after_sequence",
        "checksum",
    }:
        raise ValueError("Last-Event-ID is invalid")
    checksum = payload.get("checksum")
    projection = {key: item for key, item in payload.items() if key != "checksum"}
    if payload.get("schema_version") != "newsroom.run-event-sse-cursor/v1" or (
        not isinstance(checksum, str) or checksum_for(projection) != checksum
    ):
        raise ValueError("Last-Event-ID failed integrity validation")
    expected_stream = f"run:{validate_artifact_path_segment(run_id, field='run_id')}"
    if payload.get("stream_id") != expected_stream or payload.get("tenant_id") != tenant_id:
        raise ValueError("Last-Event-ID does not match the requested run scope")
    after_sequence = payload.get("after_sequence")
    if (
        isinstance(after_sequence, bool)
        or not isinstance(after_sequence, int)
        or after_sequence < 1
    ):
        raise ValueError("Last-Event-ID is invalid")
    return after_sequence


def _with_sse_resume_cursors(
    result: RunEventsResult,
    *,
    stream_id: str,
    tenant_id: str | None,
    fallback_after_sequence: int = 0,
) -> RunEventsResult:
    if result.availability != EventServiceAvailability.AVAILABLE.value:
        return result
    events: list[dict[str, Any]] = []
    last_sequence = fallback_after_sequence
    for event in result.events:
        projected = dict(event)
        sequence = projected.get("stream_sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("durable SSE event is missing stream_sequence")
        projected["sse_resume_cursor"] = _encode_sse_resume_cursor(
            stream_id=stream_id,
            tenant_id=tenant_id,
            after_sequence=sequence,
        )
        last_sequence = sequence
        events.append(projected)
    resume_cursor = (
        None
        if last_sequence == 0
        else _encode_sse_resume_cursor(
            stream_id=stream_id,
            tenant_id=tenant_id,
            after_sequence=last_sequence,
        )
    )
    return RunEventsResult(
        run_id=result.run_id,
        events=events,
        events_path=result.events_path,
        next_sequence_cursor=result.next_sequence_cursor,
        high_watermark=result.high_watermark,
        source=result.source,
        projection_status=result.projection_status,
        projection_checksum=result.projection_checksum,
        projection_high_watermark=result.projection_high_watermark,
        availability=result.availability,
        unavailable_reason_class=result.unavailable_reason_class,
        sse_resume_cursor=resume_cursor,
    )


def _is_checksum(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, digest = value.partition(":")
    return bool(
        separator == ":"
        and prefix == "sha256"
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _run_is_active(status: Any) -> bool:
    return str(status or "").strip().casefold() in {
        "created",
        "draft",
        "ready",
        "running",
        "retrying",
        "paused",
        "waiting_for_human",
    }


def _step_view(
    step_id: Any,
    payload: Any,
    *,
    sequence: int | None,
) -> dict[str, Any]:
    data = dict(payload) if isinstance(payload, dict) else {"value": payload}
    raw_outputs = data.get("outputs")
    outputs: dict[str, Any] = dict(raw_outputs) if isinstance(raw_outputs, dict) else {}
    error = data.get("error") if isinstance(data.get("error"), dict) else None
    return {
        "step_id": str(step_id),
        "sequence": sequence,
        "status": str(data.get("status") or "unknown"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "output_keys": sorted(str(key) for key in outputs),
        "error": to_json_safe(error),
        "metrics": to_json_safe(data.get("metrics") if isinstance(data.get("metrics"), dict) else {}),
        "artifact_refs": to_json_safe(
            data.get("artifact_refs") if isinstance(data.get("artifact_refs"), list) else []
        ),
        "raw": to_json_safe(data),
    }
