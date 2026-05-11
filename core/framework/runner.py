from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.run_result import RunResult
from core.framework.specs import WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.result import WorkflowResult
from core.framework.workflow.step_runner import FunctionStepRegistry, FunctionStepRunner
from storage.artifacts import ArtifactRef, LocalJsonArtifactIndexStore
from storage.events import EventRecord as StorageEventRecord
from storage.events import event_store_from_env
from storage.lineage import LocalJsonLineageStore, lineage_refs_from_evidence_bundle
from storage.security import StorageRedactor


class WorkflowRunner:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        function_registry: FunctionStepRegistry,
        artifact_index_store: LocalJsonArtifactIndexStore | None = None,
        event_store: Any | None = None,
        lineage_store: LocalJsonLineageStore | None = None,
        redactor: StorageRedactor | None = None,
    ) -> None:
        self._artifact_root = Path(artifact_root)
        self._artifact_manager = ArtifactManager(self._artifact_root)
        self._function_step_runner = FunctionStepRunner(function_registry)
        self._artifact_index_store = artifact_index_store or LocalJsonArtifactIndexStore(
            self._artifact_root / "_records" / "artifact_index"
        )
        self._event_store = event_store or event_store_from_env(artifact_root=self._artifact_root)
        self._lineage_store = lineage_store or LocalJsonLineageStore(
            self._artifact_root / "_records" / "lineage"
        )
        self._redactor = redactor or StorageRedactor()

    def run(
        self,
        workflow: WorkflowSpec,
        request: dict[str, Any],
        *,
        profile: str,
        run_id: str | None = None,
    ) -> RunResult:
        executor = WorkflowExecutor(
            function_step_runner=self._function_step_runner,
            artifact_manager=self._artifact_manager,
        )
        result = executor.execute(workflow, request, profile=profile, run_id=run_id)
        self._persist_storage_indexes(result)
        return RunResult.from_workflow_result(result)

    def _persist_storage_indexes(self, result: WorkflowResult) -> None:
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
                    },
                )
            )

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
