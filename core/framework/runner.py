from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.events import EventBus
from core.framework.run_result import RunResult
from core.framework.specs import WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.inspection import (
    WorkflowReplayBundle,
    WorkflowRunCatalog,
    WorkflowRunCatalogHealth,
    WorkflowRunComparison,
    WorkflowRunDiagnostics,
    WorkflowRunHealthReport,
    WorkflowRunInspection,
    WorkflowRunListItem,
    WorkflowRunInspector,
)
from core.framework.workflow.manifest import manifest_schema_version
from core.framework.workflow.result import WorkflowResult
from core.framework.workflow.step_runner import (
    FunctionStepRegistry,
    StepRunnerRegistry,
    build_default_step_runner_registry,
)
from storage.artifacts import ArtifactRef, artifact_index_store_from_env
from storage.checkpoint import WorkflowCheckpoint
from storage.events import EventRecord as StorageEventRecord
from storage.events import event_store_from_env
from storage.lineage import lineage_refs_from_evidence_bundle, lineage_store_from_env
from storage.security import StorageRedactor


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        function_registry: FunctionStepRegistry | None = None,
        step_runner_registry: StepRunnerRegistry | None = None,
        tool_registry: Any | None = None,
        agent_runner: Any | None = None,
        agent_registry: dict[str, Any] | None = None,
        workflow_registry: dict[str, WorkflowSpec] | None = None,
        approval_store: Any | None = None,
        secret_provider: Any | None = None,
        max_parallel_workers: int = 4,
        max_tool_batch_workers: int = 4,
        artifact_index_store: Any | None = None,
        event_store: Any | None = None,
        lineage_store: Any | None = None,
        checkpoint_store: Any | None = None,
        event_bus: EventBus | None = None,
        redactor: StorageRedactor | None = None,
    ) -> None:
        self._artifact_root = Path(artifact_root)
        self._artifact_manager = ArtifactManager(self._artifact_root)
        if step_runner_registry is None:
            if function_registry is None:
                raise ValueError("function_registry is required without step_runner_registry")
            step_runner_registry = build_default_step_runner_registry(
                function_registry,
                tool_registry=tool_registry,
                agent_runner=agent_runner,
                agent_registry=agent_registry,
                workflow_registry=workflow_registry,
                artifact_manager=self._artifact_manager,
                approval_store=approval_store,
                secret_provider=secret_provider,
                max_parallel_workers=max_parallel_workers,
                max_tool_batch_workers=max_tool_batch_workers,
            )
        self._step_runner_registry = step_runner_registry
        self._indexer = WorkflowRunIndexer(
            artifact_index_store=artifact_index_store
            or artifact_index_store_from_env(artifact_root=self._artifact_root),
            event_store=event_store or event_store_from_env(artifact_root=self._artifact_root),
            lineage_store=lineage_store or lineage_store_from_env(artifact_root=self._artifact_root),
            redactor=redactor or StorageRedactor(),
        )
        self._checkpoint_store = checkpoint_store
        self._event_bus = event_bus
        self._run_inspector = WorkflowRunInspector(self._artifact_root)

    def run(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            checkpoint_store=self._checkpoint_store,
            event_bus=self._event_bus,
        )
        result = executor.execute(workflow, request, profile=profile, run_id=run_id)
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def resume_from_checkpoint(
        self,
        workflow: WorkflowSpec,
        checkpoint: WorkflowCheckpoint,
        *,
        profile: str,
        run_id: str | None = None,
        buffer_updates: dict[str, Any] | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=None,
            step_runner_registry=self._step_runner_registry,
            artifact_manager=self._artifact_manager,
            checkpoint_store=self._checkpoint_store,
            event_bus=self._event_bus,
        )
        result = executor.resume_from_checkpoint(
            workflow,
            checkpoint,
            profile=profile,
            run_id=run_id,
            buffer_updates=buffer_updates,
        )
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def _persist_storage_indexes(self, result: WorkflowResult) -> None:
        self._indexer.index(result)

    def inspect_run(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunInspection:
        return self._run_inspector.inspect_run(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def build_replay_bundle(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowReplayBundle:
        return self._run_inspector.build_replay_bundle(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def inspect_run_diagnostics(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunDiagnostics:
        return self._run_inspector.build_diagnostics(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def inspect_run_health(
        self,
        run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunHealthReport:
        return self._run_inspector.build_health_report(
            run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )

    def list_runs(
        self,
        *,
        limit: int | None = 50,
        offset: int = 0,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunCatalog:
        return self._run_inspector.list_runs(
            limit=limit,
            offset=offset,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            status=status,
            profile=profile,
            include_invalid=include_invalid,
        )

    def latest_run(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        status: str | None = None,
        profile: str | None = None,
        include_invalid: bool = False,
    ) -> WorkflowRunListItem | None:
        return self._run_inspector.latest_run(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            status=status,
            profile=profile,
            include_invalid=include_invalid,
        )

    def catalog_health(
        self,
        *,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        profile: str | None = None,
        include_invalid: bool = True,
    ) -> WorkflowRunCatalogHealth:
        return self._run_inspector.catalog_health(
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            profile=profile,
            include_invalid=include_invalid,
        )

    def compare_runs(
        self,
        base_run_id: str,
        target_run_id: str,
        *,
        verify_checksums: bool = False,
        strict: bool = False,
    ) -> WorkflowRunComparison:
        return self._run_inspector.compare_runs(
            base_run_id,
            target_run_id,
            verify_checksums=verify_checksums,
            strict=strict,
        )


class WorkflowRunIndexer:
    def __init__(
        self,
        *,
        artifact_index_store: Any,
        event_store: Any,
        lineage_store: Any,
        redactor: StorageRedactor,
    ) -> None:
        self._artifact_index_store = artifact_index_store
        self._event_store = event_store
        self._lineage_store = lineage_store
        self._redactor = redactor

    def index(self, result: WorkflowResult) -> None:
        self._index_artifacts(result)
        self._index_events(result)
        self._index_lineage(result)

    def _index_artifacts(self, result: WorkflowResult) -> None:
        if result.artifact_dir is None:
            return
        run_dir = Path(result.artifact_dir)
        created_at = _parse_datetime(result.manifest.get("finished_at")) or datetime.now(UTC)
        for artifact_key, relative_path in sorted((result.manifest.get("artifacts") or {}).items()):
            if not isinstance(relative_path, str):
                continue
            path = _artifact_path(run_dir, relative_path)
            data = path.read_bytes()
            self._artifact_index_store.index_artifact(
                ArtifactRef(
                    artifact_id=_artifact_id_from_key(artifact_key),
                    run_id=result.run_id,
                    artifact_type=str(artifact_key),
                    path=Path(relative_path).as_posix(),
                    content_type=_content_type(path),
                    size_bytes=len(data),
                    checksum=sha256(data).hexdigest(),
                    redacted=True,
                    created_at=created_at,
                    metadata={
                        "artifact_key": str(artifact_key),
                        "workflow_id": result.workflow_id,
                        "workflow_version": result.workflow_version,
                        "manifest_schema_version": manifest_schema_version(result.manifest),
                    },
                )
            )
        for artifact_ref in _source_artifact_refs(run_dir, result.manifest):
            self._artifact_index_store.index_artifact(artifact_ref)

    def _index_events(self, result: WorkflowResult) -> None:
        if result.events_path is None:
            return
        events_path = Path(result.events_path)
        if not events_path.exists():
            return
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                event = StorageEventRecord.from_dict(json.loads(stripped))
                payload_step_id = event.payload.get("step_id")
                redaction = self._redactor.redact(
                    event.payload,
                    run_id=result.run_id,
                    artifact_id="events",
                )
                metadata = {
                    **event.metadata,
                    "workflow_version": result.workflow_version,
                }
                if redaction.redacted:
                    metadata["redaction_report"] = redaction.report.to_dict()
                event = replace(
                    event,
                    workflow_id=event.workflow_id or result.workflow_id,
                    step_id=event.step_id or (str(payload_step_id) if payload_step_id else None),
                    payload=redaction.value,
                    redacted=True,
                    metadata=metadata,
                )
                self._event_store.append_event(event)

    def _index_lineage(self, result: WorkflowResult) -> None:
        evidence_bundle = result.output.get("evidence_bundle")
        if evidence_bundle is None:
            return
        refs = lineage_refs_from_evidence_bundle(
            evidence_bundle,
            run_id=result.run_id,
            workflow_id=result.workflow_id,
        )
        self._lineage_store.record_many(refs)


def _artifact_path(run_dir: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid artifact path: {relative_path}")
    path = run_dir / relative
    if not path.exists():
        raise FileNotFoundError(f"artifact file not found: {relative_path}")
    return path


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _artifact_id_from_key(key: str) -> str:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key)).strip("._") or "artifact"
    if safe_key == key:
        return safe_key
    digest = sha256(str(key).encode("utf-8")).hexdigest()[:8]
    return f"{safe_key}-{digest}"


def _source_artifact_refs(run_dir: Path, manifest: dict[str, Any]) -> list[ArtifactRef]:
    artifact_paths = manifest.get("artifacts") or {}
    source_index_path = artifact_paths.get("source_artifacts")
    if not isinstance(source_index_path, str):
        return []
    try:
        index_path = _artifact_path(run_dir, source_index_path)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []

    refs: list[ArtifactRef] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref_payload = entry.get("artifact_ref")
        if not isinstance(ref_payload, dict):
            continue
        try:
            ref = ArtifactRef.from_dict(ref_payload)
            _artifact_path(run_dir, ref.path)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        refs.append(ref)
    return refs


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
