"""Graph run inspection application service.

Inspection reads Graph terminal manifests, canonical Graph index snapshots, and
durable Graph events only. Non-Graph manifests are reported as history
quarantine and are never parsed for resume, replay, or publication.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.agent.artifacts.paths import (
    resolve_artifact_descendant,
    validate_artifact_path_segment,
)
from framework.agent.artifacts import ArtifactStoreMetadataError
from framework.events.errors import EventStoreUnavailableError
from framework.events.projection import project_graph_event
from framework.events.runtime.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    StreamSequenceCursor,
)
from framework.events.schema import EventSchemaCatalog, default_event_schema_catalog
from framework.harness.artifacts import (
    GraphTerminalManifestV2,
    GraphTerminalManifestError,
    GraphTerminalManifestHistoryError,
)
from infrastructure.storage.artifacts import FilesystemGraphTerminalArtifactReader
from infrastructure.storage.indexing import (
    GraphStorageIndexError,
    GraphStorageIndexErrorCode,
    GraphStorageIndexReaderPort,
    GraphStorageIndexSnapshot,
)
from interfaces.services.event_projection_service import (
    EventProjectionConflictError,
    EventProjectionService,
    EventProjectionStatus,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventReaderService,
    EventServiceAvailability,
)
from interfaces.services.artifact_service import ArtifactInspectionService


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    status: str
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
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
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
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


@dataclass(frozen=True, slots=True)
class RunListResult:
    runs: list[RunSummary]

    def to_dict(self) -> dict[str, Any]:
        return {"run_count": len(self.runs), "runs": [item.to_dict() for item in self.runs]}


@dataclass(frozen=True, slots=True)
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
            "graph_id": self.manifest.get("graph_id"),
            "graph_version": self.manifest.get("graph_version"),
            "graph_ref": _manifest_graph_ref(self.manifest),
            "graph_checksum": self.manifest.get("normalized_graph_checksum"),
            "status": self.manifest.get("status"),
            "started_at": self.manifest.get("started_at"),
            "finished_at": self.manifest.get("completed_at"),
            "report_id": self.manifest.get("report_id"),
            "artifact_dir": self.artifact_dir,
            "output_preview": self.output_preview or {},
            "error": self.error,
            "metrics": self.metrics or {},
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
        }


@dataclass(frozen=True, slots=True)
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
        if self.source not in {"durable_store", "projection"}:
            raise ValueError("run events source must be durable_store or projection")
        if self.availability not in {"available", "unavailable"}:
            raise ValueError("run events availability is invalid")
        if self.availability == "available":
            if self.source != "durable_store":
                raise ValueError("available run events require durable_store source")
            if self.unavailable_reason_class is not None:
                raise ValueError("available run events cannot contain a reason class")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable run events require a reason class")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_count": len(self.events),
            "events": list(self.events),
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


@dataclass(frozen=True, slots=True)
class RunStepsResult:
    run_id: str
    steps: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "step_count": len(self.steps), "steps": self.steps}


@dataclass(frozen=True, slots=True)
class RunReplayResult:
    run_id: str
    manifest: dict[str, Any]
    manifest_path: str
    events: list[dict[str, Any]]
    events_path: str | None
    artifacts: list[dict[str, Any]]
    step_results: dict[str, Any]
    integrity: dict[str, Any]
    events_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "manifest": dict(self.manifest),
            "manifest_path": self.manifest_path,
            "event_count": len(self.events),
            "events": list(self.events),
            "events_path": self.events_path,
            "events_error": self.events_error,
            "artifact_count": len(self.artifacts),
            "artifacts": list(self.artifacts),
            "step_result_count": len(self.step_results),
            "step_results": dict(self.step_results),
            "integrity": dict(self.integrity),
        }


@dataclass(frozen=True, slots=True)
class RunDiagnosticsResult:
    run_id: str
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "diagnostics": dict(self.diagnostics)}


@dataclass(frozen=True, slots=True)
class RunHealthResult:
    run_id: str
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "health": dict(self.health)}


@dataclass(frozen=True, slots=True)
class RunCatalogHealthResult:
    health: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"health": dict(self.health)}


@dataclass(frozen=True, slots=True)
class RunComparisonResult:
    base_run_id: str
    target_run_id: str
    comparison: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_run_id": self.base_run_id,
            "target_run_id": self.target_run_id,
            "comparison": dict(self.comparison),
        }


class GraphRunInspectionService:
    """Read-only Graph manifest/event views with no fallback reader."""

    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        event_reader_service: EventReaderService | None = None,
        event_projection_service: EventProjectionService | None = None,
        event_authorization: EventAuthorizationContext | None = None,
        event_schema_catalog: EventSchemaCatalog | None = None,
        event_services_factory: Callable[[], tuple[EventReaderService, EventProjectionService, EventAuthorizationContext, EventSchemaCatalog]] | None = None,
        graph_index_reader: GraphStorageIndexReaderPort,
    ) -> None:
        self.artifact_root = Path(artifact_root).resolve(strict=False)
        self._terminal_reader = FilesystemGraphTerminalArtifactReader(self.artifact_root)
        self._artifact_service = ArtifactInspectionService(
            self.artifact_root,
            terminal_reader=self._terminal_reader,
        )
        self._event_reader_service = event_reader_service
        self._event_projection_service = event_projection_service
        self._event_authorization = event_authorization or EventAuthorizationContext(
            principal_id="graph-run-inspection",
            tenant_id=None,
            authentication_evidence_ref="authn://graph-run-inspection",
        )
        self._event_schema_catalog = event_schema_catalog or default_event_schema_catalog()
        self._event_services_factory = event_services_factory
        if not isinstance(graph_index_reader, GraphStorageIndexReaderPort):
            raise TypeError("graph_index_reader must implement GraphStorageIndexReaderPort")
        self._graph_index_reader = graph_index_reader
        if event_projection_service is not None and event_reader_service is None:
            raise ValueError("event projection service requires an event reader service")

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        graph_id: str | None = None,
    ) -> RunListResult:
        if limit <= 0 or offset < 0:
            raise ValueError("limit must be positive and offset must be non-negative")
        summaries: list[RunSummary] = []
        if self.artifact_root.exists():
            for run_dir in sorted(item for item in self.artifact_root.iterdir() if item.is_dir()):
                try:
                    manifest = self._read_manifest(run_dir.name)
                except GraphTerminalManifestHistoryError:
                    continue
                except (GraphTerminalManifestError, OSError, ValueError):
                    continue
                index = self._read_graph_index(manifest)
                if status is not None and manifest.status.value != status:
                    continue
                if graph_id is not None and manifest.graph_id != graph_id:
                    continue
                summaries.append(_summary_from_manifest(manifest, run_dir, index=index))
        return RunListResult(summaries[offset : offset + limit])

    def get_run(self, run_id: str) -> RunDetail:
        manifest = self._read_manifest(run_id)
        index = self._read_graph_index(manifest)
        run_dir = self._run_dir(run_id)
        payload = manifest.to_dict()
        node_instances = _node_instance_ids(index)
        return RunDetail(
            run_id=manifest.run_id,
            manifest=payload,
            manifest_path=str(run_dir / "manifest.json"),
            artifact_dir=str(run_dir),
            output_preview={
                "terminal_node_ids": list(manifest.terminal_node_ids),
                "node_instance_ids": node_instances,
            },
            metrics={
                "artifact_count": len(index.artifact_records),
                "gate_evidence_count": len(manifest.gate_evidence_refs),
                "terminal_node_count": len(manifest.terminal_node_ids),
                "graph_index_snapshot_checksum": index.snapshot_checksum,
                "graph_index_event_high_watermark": index.event_high_watermark,
            },
        )

    def get_run_events(
        self,
        run_id: str,
        *,
        event_type: str | None = None,
        node_instance_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        sequence_cursor: str | None = None,
    ) -> RunEventsResult:
        if limit is not None and not 0 < limit <= MAX_PAGE_LIMIT:
            raise ValueError("limit is outside the supported range")
        if offset < 0 or (offset and sequence_cursor):
            raise ValueError("offset and sequence_cursor cannot be combined")
        detail = self.get_run(run_id)
        index = self._read_graph_index(self._read_manifest(detail.run_id))
        self._ensure_event_services()
        if self._event_reader_service is None:
            return self._unavailable_events(detail, "event_reader_unavailable")
        cursor = _decode_cursor(sequence_cursor, run_id=detail.run_id, tenant_id=self._event_authorization.tenant_id) if sequence_cursor else None
        page = self._event_reader_service.read_run_events(
            detail.run_id,
            authorization=self._event_authorization,
            cursor=cursor,
            limit=limit or DEFAULT_PAGE_LIMIT,
            event_types=frozenset({event_type}) if event_type else frozenset(),
            through_sequence=None,
            node_instance_id=node_instance_id,
        )
        if page.availability is EventServiceAvailability.UNAVAILABLE:
            return self._unavailable_events(detail, page.unavailable_reason_class or "event_store_unavailable")
        if page.high_watermark != index.event_high_watermark:
            _raise_index_integrity_error(
                "Graph index watermark conflicts with the durable event stream",
                field="event_high_watermark",
            )
        events = []
        for event in page.events:
            row = project_graph_event(event, schema_catalog=self._event_schema_catalog)
            events.append(row)
        _verify_index_event_rows(index, events)
        if offset:
            events = events[offset:]
        projection = self._projection_metadata(detail.manifest)
        return RunEventsResult(
            run_id=detail.run_id,
            events=events,
            events_path=projection.get("path"),
            next_sequence_cursor=_encode_cursor(page.next_cursor) if page.next_cursor else None,
            high_watermark=page.high_watermark,
            projection_status=self._projection_status(detail, page.high_watermark).value,
            projection_checksum=projection.get("checksum"),
            projection_high_watermark=projection.get("high_watermark"),
        )

    def get_run_events_for_sse(self, run_id: str, *, limit: int | None = None, sequence_cursor: str | None = None, last_event_id: str | None = None) -> RunEventsResult:
        if sequence_cursor and last_event_id:
            raise ValueError("sequence_cursor and Last-Event-ID cannot be combined")
        cursor = sequence_cursor or last_event_id
        result = self.get_run_events(run_id, limit=limit, sequence_cursor=cursor)
        return result

    def get_run_steps(self, run_id: str) -> RunStepsResult:
        manifest = self._read_manifest(run_id)
        index = self._read_graph_index(manifest)
        return RunStepsResult(
            run_id=manifest.run_id,
            steps=_steps_from_index(index),
        )

    def replay_run(self, run_id: str) -> RunReplayResult:
        detail = self.get_run(run_id)
        index = self._read_graph_index(self._read_manifest(detail.run_id))
        artifacts = self._read_indexed_replay_artifacts(run_id, index)
        try:
            events_result = self._read_all_indexed_events(detail, index)
        except EventStoreUnavailableError as exc:
            events_result = self._unavailable_events(detail, str(exc))
        return RunReplayResult(
            run_id=detail.run_id,
            manifest=detail.manifest,
            manifest_path=detail.manifest_path,
            events=events_result.events,
            events_path=events_result.events_path,
            artifacts=artifacts,
            step_results={},
            integrity={
                "manifest_hash": detail.manifest.get("manifest_hash"),
                "event_projection_checksum": events_result.projection_checksum,
                "graph_index_snapshot_checksum": index.snapshot_checksum,
                "graph_index_event_high_watermark": index.event_high_watermark,
                "graph_only": True,
            },
            events_error=events_result.unavailable_reason_class,
        )

    def get_run_diagnostics(self, run_id: str) -> RunDiagnosticsResult:
        detail = self.get_run(run_id)
        return RunDiagnosticsResult(
            run_id=detail.run_id,
            diagnostics={
                "graph_id": detail.manifest.get("graph_id"),
                "graph_version": detail.manifest.get("graph_version"),
                "status": detail.manifest.get("status"),
                "terminal_reason": detail.manifest.get("terminal_reason"),
                "terminal_node_ids": detail.manifest.get("terminal_node_ids", []),
                "gate_evidence_refs": detail.manifest.get("gate_evidence_refs", []),
            },
        )

    def get_run_health(self, run_id: str) -> RunHealthResult:
        detail = self.get_run(run_id)
        return RunHealthResult(
            run_id=detail.run_id,
            health={
                "status": detail.manifest.get("status"),
                "graph_id": detail.manifest.get("graph_id"),
                "graph_version": detail.manifest.get("graph_version"),
                "manifest_verified": True,
                "artifact_count": (detail.metrics or {}).get("artifact_count", 0),
            },
        )

    def get_catalog_health(self) -> RunCatalogHealthResult:
        total = 0
        invalid = 0
        quarantined = 0
        if self.artifact_root.exists():
            for item in self.artifact_root.iterdir():
                if not item.is_dir() or item.name == "graph-index":
                    continue
                total += 1
                try:
                    manifest = self._read_manifest(item.name)
                    self._read_graph_index(manifest)
                except GraphTerminalManifestHistoryError:
                    quarantined += 1
                except Exception:
                    invalid += 1
        return RunCatalogHealthResult({"total_runs": total, "invalid_runs": invalid, "quarantined_runs": quarantined, "graph_only": True})

    def compare_runs(self, base_run_id: str, target_run_id: str) -> RunComparisonResult:
        base = self._read_manifest(base_run_id)
        target = self._read_manifest(target_run_id)
        base_index = self._read_graph_index(base)
        target_index = self._read_graph_index(target)
        return RunComparisonResult(
            base_run_id=base.run_id,
            target_run_id=target.run_id,
            comparison={
                "same_graph": (
                    base.graph_id == target.graph_id
                    and base.graph_version == target.graph_version
                    and base.normalized_graph_checksum == target.normalized_graph_checksum
                ),
                "base_status": base.status.value,
                "target_status": target.status.value,
                "base_manifest_hash": base.manifest_hash,
                "target_manifest_hash": target.manifest_hash,
                "base_artifact_count": len(base_index.artifact_records),
                "target_artifact_count": len(target_index.artifact_records),
                "base_graph_index_snapshot_checksum": base_index.snapshot_checksum,
                "target_graph_index_snapshot_checksum": target_index.snapshot_checksum,
            },
        )

    def _read_manifest(self, run_id: str) -> GraphTerminalManifestV2:
        safe = validate_artifact_path_segment(run_id, field="run_id")
        try:
            return self._terminal_reader.read_terminal_manifest(safe)
        except GraphTerminalManifestHistoryError:
            raise
        except GraphTerminalManifestError as exc:
            raise ArtifactStoreMetadataError(str(exc)) from exc

    def _read_graph_index(
        self,
        manifest: GraphTerminalManifestV2,
    ) -> GraphStorageIndexSnapshot:
        return self._graph_index_reader.read_for_manifest(manifest)

    def _read_all_indexed_events(
        self,
        detail: RunDetail,
        index: GraphStorageIndexSnapshot,
    ) -> RunEventsResult:
        self._ensure_event_services()
        if self._event_reader_service is None:
            raise EventStoreUnavailableError("event_reader_unavailable")
        cursor: StreamSequenceCursor | None = None
        rows: list[dict[str, Any]] = []
        high_watermark: int | None = None
        while True:
            page = self._event_reader_service.read_run_events(
                detail.run_id,
                authorization=self._event_authorization,
                cursor=cursor,
                limit=MAX_PAGE_LIMIT,
                through_sequence=index.event_high_watermark,
            )
            if page.availability is EventServiceAvailability.UNAVAILABLE:
                raise EventStoreUnavailableError(
                    page.unavailable_reason_class or "event_store_unavailable"
                )
            if page.high_watermark != index.event_high_watermark:
                _raise_index_integrity_error(
                    "Graph index watermark conflicts with the durable event stream",
                    field="event_high_watermark",
                )
            high_watermark = page.high_watermark
            projected = [
                project_graph_event(event, schema_catalog=self._event_schema_catalog)
                for event in page.events
            ]
            _verify_index_event_rows(index, projected)
            rows.extend(projected)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        _verify_complete_index_history(index, rows)
        projection = self._projection_metadata(detail.manifest)
        return RunEventsResult(
            run_id=detail.run_id,
            events=rows,
            events_path=projection.get("path"),
            high_watermark=high_watermark,
            projection_status=self._projection_status(detail, high_watermark).value,
            projection_checksum=projection.get("checksum"),
            projection_high_watermark=projection.get("high_watermark"),
        )

    def _read_indexed_replay_artifacts(
        self,
        run_id: str,
        index: GraphStorageIndexSnapshot,
    ) -> list[dict[str, Any]]:
        """Read the replay bundle through the immutable Graph index authority."""

        manifest = self._read_manifest(run_id)
        artifacts: list[dict[str, Any]] = []
        for record in index.artifact_records:
            manifest_artifact = manifest.artifact(record.artifact_key)
            if (
                manifest_artifact is None
                or manifest_artifact.artifact_id != record.artifact_id
                or manifest_artifact.ref != record.artifact_ref
                or manifest_artifact.relative_path != record.relative_path
                or manifest_artifact.content_checksum != record.content_checksum
                or manifest_artifact.byte_size != record.byte_size
                or manifest_artifact.media_type != record.media_type
                or manifest_artifact.required_for_replay
                != record.required_for_replay
                or manifest_artifact.required_for_publication
                != record.required_for_publication
            ):
                _raise_index_integrity_error(
                    "Graph index artifact record conflicts with the terminal manifest",
                    field="artifact",
                )
            artifact = self._artifact_service.get_artifact(run_id, record.artifact_key)
            if (
                artifact.relative_path != record.relative_path
                or artifact.content_type != record.media_type
                or artifact.size_bytes != record.byte_size
            ):
                _raise_index_integrity_error(
                    "Graph artifact read-back conflicts with the canonical index",
                    field="artifact",
                )
            artifacts.append(
                {
                    "artifact_key": artifact.artifact_key,
                    "relative_path": artifact.relative_path,
                    "content_type": artifact.content_type,
                    "size_bytes": artifact.size_bytes,
                }
            )
        return artifacts

    def _run_dir(self, run_id: str) -> Path:
        safe = validate_artifact_path_segment(run_id, field="run_id")
        path = (self.artifact_root / safe).resolve(strict=False)
        if self.artifact_root not in path.parents:
            raise ValueError("run path escapes artifact root")
        return path

    def _ensure_event_services(self) -> None:
        if self._event_reader_service is not None or self._event_services_factory is None:
            return
        self._event_reader_service, self._event_projection_service, self._event_authorization, self._event_schema_catalog = self._event_services_factory()
        self._event_services_factory = None

    def _projection_metadata(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        raw_artifacts = manifest.get("artifacts")
        if not isinstance(raw_artifacts, list):
            return _missing_projection_metadata()
        matches = [
            item
            for item in raw_artifacts
            if isinstance(item, Mapping)
            and item.get("artifact_key") == "event_projection"
        ]
        if len(matches) != 1:
            return _missing_projection_metadata()
        artifact = matches[0]
        metadata = artifact.get("metadata")
        relative_path = artifact.get("relative_path")
        run_id = manifest.get("run_id")
        if (
            not isinstance(metadata, Mapping)
            or not isinstance(relative_path, str)
            or not isinstance(run_id, str)
        ):
            return _missing_projection_metadata()
        path = resolve_artifact_descendant(
            self.artifact_root,
            validate_artifact_path_segment(run_id, field="run_id"),
            relative_path,
            field="Graph event projection path",
        )
        return {
            "path": str(path),
            "high_watermark": metadata.get("high_watermark"),
            "event_count": metadata.get("event_count"),
            "checksum": artifact.get("content_checksum"),
        }

    def _projection_status(self, detail: RunDetail, durable_high_watermark: int | None) -> EventProjectionStatus:
        projection = self._projection_metadata(detail.manifest)
        if self._event_projection_service is None or projection.get("path") is None:
            return EventProjectionStatus.UNAVAILABLE
        try:
            return self._event_projection_service.get_run_projection_status(
                detail.run_id,
                projection_high_watermark=projection.get("high_watermark"),
                projection_event_count=projection.get("event_count"),
                projection_checksum=projection.get("checksum"),
                run_is_active=detail.manifest.get("status") not in {"succeeded", "failed", "cancelled", "halted", "blocked"},
                authorization=self._event_authorization,
            ).status
        except (EventProjectionConflictError, EventStoreUnavailableError):
            return EventProjectionStatus.UNAVAILABLE

    def _unavailable_events(self, detail: RunDetail, reason: str) -> RunEventsResult:
        projection = self._projection_metadata(detail.manifest)
        return RunEventsResult(
            run_id=detail.run_id,
            events=[],
            events_path=projection.get("path"),
            source="durable_store",
            projection_status=EventProjectionStatus.UNAVAILABLE.value,
            projection_checksum=projection.get("checksum"),
            projection_high_watermark=projection.get("high_watermark"),
            availability=EventServiceAvailability.UNAVAILABLE.value,
            unavailable_reason_class=reason,
        )


def _summary_from_manifest(
    manifest: GraphTerminalManifestV2,
    run_dir: Path,
    *,
    index: GraphStorageIndexSnapshot,
) -> RunSummary:
    return RunSummary(
        run_id=manifest.run_id,
        status=manifest.status.value,
        graph_id=manifest.graph_id,
        graph_version=manifest.graph_version,
        graph_ref=_manifest_graph_ref(manifest.to_dict()),
        graph_checksum=manifest.normalized_graph_checksum,
        started_at=manifest.started_at.isoformat(),
        finished_at=manifest.completed_at.isoformat(),
        artifact_dir=str(run_dir),
        step_count=len(_node_instance_ids(index)),
        event_count=index.event_high_watermark,
        manifest_path=str(run_dir / "manifest.json"),
    )


def _manifest_graph_ref(manifest: Mapping[str, Any]) -> str | None:
    graph_id = manifest.get("graph_id")
    graph_version = manifest.get("graph_version")
    if not graph_id or not graph_version:
        return None
    return f"{graph_id}@{graph_version}"


def _projection_artifact_metadata(
    manifest: GraphTerminalManifestV2,
) -> Mapping[str, Any]:
    artifact = manifest.artifact("event_projection")
    if artifact is None:
        return {}
    return artifact.metadata


def _missing_projection_metadata() -> dict[str, Any]:
    return {
        "path": None,
        "high_watermark": None,
        "event_count": None,
        "checksum": None,
    }


def _node_instance_ids(index: GraphStorageIndexSnapshot) -> list[str]:
    return sorted(
        {
            record.node_instance_id
            for record in index.event_records
            if record.node_instance_id is not None
        }
    )


def _steps_from_index(index: GraphStorageIndexSnapshot) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = {}
    for record in index.event_records:
        if record.node_id is None or record.node_instance_id is None:
            continue
        grouped.setdefault((record.node_id, record.node_instance_id), []).append(record)
    steps: list[dict[str, Any]] = []
    for (node_id, node_instance_id), records in sorted(grouped.items()):
        ordered = sorted(records, key=lambda item: item.stream_sequence)
        activity_ids = sorted(
            {
                item.activity_id
                for item in ordered
                if item.activity_id is not None
            }
        )
        attempts = sorted(
            {item.attempt for item in ordered if item.attempt is not None}
        )
        steps.append(
            {
                "node_id": node_id,
                "node_instance_id": node_instance_id,
                "activity_ids": activity_ids,
                "attempts": attempts,
                "event_count": len(ordered),
                "first_event_sequence": ordered[0].stream_sequence,
                "last_event_sequence": ordered[-1].stream_sequence,
                "latest_event_type": ordered[-1].event_type,
                "status": "indexed",
            }
        )
    return steps


def _verify_index_event_rows(
    index: GraphStorageIndexSnapshot,
    rows: list[dict[str, Any]],
) -> None:
    records = {record.event_id: record for record in index.event_records}
    seen: set[str] = set()
    for row in rows:
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or event_id in seen:
            _raise_index_integrity_error(
                "Durable event projection has an invalid event identity",
                field="event_id",
            )
        seen.add(event_id)
        record = records.get(event_id)
        if record is None:
            _raise_index_integrity_error(
                "Durable event is absent from the canonical Graph index",
                field="event_id",
            )
        expected = {
            "stream_id": f"run:{index.identity.run_id}",
            "stream_sequence": record.stream_sequence,
            "event_type": record.event_type,
            "data_schema": record.data_schema,
            "source_content_checksum": record.content_checksum,
            "source_record_checksum": record.source_record_checksum,
            "node_id": record.node_id,
            "node_instance_id": record.node_instance_id,
            "activity_id": record.activity_id,
            "attempt": record.attempt,
            "run_id": index.identity.run_id,
            "graph_id": index.identity.graph_identity.graph_id,
            "graph_version": index.identity.graph_identity.graph_version,
            "graph_ref": index.identity.graph_identity.graph_ref,
            "graph_checksum": index.identity.graph_identity.graph_checksum,
        }
        if any(row.get(name) != value for name, value in expected.items()):
            _raise_index_integrity_error(
                "Durable event projection conflicts with the canonical Graph index",
                field="event",
            )


def _verify_complete_index_history(
    index: GraphStorageIndexSnapshot,
    rows: list[dict[str, Any]],
) -> None:
    if len(rows) != len(index.event_records):
        _raise_index_integrity_error(
            "Durable event history does not cover the canonical Graph index",
            field="event_count",
        )
    _verify_index_event_rows(index, rows)
    sequences = sorted(row.get("stream_sequence") for row in rows)
    if sequences != list(range(1, index.event_high_watermark + 1)):
        _raise_index_integrity_error(
            "Durable event history has a Graph index sequence gap",
            field="stream_sequence",
        )


def _raise_index_integrity_error(message: str, *, field: str) -> None:
    raise GraphStorageIndexError(
        GraphStorageIndexErrorCode.INDEX_CORRUPT,
        message,
        field=field,
    )


def _encode_cursor(cursor: StreamSequenceCursor) -> str:
    payload = {"stream_id": cursor.stream_id, "tenant_id": cursor.tenant_id, "after_sequence": cursor.after_sequence, "high_watermark": cursor.high_watermark}
    return base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")


def _decode_cursor(value: str, *, run_id: str, tenant_id: str | None) -> StreamSequenceCursor:
    try:
        raw = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        cursor = StreamSequenceCursor(**raw)
    except Exception as exc:
        raise ValueError("invalid Graph event sequence cursor") from exc
    if cursor.stream_id != f"run:{run_id}" or cursor.tenant_id != tenant_id:
        raise ValueError("Graph event cursor scope mismatch")
    return cursor


__all__ = [
    "GraphRunInspectionService",
    "RunCatalogHealthResult",
    "RunComparisonResult",
    "RunDetail",
    "RunDiagnosticsResult",
    "RunEventsResult",
    "RunHealthResult",
    "RunListResult",
    "RunReplayResult",
    "RunStepsResult",
    "RunSummary",
]
